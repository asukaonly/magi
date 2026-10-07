"""Resolve Hub assets once, then use the cancellable shared transfer engine."""

from __future__ import annotations

import asyncio
import fnmatch
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from .model_download import DownloadFile, DownloadTracker, download_files, remove_directory, safe_path


class _Lfs(BaseModel):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class _Sibling(BaseModel):
    rfilename: str
    size: int = Field(ge=0)
    blobId: str = Field(pattern=r"^[a-f0-9]{40}$")
    lfs: _Lfs | None = None


class _Repository(BaseModel):
    sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    siblings: list[_Sibling]


async def download_hub_model(
    repo: str, patterns: list[str], directory: Path, tracker: DownloadTracker,
    proxy_url: str | None = None,
) -> None:
    """Pin the resolved commit and verify both LFS and Git blob content hashes."""
    staging = directory.parent / f".{directory.name}.partial"
    published = False
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, proxy=proxy_url, trust_env=False) as client:
            for attempt in range(3):
                try:
                    response = await client.get(f"https://huggingface.co/api/models/{quote(repo, safe='/')}/revision/main", params={"blobs": "true"})
                    response.raise_for_status()
                    repository = _Repository.model_validate(response.json())
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if attempt == 2 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {408, 429, 500, 502, 503, 504}):
                        raise
                    tracker.phase = "retrying"
                    await asyncio.sleep(2 ** attempt)
        files = [DownloadFile(
            path=item.rfilename,
            url=f"https://huggingface.co/{quote(repo, safe='/')}/resolve/{repository.sha}/{quote(item.rfilename, safe='/')}",
            size=item.size,
            digest=item.lfs.sha256 if item.lfs else item.blobId,
            algorithm="sha256" if item.lfs else "git-sha1",
        ) for item in repository.siblings if any(fnmatch.fnmatchcase(item.rfilename, pattern) for pattern in patterns)]
        if not any(item.path.endswith(".onnx") for item in files) or not any(item.path == "tokenizer.json" for item in files):
            raise ValueError("model_files_missing")
        await download_files(files, staging, tracker, proxy_url)
        # Publish only verified files; keep other installed variants intact.
        for item in files:
            safe_path(directory, item.path)
        directory.mkdir(parents=True, exist_ok=True)
        for item in sorted(files, key=lambda file: file.path.endswith(".onnx")):
            target = safe_path(directory, item.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            (staging / item.path).replace(target)
        published = True
        await remove_directory(staging)
        tracker.phase = "completed"
    except asyncio.CancelledError:
        if published:
            tracker.phase = "completed"
            return
        tracker.phase = "cancelled"
        raise
    except Exception:
        tracker.phase = "failed"
        raise
