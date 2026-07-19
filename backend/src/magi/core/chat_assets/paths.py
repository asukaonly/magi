"""Trusted path boundary for managed chat assets."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ...utils.runtime import RuntimePaths, get_runtime_paths

SAFE_CHAT_ASSET_COMPONENT_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
_SAFE_CHAT_ASSET_COMPONENT = re.compile(SAFE_CHAT_ASSET_COMPONENT_PATTERN)


def verified_chat_resources_dir(runtime_paths: RuntimePaths) -> Path:
    """Return the canonical chat-resources root without following retargets."""

    base_path = runtime_paths.base_dir.expanduser().absolute()
    resources_path = runtime_paths.chat_resources_dir.expanduser().absolute()
    expected_resources = (
        base_path.resolve()
        / resources_path.relative_to(base_path)
    )
    if resources_path.resolve() != expected_resources:
        raise ValueError("Managed chat resources root was retargeted")
    return expected_resources


def verified_chat_asset_root(
    root_dir: Path,
    runtime_paths: RuntimePaths,
) -> Path:
    """Return one canonical asset root without following scope retargets."""

    base_path = runtime_paths.base_dir.expanduser().absolute()
    canonical_base_path = base_path.resolve()
    root_path = root_dir.expanduser().absolute()
    try:
        relative_root = root_path.relative_to(base_path)
    except ValueError:
        relative_root = root_path.relative_to(canonical_base_path)
    expected_root = canonical_base_path / relative_root
    expected_resources = verified_chat_resources_dir(runtime_paths)
    expected_root.relative_to(expected_resources)
    if root_path.resolve() != expected_root:
        raise ValueError("Managed chat asset root is outside chat resources")
    return expected_root


def normalize_chat_asset_component(value: object, *, label: str) -> str:
    """Validate one identifier before using it as a filesystem component."""

    normalized = str(value or "").strip()
    if not _SAFE_CHAT_ASSET_COMPONENT.fullmatch(normalized):
        raise ValueError(
            f"{label} must contain only letters, numbers, underscores, or hyphens "
            "and be at most 128 characters"
        )
    return normalized


def is_safe_chat_asset_component(value: object) -> bool:
    """Return whether a value is safe as one managed asset path component."""

    return bool(_SAFE_CHAT_ASSET_COMPONENT.fullmatch(str(value or "").strip()))


def asset_scope_identity_key(value: object) -> str:
    """Return a conservative identity key for one filesystem path component."""

    return unicodedata.normalize("NFC", str(value or "")).casefold()


def _assert_no_casefold_scope_collision(parent: Path, component: str) -> None:
    """Reject filesystem scopes whose spelling is not identity-stable."""

    if not parent.exists():
        return
    expected_identity = asset_scope_identity_key(component)
    for child in parent.iterdir():
        if (
            child.name != component
            and asset_scope_identity_key(child.name) == expected_identity
        ):
            raise ValueError("Managed chat asset scope is ambiguous")


def _resolve_scope_directory(
    parent: Path,
    component: str,
    *,
    create: bool,
) -> Path | None:
    """Resolve one exact directory component without accepting aliases."""

    _assert_no_casefold_scope_collision(parent, component)
    candidate = parent / component
    if candidate.exists() or candidate.is_symlink():
        if (
            candidate.is_symlink()
            or not candidate.is_dir()
            or candidate.resolve() != candidate
        ):
            raise ValueError(
                "Managed chat asset path is outside the expected scope directory"
            )
        return candidate
    if not create:
        return None
    candidate.mkdir()
    return candidate


def resolve_chat_asset_session_directory(
    root_dir: Path,
    *,
    session_id: object,
    runtime_paths: RuntimePaths,
) -> Path | None:
    """Resolve an existing exact session directory under one asset root."""

    normalized_session_id = normalize_chat_asset_component(
        session_id,
        label="session_id",
    )
    root = verified_chat_asset_root(root_dir, runtime_paths)
    if not root.exists():
        return None
    return _resolve_scope_directory(
        root,
        normalized_session_id,
        create=False,
    )


def resolve_chat_asset_turn_directory(
    root_dir: Path,
    *,
    session_id: object,
    turn_id: object,
    runtime_paths: RuntimePaths,
) -> Path | None:
    """Resolve an existing exact turn directory under one asset root."""

    normalized_turn_id = normalize_chat_asset_component(
        turn_id,
        label="turn_id",
    )
    session_dir = resolve_chat_asset_session_directory(
        root_dir,
        session_id=session_id,
        runtime_paths=runtime_paths,
    )
    if session_dir is None:
        return None
    return _resolve_scope_directory(
        session_dir,
        normalized_turn_id,
        create=False,
    )


def build_chat_derived_path(
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    runtime_paths: RuntimePaths | None = None,
) -> Path:
    """Build the one valid derived-text path for a managed attachment."""

    paths = runtime_paths or get_runtime_paths()
    normalized_session_id = normalize_chat_asset_component(
        session_id,
        label="session_id",
    )
    normalized_turn_id = normalize_chat_asset_component(
        turn_id,
        label="turn_id",
    )
    normalized_attachment_id = normalize_chat_asset_component(
        attachment_id,
        label="attachment_id",
    )
    return (
        verified_chat_asset_root(paths.chat_derived_dir, paths)
        / normalized_session_id
        / normalized_turn_id
        / f"{normalized_attachment_id}.txt"
    )


def prepare_chat_asset_turn_directory(
    root_dir: Path,
    *,
    session_id: object,
    turn_id: object,
    runtime_paths: RuntimePaths,
) -> Path:
    """Create an exact managed turn directory without following scope symlinks."""

    normalized_session_id = normalize_chat_asset_component(
        session_id,
        label="session_id",
    )
    normalized_turn_id = normalize_chat_asset_component(
        turn_id,
        label="turn_id",
    )
    root = verified_chat_asset_root(root_dir, runtime_paths)
    root.mkdir(parents=True, exist_ok=True)
    session_dir = _resolve_scope_directory(
        root,
        normalized_session_id,
        create=True,
    )
    if session_dir is None:
        raise ValueError("Managed chat session asset directory could not be created")
    turn_dir = _resolve_scope_directory(
        session_dir,
        normalized_turn_id,
        create=True,
    )
    if turn_dir is None:
        raise ValueError("Managed chat turn asset directory could not be created")
    return turn_dir


def prepare_chat_derived_write_path(
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    runtime_paths: RuntimePaths | None = None,
) -> Path:
    """Create and verify the exact parent directory for a derived-text write."""

    paths = runtime_paths or get_runtime_paths()
    target = build_chat_derived_path(
        session_id=session_id,
        turn_id=turn_id,
        attachment_id=attachment_id,
        runtime_paths=paths,
    )
    target_dir = prepare_chat_asset_turn_directory(
        paths.chat_derived_dir,
        session_id=session_id,
        turn_id=turn_id,
        runtime_paths=paths,
    )
    if target_dir != target.parent or target.is_symlink():
        raise ValueError("Managed chat derived path is outside the expected turn directory")
    return target


def resolve_chat_derived_file(
    raw_path: object,
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    runtime_paths: RuntimePaths | None = None,
) -> Path | None:
    """Resolve an existing derived-text file only at its exact owned path."""

    paths = runtime_paths or get_runtime_paths()
    normalized_path = str(raw_path or "").strip()
    if not normalized_path:
        return None
    try:
        expected = build_chat_derived_path(
            session_id=session_id,
            turn_id=turn_id,
            attachment_id=attachment_id,
            runtime_paths=paths,
        )
        expected_parent = resolve_chat_asset_turn_directory(
            paths.chat_derived_dir,
            session_id=session_id,
            turn_id=turn_id,
            runtime_paths=paths,
        )
        if expected_parent is None or expected_parent != expected.parent:
            return None
        candidate = Path(normalized_path)
        if not candidate.is_absolute():
            candidate = paths.base_dir / candidate
        if (
            candidate.parent.resolve() != expected_parent
            or candidate.name != expected.name
            or expected.is_symlink()
            or not expected.is_file()
        ):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return expected


def resolve_chat_attachment_file(
    raw_path: object,
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    runtime_paths: RuntimePaths | None = None,
) -> Path | None:
    """Resolve an existing original attachment inside its exact turn scope."""

    paths = runtime_paths or get_runtime_paths()
    normalized_path = str(raw_path or "").strip()
    if not normalized_path:
        return None
    try:
        normalized_session_id = normalize_chat_asset_component(
            session_id,
            label="session_id",
        )
        normalized_turn_id = normalize_chat_asset_component(
            turn_id,
            label="turn_id",
        )
        normalized_attachment_id = normalize_chat_asset_component(
            attachment_id,
            label="attachment_id",
        )
        candidate = Path(normalized_path)
        if not candidate.is_absolute():
            candidate = paths.base_dir / candidate
        candidate_parent = candidate.parent.resolve()
        for root_dir in (paths.chat_images_dir, paths.chat_files_dir):
            expected_parent = resolve_chat_asset_turn_directory(
                root_dir,
                session_id=normalized_session_id,
                turn_id=normalized_turn_id,
                runtime_paths=paths,
            )
            if expected_parent is None:
                continue
            if candidate_parent != expected_parent:
                continue
            filename_prefix = f"{normalized_attachment_id}__"
            if (
                not candidate.name.startswith(filename_prefix)
                or candidate.name == filename_prefix
            ):
                return None
            target = expected_parent / candidate.name
            if target.is_symlink() or not target.is_file():
                return None
            return target
    except (OSError, RuntimeError, ValueError):
        return None
    return None


__all__ = [
    "SAFE_CHAT_ASSET_COMPONENT_PATTERN",
    "asset_scope_identity_key",
    "build_chat_derived_path",
    "is_safe_chat_asset_component",
    "normalize_chat_asset_component",
    "prepare_chat_asset_turn_directory",
    "prepare_chat_derived_write_path",
    "resolve_chat_asset_session_directory",
    "resolve_chat_asset_turn_directory",
    "resolve_chat_attachment_file",
    "resolve_chat_derived_file",
    "verified_chat_asset_root",
    "verified_chat_resources_dir",
]
