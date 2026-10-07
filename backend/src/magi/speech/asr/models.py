"""Verified model downloads with one writer and atomic publication."""

from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path
import httpx
from ...utils.model_download import DownloadFile, DownloadTracker, download_files, remove_directory, safe_path
from .catalog import CATALOG, ModelSpec
from .contracts import ASRError, ASRModel

DOWNLOAD_TIMEOUT = 1800


class _ModelInstallation:
    def __init__(self, root: Path, model: ModelSpec) -> None:
        self.root, self.model = root, model
        self.directory = root / model.id
        self.task: asyncio.Task[None] | None = None
        self.info = ASRModel(
            id=model.id,
            label=model.label,
            family=model.family,
            size_bytes=sum(f.size for f in model.files),
            license=model.license,
            license_url=model.license_url,
            source_url=model.source_url,
            recommended=model.recommended,
            state="missing",
        )
        self._verified: tuple[tuple[int, int, int], ...] | None = None
        self.mutation_lock = asyncio.Lock()
        self.transfer: DownloadTracker | None = None

    def _signature(self) -> tuple[tuple[int, int, int], ...]:
        if self.directory.is_symlink():
            raise ASRError("model_not_ready", 409)
        result = []
        for item in self.model.files:
            path = self.directory / item.name
            for parent in path.parents:
                if parent == self.directory:
                    break
                if parent.is_symlink():
                    raise ASRError("model_not_ready", 409)
            if path.is_symlink() or not path.is_file():
                raise ASRError("model_not_ready", 409)
            stat = path.stat()
            if stat.st_size != item.size:
                raise ASRError("model_not_ready", 409)
            result.append((stat.st_size, stat.st_mtime_ns, stat.st_ino))
        return tuple(result)

    def _verify(self) -> None:
        signature = self._signature()
        if signature == self._verified:
            return
        for item in self.model.files:
            digest = hashlib.sha256()
            with (self.directory / item.name).open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != item.sha256:
                raise ASRError("model_not_ready", 409)
        if self._signature() != signature:
            raise ASRError("model_not_ready", 409)
        self._verified = signature

    async def ready(self) -> bool:
        try:
            await asyncio.to_thread(self._verify)
            return True
        except (ASRError, OSError):
            return False

    async def snapshot(self) -> ASRModel:
        if self.task is None or self.task.done():
            if await self.ready():
                self.info.state = "ready"
            elif self.info.state == "ready":
                self.info.state = "missing"
        result = self.info.model_copy(deep=True)
        result.download = self.transfer.snapshot() if self.transfer else None
        return result

    async def download(self, proxy_url: str | None = None) -> ASRModel:
        async with self.mutation_lock:
            if self.task is not None and not self.task.done():
                return await self.snapshot()
            if await self.ready():
                return await self.snapshot()
            self.info.state, self.info.error = "downloading", None
            self.transfer = DownloadTracker()
            self.task = asyncio.create_task(self._bounded_download(proxy_url))
            return await self.snapshot()

    async def _bounded_download(self, proxy_url: str | None) -> None:
        try:
            await asyncio.wait_for(self._download(proxy_url), timeout=DOWNLOAD_TIMEOUT)
        except asyncio.TimeoutError:
            self.info.state, self.info.error = "failed", "model_download_failed"
            if self.transfer:
                self.transfer.phase = "failed"

    async def _download(self, proxy_url: str | None) -> None:
        staging = self.root / f".{self.model.id}.partial"
        assert self.transfer is not None
        try:
            safe_path(self.directory, ".download.json")
            await download_files([
                DownloadFile(item.name, self.model.file_url(item), item.size, item.sha256)
                for item in self.model.files
            ], staging, self.transfer, proxy_url)
            if self.directory.exists():
                await remove_directory(self.directory)
            (staging / ".download.json").unlink()
            staging.rename(self.directory)
            self._verified = self._signature()
            self.info.state = "ready"
            self.transfer.phase = "completed"
        except asyncio.CancelledError:
            self.info.state = "cancelled"
            self.transfer.phase = "cancelled"
            raise
        except (OSError, ValueError, ASRError, httpx.HTTPError):
            self.info.state, self.info.error = "failed", "model_download_failed"
            self.transfer.phase = "failed"

    async def cancel(self) -> ASRModel:
        async with self.mutation_lock:
            await self._cancel()
            return await self.snapshot()

    async def _cancel(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.info.state = "cancelled"
            if self.transfer:
                self.transfer.phase = "cancelled"

    async def delete(self) -> ASRModel:
        async with self.mutation_lock:
            await self._cancel()
            if self.directory.is_symlink():
                raise ASRError("unsafe_model_path")
            if self.directory.exists():
                await remove_directory(self.directory)
            staging = self.root / f".{self.model.id}.partial"
            safe_path(staging, ".download.json")
            if staging.exists():
                await remove_directory(staging)
            self._verified = None
            self.info.state, self.info.error = "missing", None
            self.transfer = None
            return await self.snapshot()


class ASRModelStore:
    """Own independent installations for the bounded, pinned model catalog."""

    def __init__(self, root: Path) -> None:
        self.installations = {
            model.id: _ModelInstallation(root, model) for model in CATALOG.values()
        }

    def get(self, model_id: str) -> _ModelInstallation:
        try:
            return self.installations[model_id]
        except KeyError as exc:
            raise ASRError("unknown_model", 404) from exc

    async def ready(self, model_id: str) -> bool:
        return await self.get(model_id).ready()

    async def snapshot(self, selected_model_id: str | None = None) -> list[ASRModel]:
        entries = []
        for installation in sorted(
            self.installations.values(),
            key=lambda item: (not item.model.featured, not item.model.recommended),
        ):
            model = await installation.snapshot()
            if (
                installation.model.featured
                or model.id == selected_model_id
                or model.state != "missing"
            ):
                entries.append(model)
        return entries

    async def cancel_all(self) -> None:
        await asyncio.gather(*(model.cancel() for model in self.installations.values()))
