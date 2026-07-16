"""Deterministic identity helpers for local context records."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

from ...core.workspace import WorkspacePaths, WorkspaceStateStore
from .models import ContextDimension

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_alias(value: str) -> str:
    """Return a locale-independent alias comparison form."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", text).casefold()


def canonical_workspace_path(workspace_path: str) -> str:
    """Canonicalize a local workspace path without requiring it to exist."""
    raw = str(workspace_path or "").strip()
    if not raw:
        raise ValueError("Workspace path is required")
    resolved = WorkspacePaths.from_root(raw).workspace_root
    return unicodedata.normalize("NFC", os.path.normcase(str(resolved)))


def _digest(*parts: str) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _claimed_workspace_id(workspace_path: str) -> str | None:
    """Return a durable identity only when its root matches this workspace."""
    paths = WorkspacePaths.from_root(workspace_path)
    state_store = WorkspaceStateStore(paths)
    persisted = state_store.read_persisted()
    if persisted is not None:
        try:
            previous_root = Path(persisted.workspace_root).expanduser().resolve(strict=False)
            use_persisted_id = previous_root == paths.workspace_root
        except (OSError, RuntimeError, ValueError):
            use_persisted_id = False
        if use_persisted_id:
            return persisted.workspace_id
    return None


def _workspace_id(workspace_path: str) -> str:
    """Resolve a read-only identity from durable state or the canonical path."""
    paths = WorkspacePaths.from_root(workspace_path)
    persisted_id = _claimed_workspace_id(workspace_path)
    if persisted_id is not None:
        return persisted_id
    return paths.workspace_id


def claimed_workspace_identity(workspace_path: str) -> tuple[str, str] | None:
    """Return catalog identities only for a durably claimed workspace."""
    workspace_id = _claimed_workspace_id(workspace_path)
    if workspace_id is None:
        return None
    binding_id = f"workspace_{_digest(workspace_id)}"
    context_id = f"ctx_project_{_digest('project', 'workspace', binding_id)}"
    return binding_id, context_id


def workspace_binding_id(workspace_path: str) -> str:
    """Return a non-reversible stable identity for one local workspace."""
    return f"workspace_{_digest(_workspace_id(workspace_path))}"


def context_id_for_workspace(workspace_path: str) -> str:
    """Return the stable project context identity for one workspace."""
    return f"ctx_project_{_digest('project', 'workspace', workspace_binding_id(workspace_path))}"


def context_id_for_legacy_value(
    dimension: ContextDimension,
    value: str,
) -> str:
    """Preserve one legacy free-text value as an isolated custom identity."""
    normalized = normalize_alias(value)
    if not normalized:
        raise ValueError("Legacy context value is required")
    return f"ctx_{dimension}_{_digest(dimension, 'legacy_custom', normalized)}"


def context_id_for_builtin(
    dimension: ContextDimension,
    canonical_name: str,
) -> str:
    """Return the stable identity for one code-defined local context."""
    normalized = normalize_alias(canonical_name)
    if not normalized:
        raise ValueError("Built-in context name is required")
    return f"ctx_{dimension}_{_digest(dimension, 'built_in', normalized)}"


__all__ = [
    "canonical_workspace_path",
    "claimed_workspace_identity",
    "context_id_for_builtin",
    "context_id_for_legacy_value",
    "context_id_for_workspace",
    "normalize_alias",
    "workspace_binding_id",
]
