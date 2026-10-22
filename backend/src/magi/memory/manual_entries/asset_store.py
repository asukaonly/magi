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
from magi_plugin_sdk.fs import atomic_write_managed_bytes, read_managed_bytes, UnsafeManagedPathError

from .asset_types import ACCEPTED_CONTENT_TYPES, EXT_TO_CONTENT_TYPE, ASSET_SCHEME, MAX_UPLOAD_BYTES

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
        if not data or len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("Asset size is outside the accepted range")
        digest = hashlib.sha256(data).hexdigest()
        path = self._safe_path_for(digest, ext)
        if path is None:
            raise RuntimeError("Asset path resolved outside the owned media directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique temporary files and fsync make concurrent equal-content uploads safe.
        if self.resolve(f"{ASSET_SCHEME}://{digest}.{ext}") != (data, EXT_TO_CONTENT_TYPE[ext]):
            atomic_write_managed_bytes(path, data)
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
            data = read_managed_bytes(path, max_bytes=MAX_UPLOAD_BYTES)
        except (OSError, UnsafeManagedPathError):
            return None
        if data is None or hashlib.sha256(data).hexdigest() != digest:
            return None
        return data, content_type

    def has_asset(self, asset_ref: str) -> bool:
        """Return whether a canonical ref points to a stored file owned by this store."""
        return self.resolve(asset_ref) is not None

    def clear(self) -> int:
        """Delete every manual-entry asset while preserving the owned root directory."""
        if self._root.is_symlink() or self._root.parent.is_symlink():
            raise RuntimeError("Asset root is not an owned directory")
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
            if self._root.is_symlink() or self._root.parent.is_symlink():
                return None
            root = self._root.resolve(strict=False)
            raw_path = self._path_for(digest, ext)
            if raw_path.is_symlink() or raw_path.parent.is_symlink():
                return None
            candidate = raw_path.resolve(strict=False)
            candidate.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None
        return candidate
