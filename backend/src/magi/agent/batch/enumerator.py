"""Enumerators: expand a seed_spec into item inputs. Task-agnostic.

MVP: 'fs' source (deterministic filesystem walk). 'prompt' seeder is Phase 2.
The engine calls this in the planning phase to seed the manifest; what the
inputs mean is the handler's business. Returns a LAZY iterator so a huge tree
never materializes as one big list.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any, Iterator


def enumerate_seed(seed_spec: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Expand a seed_spec into a lazy stream of opaque item-input dicts.
    Source is validated eagerly; the filesystem walk itself stays lazy."""
    source = seed_spec.get("source")
    if source == "fs":
        return _enumerate_fs(seed_spec)
    raise ValueError(f"unsupported seed source: {source!r}")


def _enumerate_fs(seed_spec: dict[str, Any]) -> Iterator[dict[str, Any]]:
    root = Path(str(seed_spec["root"])).expanduser()
    patterns = seed_spec.get("patterns") or ["*"]
    recursive = bool(seed_spec.get("recursive", True))
    if not root.exists():
        return
    if recursive:
        candidates = (
            Path(dirpath) / fname
            for dirpath, _dirs, fnames in os.walk(root)
            for fname in fnames
        )
    else:
        candidates = (p for p in root.iterdir() if p.is_file())
    for p in sorted(candidates):
        if any(fnmatch.fnmatch(p.name, pat) for pat in patterns):
            yield {"path": str(p)}
