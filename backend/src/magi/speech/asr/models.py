"""Verified model downloads with one writer and atomic publication."""

from __future__ import annotations
import asyncio
import hashlib
import shutil
from pathlib import Path
import httpx
from .catalog import CATALOG, LICENSE_URL, SOURCE_URL, ModelSpec
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
            size_bytes=sum(f.size for f in model.files),
            license="Apache-2.0 (upstream model card)",
            license_url=LICENSE_URL,
            source_url=SOURCE_URL,
            state="missing",
        )
        self._verified: tuple[tuple[int, int, int], ...] | None = None
        self.mutation_lock = asyncio.Lock()

    def _signature(self) -> tuple[tuple[int, int, int], ...]:
        if self.directory.is_symlink():
            raise ASRError("model_not_ready", 409)
        result = []
        for item in self.model.files:
            path = self.directory / item.name
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
                self.info.state, self.info.progress = "ready", 100
            elif self.info.state == "ready":
                self.info.state = "missing"
        return self.info.model_copy(deep=True)

    async def download(self, proxy_url: str | None = None) -> ASRModel:
        async with self.mutation_lock:
            if self.task is not None and not self.task.done():
                return self.info.model_copy(deep=True)
            if await self.ready():
                return await self.snapshot()
            self.info.state, self.info.error, self.info.progress = "downloading", None, 0
            self.task = asyncio.create_task(self._bounded_download(proxy_url))
            return self.info.model_copy(deep=True)

    async def _bounded_download(self, proxy_url: str | None) -> None:
        try:
            await asyncio.wait_for(self._download(proxy_url), timeout=DOWNLOAD_TIMEOUT)
        except asyncio.TimeoutError:
            self.info.state, self.info.error = "failed", "model_download_failed"

    async def _download(self, proxy_url: str | None) -> None:
        staging = self.root / f".{self.model.id}.partial"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if staging.is_symlink() or self.directory.is_symlink():
                raise ASRError("unsafe_model_path")
            if staging.exists():
                await asyncio.to_thread(shutil.rmtree, staging)
            staging.mkdir()
            received = 0
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=60, proxy=proxy_url, trust_env=False
            ) as client:
                for item in self.model.files:
                    digest, size = hashlib.sha256(), 0
                    async with client.stream("GET", item.url) as response:
                        response.raise_for_status()
                        with (staging / item.name).open("wb") as output:
                            async for chunk in response.aiter_bytes(65536):
                                size += len(chunk)
                                if size > item.size:
                                    raise ASRError("model_checksum_failed")
                                output.write(chunk)
                                digest.update(chunk)
                                received += len(chunk)
                                self.info.progress = received / self.info.size_bytes * 100
                    if size != item.size or digest.hexdigest() != item.sha256:
                        raise ASRError("model_checksum_failed")
            if self.directory.exists():
                await asyncio.to_thread(shutil.rmtree, self.directory)
            staging.rename(self.directory)
            self._verified = self._signature()
            self.info.state = "ready"
        except asyncio.CancelledError:
            self.info.state = "cancelled"
            raise
        except Exception:
            self.info.state, self.info.error = "failed", "model_download_failed"
        finally:
            if staging.exists() and not staging.is_symlink():
                await asyncio.to_thread(shutil.rmtree, staging)

    async def cancel(self) -> ASRModel:
        async with self.mutation_lock:
            await self._cancel()
            return await self.snapshot()

    async def _cancel(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.info.state = "cancelled"

    async def delete(self) -> ASRModel:
        async with self.mutation_lock:
            await self._cancel()
            if self.directory.is_symlink():
                raise ASRError("unsafe_model_path")
            if self.directory.exists():
                await asyncio.to_thread(shutil.rmtree, self.directory)
            self._verified = None
            self.info.state, self.info.error, self.info.progress = "missing", None, 0
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

    async def snapshot(self) -> list[ASRModel]:
        return [await model.snapshot() for model in self.installations.values()]

    async def cancel_all(self) -> None:
        await asyncio.gather(*(model.cancel() for model in self.installations.values()))
