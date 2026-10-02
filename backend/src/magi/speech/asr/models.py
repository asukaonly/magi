"""Verified model downloads with one writer and atomic publication."""

from __future__ import annotations
import asyncio
import hashlib
import shutil
from pathlib import Path
import httpx
from .catalog import FILES, LICENSE_URL, MODEL_ID, SOURCE_URL
from .contracts import ASRError, ASRModel


class ASRModelStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / MODEL_ID
        self.task: asyncio.Task[None] | None = None
        self.info = ASRModel(
            id=MODEL_ID,
            label="Paraformer Chinese / English (int8)",
            size_bytes=sum(f.size for f in FILES),
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
        for item in FILES:
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
        for item in FILES:
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

    async def download(self) -> ASRModel:
        async with self.mutation_lock:
            if self.task is not None and not self.task.done():
                return self.info.model_copy(deep=True)
            if await self.ready():
                return await self.snapshot()
            self.info.state, self.info.error, self.info.progress = "downloading", None, 0
            self.task = asyncio.create_task(self._bounded_download())
            return self.info.model_copy(deep=True)

    async def _bounded_download(self) -> None:
        try:
            await asyncio.wait_for(self._download(), timeout=1800)
        except asyncio.TimeoutError:
            self.info.state, self.info.error = "failed", "model_download_failed"

    async def _download(self) -> None:
        staging = self.root / f".{MODEL_ID}.partial"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if staging.is_symlink() or self.directory.is_symlink():
                raise ASRError("unsafe_model_path")
            if staging.exists():
                await asyncio.to_thread(shutil.rmtree, staging)
            staging.mkdir()
            received = 0
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                for item in FILES:
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
