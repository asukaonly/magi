"""Bounded, resumable model transfers with byte-based progress and verification."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import httpx
from pydantic import BaseModel, Field

Phase = Literal["connecting", "downloading", "retrying", "verifying", "completed", "cancelled", "failed"]


class DownloadProgress(BaseModel):
    phase: Phase = "connecting"
    downloaded_bytes: int = Field(default=0, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    speed_bps: float = Field(default=0, ge=0)
    eta_seconds: float | None = Field(default=None, ge=0)
    files_completed: int = Field(default=0, ge=0)
    total_files: int = Field(default=0, ge=0)


class ModelDownloadStatus(BaseModel):
    model_id: str
    status: Literal["downloading", "completed", "failed", "cancelled", "not_found"]
    download: DownloadProgress | None = None
    error: str | None = None


@dataclass(frozen=True)
class DownloadFile:
    path: str
    url: str
    size: int
    digest: str
    algorithm: Literal["sha256", "git-sha1"] = "sha256"


class DownloadTracker:
    """Keep transfer rate separate from bytes recovered from a previous attempt."""

    def __init__(self) -> None:
        self.phase: Phase = "connecting"
        self.total: int | None = None
        self.counts: dict[str, int] = {}
        self.phases: dict[str, Phase] = {}
        self.transferred = 0
        self.samples: deque[tuple[float, int]] = deque([(time.monotonic(), 0)])
        self.last_byte = 0.0

    def received(self, name: str, count: int) -> None:
        self.counts[name] += count
        self.transferred += count
        self.last_byte = time.monotonic()
        if self.last_byte - self.samples[-1][0] >= 0.25:
            self.samples.append((self.last_byte, self.transferred))
        while len(self.samples) > 2 and self.samples[1][0] < self.last_byte - 5:
            self.samples.popleft()

    def snapshot(self) -> DownloadProgress:
        now = time.monotonic()
        phase = self.phase
        if phase not in {"completed", "failed", "cancelled"}:
            phase = next((p for p in ("downloading", "retrying", "verifying", "connecting")
                          if p in self.phases.values()), phase)
        speed = 0.0
        elapsed = now - self.samples[0][0]
        if phase == "downloading" and now - self.last_byte < 3 and elapsed >= 1:
            speed = (self.transferred - self.samples[0][1]) / elapsed
        # Avoid unstable estimates at startup or while the connection is stalled.
        rates = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(self.samples, list(self.samples)[1:])]
        stable = len(rates) >= 4 and min(rates) > 0 and max(rates) < min(rates) * 3
        received = sum(self.counts.values())
        eta = max(0, self.total - received) / speed if self.total and speed and stable else None
        return DownloadProgress(
            phase=phase, downloaded_bytes=received, total_bytes=self.total,
            speed_bps=speed, eta_seconds=eta,
            files_completed=sum(p == "completed" for p in self.phases.values()),
            total_files=len(self.phases),
        )


def safe_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or "\\" in name:
        raise ValueError("unsafe_model_path")
    path = root / name
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("unsafe_model_path")
        if parent == root:
            break
    return path


def verified(path: Path, item: DownloadFile) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != item.size:
        return False
    digest = hashlib.sha256() if item.algorithm == "sha256" else hashlib.sha1()
    if item.algorithm == "git-sha1":
        digest.update(f"blob {item.size}\0".encode())
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == item.digest


async def _transfer(
    client: httpx.AsyncClient, item: DownloadFile, staging: Path, tracker: DownloadTracker,
) -> None:
    path = safe_path(staging, item.path)
    partial = safe_path(staging, item.path + ".magi-part")
    path.parent.mkdir(parents=True, exist_ok=True)
    tracker.phases[item.path] = "verifying"
    if await asyncio.to_thread(verified, path, item):
        tracker.counts[item.path] = item.size
        tracker.phases[item.path] = "completed"
        return
    path.unlink(missing_ok=True)
    for attempt in range(3):
        if partial.exists() and partial.stat().st_size > item.size:
            partial.unlink()
        offset = partial.stat().st_size if partial.exists() else 0
        tracker.counts[item.path] = offset
        try:
            if offset < item.size or not partial.exists():
                tracker.phases[item.path] = "connecting"
                headers = {"Accept-Encoding": "identity"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                async with client.stream("GET", item.url, headers=headers) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
                        if not match or tuple(map(int, match.groups())) != (offset, item.size - 1, item.size):
                            raise ValueError("invalid_download_range")
                    elif response.status_code == 200:
                        offset = 0
                        tracker.counts[item.path] = 0
                    else:
                        raise ValueError("invalid_download_response")
                    tracker.phases[item.path] = "downloading"
                    with partial.open("ab" if offset else "wb") as output:
                        async for chunk in response.aiter_bytes():
                            if tracker.counts[item.path] + len(chunk) > item.size:
                                raise ValueError("model_checksum_failed")
                            output.write(chunk)
                            tracker.received(item.path, len(chunk))
            tracker.phases[item.path] = "verifying"
            if partial.stat().st_size < item.size:
                raise httpx.ReadError("Model transfer ended before all bytes arrived")
            if not await asyncio.to_thread(verified, partial, item):
                partial.unlink(missing_ok=True)
                tracker.counts[item.path] = 0
                raise ValueError("model_checksum_failed")
            partial.replace(path)
            tracker.phases[item.path] = "completed"
            return
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {408, 429, 500, 502, 503, 504}:
                raise
            if attempt == 2:
                raise
            tracker.phases[item.path] = "retrying"
            await asyncio.sleep(2 ** attempt)


async def download_files(
    files: list[DownloadFile], staging: Path, tracker: DownloadTracker,
    proxy_url: str | None = None,
) -> None:
    """Download at most four files at once; cancellation retains resumable bytes."""
    if not files or len({item.path for item in files}) != len(files):
        raise ValueError("invalid_model_manifest")
    safe_path(staging, ".download.json")
    manifest = [asdict(item) for item in files]
    manifest_path = staging / ".download.json"
    if staging.exists():
        try:
            matches = json.loads(manifest_path.read_text()) == manifest
        except (OSError, ValueError):
            matches = False
        if not matches:
            await remove_directory(staging)
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest))
    tracker.total = sum(item.size for item in files)
    tracker.counts = {item.path: 0 for item in files}
    tracker.phases = {item.path: "connecting" for item in files}
    slots = asyncio.Semaphore(4)
    tasks: list[asyncio.Task[None]] = []
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, proxy=proxy_url, trust_env=False) as client:
            async def one(item: DownloadFile) -> None:
                async with slots:
                    await _transfer(client, item, staging, tracker)
            tasks = [asyncio.create_task(one(item)) for item in files]
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=1800)
        tracker.phase = "verifying"
    except asyncio.CancelledError:
        tracker.phase = "cancelled"
        raise
    except Exception:
        tracker.phase = "failed"
        raise
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def remove_directory(directory: Path) -> None:
    """Drain filesystem cleanup before cancellation releases the job owner."""
    task = asyncio.create_task(asyncio.to_thread(shutil.rmtree, directory))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
