"""Content identities shared by file mutations and their validation evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_content_digest(path: Path) -> str | None:
    """Hash the current bytes, returning unknown when they cannot be read."""
    try:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def file_validation_target(path: str | Path) -> dict[str, str | None]:
    """Identify the actual file and content version produced by a mutation."""
    absolute = Path(path).resolve()
    return {"path": str(absolute), "content_sha256": file_content_digest(absolute)}
