"""Short-lived, immutable candidates for uploaded plugin packages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import threading
import time
import uuid

from ..utils.runtime import get_runtime_paths
from .contracts import PluginManifest


DEFAULT_CANDIDATE_TTL_SECONDS = 15 * 60
_CANDIDATE_ID_LENGTH = 32


class PluginInstallCandidateError(RuntimeError):
    """Base error for plugin install candidate lifecycle failures."""


class PluginInstallCandidateNotFoundError(PluginInstallCandidateError):
    """Raised when a candidate does not exist or has expired."""


class PluginInstallCandidateClaimedError(PluginInstallCandidateError):
    """Raised when a candidate has already started installation."""


class PluginInstallCandidateDigestMismatchError(PluginInstallCandidateError):
    """Raised when the approved content does not match the staged archive."""


@dataclass(slots=True)
class PluginInstallCandidate:
    """One inspected archive awaiting explicit installation approval."""

    candidate_id: str
    archive_path: Path
    original_filename: str
    archive_sha256: str
    manifest: PluginManifest
    created_at: float
    expires_at: float
    claimed_at: float | None = None


class PluginInstallCandidateStore:
    """Own short-lived upload directories and single-use candidate records."""

    def __init__(
        self,
        root_dir: Path | None = None,
        *,
        ttl_seconds: int = DEFAULT_CANDIDATE_TTL_SECONDS,
        now=time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        default_root = get_runtime_paths().cache_dir / "plugin-install-candidates"
        self._root_dir = (root_dir or default_root).resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._ttl_seconds = ttl_seconds
        self._now = now
        self._records: dict[str, PluginInstallCandidate] = {}
        self._reserved_ids: set[str] = set()
        self._lock = threading.RLock()
        self._prune_orphan_directories()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def reserve_archive(self, archive_suffix: str) -> tuple[str, Path]:
        """Reserve a server-owned path for an upload before inspection."""

        if archive_suffix not in {".tar.gz", ".zip"}:
            raise ValueError(f"Unsupported archive suffix: {archive_suffix}")
        with self._lock:
            self._prune_expired_locked()
            candidate_id = uuid.uuid4().hex
            candidate_dir = self._candidate_dir(candidate_id)
            candidate_dir.mkdir(mode=0o700)
            archive_path = candidate_dir / f"archive{archive_suffix}"
            self._reserved_ids.add(candidate_id)
            return candidate_id, archive_path

    def register(
        self,
        *,
        candidate_id: str,
        archive_path: Path,
        original_filename: str,
        archive_sha256: str,
        manifest: PluginManifest,
    ) -> PluginInstallCandidate:
        """Register a successfully inspected staged archive."""

        with self._lock:
            self._prune_expired_locked()
            if candidate_id not in self._reserved_ids:
                raise PluginInstallCandidateNotFoundError("Plugin install candidate not reserved")
            expected_dir = self._candidate_dir(candidate_id)
            resolved_archive = archive_path.resolve()
            if resolved_archive.parent != expected_dir or not resolved_archive.is_file():
                raise PluginInstallCandidateError(
                    "Plugin install candidate archive is outside its reserved directory"
                )
            actual_sha256 = _sha256_file(resolved_archive)
            if actual_sha256 != archive_sha256:
                raise PluginInstallCandidateDigestMismatchError(
                    "Plugin install candidate changed during inspection"
                )
            created_at = self._now()
            candidate = PluginInstallCandidate(
                candidate_id=candidate_id,
                archive_path=resolved_archive,
                original_filename=original_filename,
                archive_sha256=archive_sha256,
                manifest=manifest,
                created_at=created_at,
                expires_at=created_at + self._ttl_seconds,
            )
            self._reserved_ids.discard(candidate_id)
            self._records[candidate_id] = candidate
            return candidate

    def get(self, candidate_id: str) -> PluginInstallCandidate:
        """Return an unexpired candidate without consuming it."""

        with self._lock:
            self._prune_expired_locked()
            candidate = self._records.get(candidate_id)
            if candidate is None:
                raise PluginInstallCandidateNotFoundError(
                    "Plugin install candidate not found or expired"
                )
            return candidate

    def claim(
        self,
        candidate_id: str,
        *,
        expected_sha256: str,
    ) -> PluginInstallCandidate:
        """Consume a candidate for exactly one install job."""

        with self._lock:
            candidate = self.get(candidate_id)
            if candidate.claimed_at is not None:
                raise PluginInstallCandidateClaimedError(
                    "Plugin install candidate is already being installed"
                )
            if candidate.archive_sha256 != expected_sha256:
                raise PluginInstallCandidateDigestMismatchError(
                    "Approved plugin package does not match the inspected package"
                )
            if not candidate.archive_path.is_file():
                raise PluginInstallCandidateDigestMismatchError(
                    "Inspected plugin package is no longer available"
                )
            actual_sha256 = _sha256_file(candidate.archive_path)
            if actual_sha256 != candidate.archive_sha256:
                raise PluginInstallCandidateDigestMismatchError(
                    "Inspected plugin package changed before installation"
                )
            candidate.claimed_at = self._now()
            return candidate

    def discard(self, candidate_id: str) -> None:
        """Remove an unused or completed candidate and its owned files."""

        with self._lock:
            candidate = self._records.get(candidate_id)
            if candidate is not None and candidate.claimed_at is not None:
                raise PluginInstallCandidateClaimedError(
                    "Plugin install candidate is already being installed"
                )
            self._remove_candidate_locked(candidate_id)

    def complete(self, candidate_id: str) -> None:
        """Remove a claimed candidate after its install job terminates."""

        with self._lock:
            self._remove_candidate_locked(candidate_id)

    def prune_expired(self) -> None:
        """Delete all expired candidate records and abandoned files."""

        with self._lock:
            self._prune_expired_locked()

    def _prune_expired_locked(self) -> None:
        now = self._now()
        expired_ids = [
            candidate_id
            for candidate_id, candidate in self._records.items()
            if candidate.expires_at <= now and candidate.claimed_at is None
        ]
        for candidate_id in expired_ids:
            self._remove_candidate_locked(candidate_id)

    def _prune_orphan_directories(self) -> None:
        cutoff = self._now() - self._ttl_seconds
        for child in self._root_dir.iterdir():
            if not child.is_dir() or not _is_candidate_id(child.name):
                continue
            try:
                modified_at = child.stat().st_mtime
            except OSError:
                continue
            if modified_at <= cutoff:
                _remove_owned_directory(self._root_dir, child)

    def _remove_candidate_locked(self, candidate_id: str) -> None:
        self._records.pop(candidate_id, None)
        self._reserved_ids.discard(candidate_id)
        if _is_candidate_id(candidate_id):
            _remove_owned_directory(self._root_dir, self._candidate_dir(candidate_id))

    def _candidate_dir(self, candidate_id: str) -> Path:
        if not _is_candidate_id(candidate_id):
            raise PluginInstallCandidateNotFoundError("Invalid plugin install candidate id")
        candidate_dir = (self._root_dir / candidate_id).resolve()
        if candidate_dir.parent != self._root_dir:
            raise PluginInstallCandidateError(
                "Plugin install candidate directory escaped its managed root"
            )
        return candidate_dir


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_candidate_id(value: str) -> bool:
    return len(value) == _CANDIDATE_ID_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _remove_owned_directory(root_dir: Path, candidate_dir: Path) -> None:
    try:
        resolved = candidate_dir.resolve()
    except OSError:
        return
    if resolved.parent != root_dir:
        return
    if candidate_dir.is_symlink():
        candidate_dir.unlink(missing_ok=True)
        return
    shutil.rmtree(candidate_dir, ignore_errors=True)


_candidate_store: PluginInstallCandidateStore | None = None
_candidate_store_lock = threading.Lock()


def get_plugin_install_candidate_store() -> PluginInstallCandidateStore:
    """Return the process-wide upload candidate store."""

    global _candidate_store
    if _candidate_store is None:
        with _candidate_store_lock:
            if _candidate_store is None:
                _candidate_store = PluginInstallCandidateStore()
    return _candidate_store


__all__ = [
    "DEFAULT_CANDIDATE_TTL_SECONDS",
    "PluginInstallCandidate",
    "PluginInstallCandidateClaimedError",
    "PluginInstallCandidateDigestMismatchError",
    "PluginInstallCandidateError",
    "PluginInstallCandidateNotFoundError",
    "PluginInstallCandidateStore",
    "get_plugin_install_candidate_store",
]
