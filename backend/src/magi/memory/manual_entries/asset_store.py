"""Content-addressed storage for manual-entry image attachments.

Layout under the magi data root::

    media/manual_entries/<sha[:2]>/<sha>.<ext>

The two-char prefix directory keeps any single dir below a few hundred
files even with thousands of attachments. The sha256 in the filename
gives us free deduplication: the same image bytes pasted twice resolves
to the same file.

Asset refs look like ``manual-entry-asset://<sha>.<ext>``. The existing
``/timeline/asset/{ref:path}`` route picks them up by scheme.

Phase A intentionally does not auto-convert HEIC — Pillow / pillow-heif
aren't in the backend's runtime deps yet. HEIC uploads are rejected
with a 415 so the user gets a clear "please convert first" message.
Adding HEIC support is a Phase B follow-up that pulls in pillow-heif.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Optional

# Content-Type → file extension. The keys are what we accept on upload;
# anything else gets a 415 at the route layer.
ACCEPTED_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}

# Content types we explicitly recognize but don't yet support — produces
# a clearer error message than a generic "not allowed".
KNOWN_UNSUPPORTED_CONTENT_TYPES: dict[str, str] = {
    "image/heic": "HEIC 暂不支持，请先转换为 JPG 或 PNG。",
    "image/heif": "HEIF 暂不支持，请先转换为 JPG 或 PNG。",
}

# Reverse map for content-type lookup on serve.
EXT_TO_CONTENT_TYPE: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

ASSET_SCHEME = "manual-entry-asset"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_CANONICAL_EXTENSIONS = frozenset(ACCEPTED_CONTENT_TYPES.values())
_ASSET_REF_PATTERN = re.compile(
    rf"{re.escape(ASSET_SCHEME)}://"
    rf"(?P<digest>[0-9a-f]{{64}})\."
    rf"(?P<ext>{'|'.join(sorted(_CANONICAL_EXTENSIONS))})\Z"
)


class ManualEntryAssetStore:
    """Read/write content-addressed image bytes on local disk."""

    def __init__(self, *, media_root: str | Path) -> None:
        self._root = Path(media_root).expanduser() / "manual_entries"

    def store_bytes(self, data: bytes, *, content_type: str) -> str:
        """Persist bytes under their sha256 and return an asset_ref.

        Idempotent: writing the same bytes twice resolves to the same
        file (and ref). Returns the ``manual-entry-asset://...`` ref.
        """
        ext = ACCEPTED_CONTENT_TYPES.get(content_type.lower())
        if ext is None:
            raise ValueError(f"Unsupported content type: {content_type}")
        digest = hashlib.sha256(data).hexdigest()
        path = self._safe_path_for(digest, ext)
        if path is None:
            raise RuntimeError("Asset path resolved outside the owned media directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Write atomically: temp file in same dir, then rename
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.rename(path)
        return f"{ASSET_SCHEME}://{digest}.{ext}"

    def resolve(self, asset_ref: str) -> Optional[tuple[bytes, str]]:
        """Resolve an asset_ref to (bytes, content_type), or None if absent."""
        parsed = self._parse_asset_ref(asset_ref)
        if parsed is None:
            return None
        digest, ext = parsed
        content_type = EXT_TO_CONTENT_TYPE.get(ext.lower())
        if content_type is None:
            return None
        path = self._safe_path_for(digest, ext)
        if path is None or not path.is_file():
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        return data, content_type

    def has_asset(self, asset_ref: str) -> bool:
        """Return whether a canonical ref points to a stored file owned by this store."""
        parsed = self._parse_asset_ref(asset_ref)
        if parsed is None:
            return False
        path = self._safe_path_for(*parsed)
        return path is not None and path.is_file()

    def clear(self) -> int:
        """Delete every manual-entry asset while preserving the owned root directory."""
        if not self._root.exists():
            self._root.mkdir(parents=True, exist_ok=True)
            return 0
        removed = sum(1 for path in self._root.rglob("*") if path.is_file())
        shutil.rmtree(self._root)
        self._root.mkdir(parents=True, exist_ok=True)
        return removed

    def _path_for(self, digest: str, ext: str) -> Path:
        return self._root / digest[:2] / f"{digest}.{ext}"

    @staticmethod
    def _parse_asset_ref(asset_ref: str) -> tuple[str, str] | None:
        match = _ASSET_REF_PATTERN.fullmatch(str(asset_ref or ""))
        if match is None:
            return None
        return match.group("digest"), match.group("ext")

    def _safe_path_for(self, digest: str, ext: str) -> Path | None:
        """Resolve one asset path and reject symlink or traversal escapes."""
        try:
            root = self._root.resolve(strict=False)
            candidate = self._path_for(digest, ext).resolve(strict=False)
            candidate.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None
        return candidate
