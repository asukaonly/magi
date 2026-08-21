"""Durable code-delegation references and strict local artifact cleanup."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chat_assets.paths import normalize_chat_asset_component
from magi_plugin_sdk.subprocess import hidden_process_kwargs

_DELEGATION_ID_PATTERN = re.compile(r"[0-9a-fA-F]{32}")
_STATIC_COMPONENT_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class CodeAgentArtifactDeletionError(RuntimeError):
    """Raised when code-delegation evidence could not be removed completely."""


class CodeAgentArtifactPathError(ValueError):
    """Raised when a code-delegation path cannot be proven to stay in scope."""


@dataclass(frozen=True, slots=True)
class WorkspaceSessionArtifactReference:
    """Exact workspace-owned session cache that must be removed."""

    workspace_path: str
    session_id: str


def normalize_code_agent_delegation_id(value: object) -> str:
    """Return one canonical delegation id that is safe as a path component."""

    normalized = str(value or "").strip()
    if not _DELEGATION_ID_PATTERN.fullmatch(normalized):
        raise CodeAgentArtifactPathError(
            "delegation_id must be a 32-character hexadecimal value"
        )
    return normalized.lower()


def resolve_code_agent_workspace_root(value: str | Path) -> Path:
    """Return one existing canonical workspace without following aliases."""

    raw_path = Path(value).expanduser()
    if not raw_path.is_absolute():
        raise CodeAgentArtifactPathError("workspace root must be absolute")
    if ".." in raw_path.parts:
        raise CodeAgentArtifactPathError(
            "workspace root must not contain parent-directory aliases"
        )
    absolute_path = raw_path.absolute()
    if absolute_path.is_symlink():
        raise CodeAgentArtifactPathError(
            "workspace root must not be a symbolic link"
        )
    try:
        resolved_path = absolute_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CodeAgentArtifactPathError(
            "workspace root could not be resolved"
        ) from exc
    if resolved_path != absolute_path:
        raise CodeAgentArtifactPathError(
            "workspace root must not traverse symbolic links"
        )
    if not resolved_path.is_dir():
        raise CodeAgentArtifactPathError(
            "workspace root must be a directory"
        )
    return resolved_path


def _artifact_identity_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _assert_unambiguous_artifact_child(parent: Path, component: str) -> None:
    expected_identity = _artifact_identity_key(component)
    try:
        entries = parent.iterdir()
        for entry in entries:
            if (
                entry.name != component
                and _artifact_identity_key(entry.name) == expected_identity
            ):
                raise CodeAgentArtifactPathError(
                    "code-agent path component identity is ambiguous"
                )
    except CodeAgentArtifactPathError:
        raise
    except OSError as exc:
        raise CodeAgentArtifactPathError(
            "code-agent parent directory could not be inspected"
        ) from exc


def _existing_real_artifact_directory(path: Path) -> Path | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_dir():
        raise CodeAgentArtifactPathError(
            "code-agent scope is not a real directory"
        )
    try:
        resolved_path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CodeAgentArtifactPathError(
            "code-agent scope could not be resolved"
        ) from exc
    if resolved_path != path:
        raise CodeAgentArtifactPathError(
            "code-agent scope escaped its expected directory"
        )
    return path


def _resolve_artifact_child_directory(
    parent: Path,
    component: str,
    *,
    create: bool,
) -> Path | None:
    if not _STATIC_COMPONENT_PATTERN.fullmatch(component):
        raise CodeAgentArtifactPathError(
            "code-agent path component is invalid"
        )
    _assert_unambiguous_artifact_child(parent, component)
    child = parent / component
    existing = _existing_real_artifact_directory(child)
    if existing is not None or not create:
        return existing
    try:
        child.mkdir()
    except FileExistsError:
        pass
    except OSError as exc:
        raise CodeAgentArtifactPathError(
            "code-agent scope could not be created"
        ) from exc
    return _existing_real_artifact_directory(child)


def _resolve_existing_workspace_session_dir(
    *,
    workspace_root: str | Path,
    session_id: object,
) -> tuple[Path, Path | None]:
    resolved_root = resolve_code_agent_workspace_root(workspace_root)
    normalized_session_id = normalize_chat_asset_component(
        session_id,
        label="session_id",
    )
    current = resolved_root
    for component in (".magi", "sessions", normalized_session_id):
        child = _resolve_artifact_child_directory(
            current,
            component,
            create=False,
        )
        if child is None:
            return resolved_root, None
        current = child
    return resolved_root, current


@dataclass(frozen=True, slots=True)
class CodeAgentArtifactLocator:
    """Validated filesystem locations for one exact code delegation."""

    workspace_root: Path
    session_id: str
    delegation_id: str

    @classmethod
    def resolve(
        cls,
        *,
        workspace_root: str | Path,
        session_id: object,
        delegation_id: object,
    ) -> "CodeAgentArtifactLocator":
        return cls(
            workspace_root=resolve_code_agent_workspace_root(workspace_root),
            session_id=normalize_chat_asset_component(
                session_id,
                label="session_id",
            ),
            delegation_id=normalize_code_agent_delegation_id(delegation_id),
        )

    @property
    def sessions_root(self) -> Path:
        return self.workspace_root / ".magi" / "sessions"

    @property
    def session_root(self) -> Path:
        return self.sessions_root / self.session_id

    @property
    def delegations_root(self) -> Path:
        return self.session_root / "delegations"

    @property
    def delegation_dir(self) -> Path:
        return self.delegations_root / self.delegation_id

    @property
    def worktrees_root(self) -> Path:
        return self.session_root / "worktrees"

    @property
    def worktree_dir(self) -> Path:
        return self.worktrees_root / self.delegation_id

    def ensure_delegation_dir(self) -> Path:
        """Create and validate the directory that owns delegation evidence."""

        delegation_dir = self._resolve_scope(
            (
                ".magi",
                "sessions",
                self.session_id,
                "delegations",
                self.delegation_id,
            ),
            create=True,
        )
        if delegation_dir is None:  # pragma: no cover - create=True guarantees a path
            raise CodeAgentArtifactPathError(
                "delegation directory was not created"
            )
        return delegation_dir

    def ensure_worktrees_root(self) -> Path:
        """Create and validate the parent directory for isolated worktrees."""

        worktrees_root = self._resolve_scope(
            (".magi", "sessions", self.session_id, "worktrees"),
            create=True,
        )
        if worktrees_root is None:  # pragma: no cover - create=True guarantees a path
            raise CodeAgentArtifactPathError(
                "worktrees directory was not created"
            )
        return worktrees_root

    def existing_delegation_dir(self) -> Path | None:
        """Return the exact delegation directory when it exists safely."""

        return self._resolve_scope(
            (
                ".magi",
                "sessions",
                self.session_id,
                "delegations",
                self.delegation_id,
            ),
            create=False,
        )

    def existing_worktree_dir(self) -> Path | None:
        """Return the exact worktree directory when it exists safely."""

        return self._resolve_scope(
            (
                ".magi",
                "sessions",
                self.session_id,
                "worktrees",
                self.delegation_id,
            ),
            create=False,
        )

    def validate_existing_scopes(self) -> None:
        """Read-only validation of any artifact scopes already on disk."""

        self.existing_delegation_dir()
        self.existing_worktree_dir()

    def ensure_delegation_child_dir(self, component: str) -> Path:
        """Create one static child directory below the delegation scope."""

        delegation_dir = self.ensure_delegation_dir()
        child = _resolve_artifact_child_directory(
            delegation_dir,
            component,
            create=True,
        )
        if child is None:  # pragma: no cover - create=True guarantees a path
            raise CodeAgentArtifactPathError(
                "code-agent child directory was not created"
            )
        return child

    def artifact_file(
        self,
        filename: str,
        *,
        require_delegation: bool,
    ) -> Path:
        """Return one non-symlink regular-file location in this delegation."""

        if not _STATIC_COMPONENT_PATTERN.fullmatch(filename):
            raise CodeAgentArtifactPathError(
                "code-agent artifact filename is invalid"
            )
        delegation_dir = (
            self.existing_delegation_dir()
            if require_delegation
            else self.ensure_delegation_dir()
        )
        if delegation_dir is None:
            raise CodeAgentArtifactPathError(
                "delegation directory does not exist"
            )
        path = delegation_dir / filename
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise CodeAgentArtifactPathError(
                    "code-agent artifact is not a real regular file"
                )
            try:
                resolved_path = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise CodeAgentArtifactPathError(
                    "code-agent artifact could not be resolved"
                ) from exc
            if resolved_path != path:
                raise CodeAgentArtifactPathError(
                    "code-agent artifact escaped its expected directory"
                )
        return path

    def validate_worktree_path(self, worktree_path: str | Path) -> Path:
        """Reject a worktree argument that does not match this identity."""

        raw_path = Path(worktree_path).expanduser()
        if (
            not raw_path.is_absolute()
            or ".." in raw_path.parts
            or raw_path.absolute() != self.worktree_dir
        ):
            raise CodeAgentArtifactPathError(
                "worktree path does not match the delegation identity"
            )
        existing = self.existing_worktree_dir()
        return existing if existing is not None else self.worktree_dir

    def _resolve_scope(
        self,
        components: tuple[str, ...],
        *,
        create: bool,
    ) -> Path | None:
        current = self.workspace_root
        for component in components:
            child = _resolve_artifact_child_directory(
                current,
                component,
                create=create,
            )
            if child is None:
                return None
            current = child
        return current


@dataclass(frozen=True, slots=True)
class CodeAgentDelegationReference:
    """Stable identity required to recover or remove one code delegation."""

    session_id: str
    delegation_id: str
    turn_id: str
    workspace_path: str

    def to_message_payload(self) -> dict[str, str]:
        """Return the session-local representation persisted on chat messages."""

        return {
            "delegation_id": self.delegation_id,
            "turn_id": self.turn_id,
            "workspace_path": self.workspace_path,
        }


def normalize_code_agent_delegation_references(
    payload: Any,
    *,
    session_id: object,
) -> list[CodeAgentDelegationReference]:
    """Parse the explicit message contract without accepting path-like IDs."""

    if not isinstance(payload, dict):
        return []
    try:
        normalized_session_id = normalize_chat_asset_component(
            session_id,
            label="session_id",
        )
    except ValueError:
        return []
    raw_references = payload.get("code_agent_delegations")
    if not isinstance(raw_references, list):
        return []

    references: list[CodeAgentDelegationReference] = []
    seen: set[str] = set()
    for raw_reference in raw_references:
        if not isinstance(raw_reference, dict):
            continue
        turn_id = str(raw_reference.get("turn_id") or "").strip()
        workspace_path = str(raw_reference.get("workspace_path") or "").strip()
        try:
            normalized_delegation_id = normalize_code_agent_delegation_id(
                raw_reference.get("delegation_id")
            )
        except CodeAgentArtifactPathError:
            continue
        if not turn_id or not workspace_path:
            continue
        if not Path(workspace_path).expanduser().is_absolute():
            continue
        if normalized_delegation_id in seen:
            continue
        seen.add(normalized_delegation_id)
        references.append(
            CodeAgentDelegationReference(
                session_id=normalized_session_id,
                delegation_id=normalized_delegation_id,
                turn_id=turn_id,
                workspace_path=workspace_path,
            )
        )
    return references


class CodeAgentArtifactGC:
    """Remove Magi-owned logs, diffs, and temporary worktrees."""

    def delete_references(
        self,
        references: list[CodeAgentDelegationReference],
    ) -> int:
        """Delete each exact delegation scope, leaving applied workspace edits."""

        deleted = 0
        seen: set[tuple[str, str, str]] = set()
        for reference in references:
            identity = (
                reference.workspace_path,
                reference.session_id,
                reference.delegation_id,
            )
            if identity in seen:
                continue
            seen.add(identity)
            if self._delete_reference(reference):
                deleted += 1
        return deleted

    def _delete_reference(self, reference: CodeAgentDelegationReference) -> bool:
        raw_workspace_root = Path(reference.workspace_path).expanduser()
        if not raw_workspace_root.is_absolute():
            raise CodeAgentArtifactDeletionError(
                "Code delegation workspace must be absolute"
            )
        if raw_workspace_root.is_symlink():
            raise CodeAgentArtifactDeletionError(
                "Code delegation workspace is not a real directory"
            )
        if not raw_workspace_root.exists():
            return False
        try:
            locator = CodeAgentArtifactLocator.resolve(
                workspace_root=raw_workspace_root,
                session_id=reference.session_id,
                delegation_id=reference.delegation_id,
            )
            worktree_path = locator.existing_worktree_dir()
            delegation_path = locator.existing_delegation_dir()
        except (CodeAgentArtifactPathError, ValueError) as exc:
            raise CodeAgentArtifactDeletionError(
                "Code delegation identity or path is not safe"
            ) from exc
        existed = worktree_path is not None or delegation_path is not None

        removed_git_artifact = self._remove_worktree_and_branch(
            workspace_root=locator.workspace_root,
            worktree_path=worktree_path,
            delegation_id=locator.delegation_id,
        )
        if delegation_path is not None:
            self._remove_tree(delegation_path)

        for directory in (
            locator.worktrees_root,
            locator.delegations_root,
            locator.session_root,
            locator.sessions_root,
        ):
            self._remove_empty_directory(directory)
        return existed or removed_git_artifact

    def _remove_worktree_and_branch(
        self,
        *,
        workspace_root: Path,
        worktree_path: Path | None,
        delegation_id: str,
    ) -> bool:
        removed = worktree_path is not None
        if worktree_path is not None:
            self._run_git(
                workspace_root,
                "worktree",
                "remove",
                "--force",
                str(worktree_path),
            )
            if worktree_path.exists():
                self._remove_tree(worktree_path)
            if worktree_path.exists() or worktree_path.is_symlink():
                raise CodeAgentArtifactDeletionError(
                    "Code delegation worktree could not be deleted"
                )
        prune_result = self._run_git(workspace_root, "worktree", "prune")
        if prune_result.returncode != 0:
            raise CodeAgentArtifactDeletionError(
                "Code delegation worktree metadata could not be deleted"
            )
        branch = f"refs/heads/magi/delegation/{delegation_id}"
        branch_state = self._run_git(
            workspace_root,
            "show-ref",
            "--verify",
            "--quiet",
            branch,
        )
        if branch_state.returncode == 0:
            removed = True
            self._run_git(
                workspace_root,
                "branch",
                "-D",
                f"magi/delegation/{delegation_id}",
            )
            branch_state = self._run_git(
                workspace_root,
                "show-ref",
                "--verify",
                "--quiet",
                branch,
            )
        if branch_state.returncode not in {1}:
            raise CodeAgentArtifactDeletionError(
                "Code delegation branch could not be deleted"
            )
        return removed

    @staticmethod
    def _run_git(
        workspace_root: Path,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                check=False,
                **hidden_process_kwargs(),
            )
        except OSError as exc:
            raise CodeAgentArtifactDeletionError(
                "Code delegation git metadata could not be inspected"
            ) from exc

    @staticmethod
    def _remove_tree(path: Path) -> None:
        def handle_remove_error(
            function: Any,
            failed_path: str,
            _error_info: Any,
        ) -> None:
            try:
                os.chmod(failed_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
                function(failed_path)
            except OSError:
                return

        try:
            shutil.rmtree(path, onerror=handle_remove_error)
        except OSError as exc:
            raise CodeAgentArtifactDeletionError(
                "Code delegation directory could not be deleted"
            ) from exc
        if path.exists() or path.is_symlink():
            raise CodeAgentArtifactDeletionError(
                "Code delegation directory could not be deleted"
            )

    @staticmethod
    def _remove_empty_directory(path: Path | None) -> None:
        if path is None or not path.exists():
            return
        try:
            path.rmdir()
        except OSError:
            return


class WorkspaceSessionArtifactGC:
    """Remove complete Magi session caches from exact user workspaces."""

    def delete_references(
        self,
        references: list[WorkspaceSessionArtifactReference],
    ) -> int:
        deleted = 0
        seen: set[tuple[str, str]] = set()
        for reference in references:
            identity = (reference.workspace_path, reference.session_id)
            if identity in seen:
                continue
            seen.add(identity)
            if self._delete_reference(reference):
                deleted += 1
        return deleted

    def _delete_reference(
        self,
        reference: WorkspaceSessionArtifactReference,
    ) -> bool:
        raw_workspace_root = Path(reference.workspace_path).expanduser()
        if not raw_workspace_root.is_absolute():
            raise CodeAgentArtifactDeletionError(
                "Workspace session cache root must be absolute"
            )
        if raw_workspace_root.is_symlink():
            raise CodeAgentArtifactDeletionError(
                "Workspace session cache root is not a real directory"
            )
        if not raw_workspace_root.exists():
            return False
        try:
            workspace_root, session_dir = _resolve_existing_workspace_session_dir(
                workspace_root=raw_workspace_root,
                session_id=reference.session_id,
            )
        except (CodeAgentArtifactPathError, ValueError) as exc:
            raise CodeAgentArtifactDeletionError(
                "Workspace session cache identity or path is not safe"
            ) from exc
        if session_dir is None:
            return False

        CodeAgentArtifactGC._remove_tree(session_dir)
        CodeAgentArtifactGC._remove_empty_directory(workspace_root / ".magi" / "sessions")
        return True


__all__ = [
    "CodeAgentArtifactDeletionError",
    "CodeAgentArtifactGC",
    "CodeAgentArtifactLocator",
    "CodeAgentArtifactPathError",
    "CodeAgentDelegationReference",
    "WorkspaceSessionArtifactGC",
    "WorkspaceSessionArtifactReference",
    "normalize_code_agent_delegation_id",
    "normalize_code_agent_delegation_references",
    "resolve_code_agent_workspace_root",
]
