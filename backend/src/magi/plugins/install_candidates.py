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
DEFAULT_MAX_CANDIDATES = 16
DEFAULT_MAX_CANDIDATE_BYTES = 64 * 1024 * 1024
_CANDIDATE_ID_LENGTH = 32


class PluginInstallCandidateError(RuntimeError):
    """Base error for plugin install candidate lifecycle failures."""


class PluginInstallCandidateNotFoundError(PluginInstallCandidateError):
    """Raised when a candidate does not exist or has expired."""


class PluginInstallCandidateClaimedError(PluginInstallCandidateError):
    """Raised when a candidate has already started installation."""


class PluginInstallCandidateDigestMismatchError(PluginInstallCandidateError):
    """Raised when the approved content does not match the staged archive."""


class PluginInstallCandidateCapacityError(PluginInstallCandidateError):
    """Raised when the process-wide candidate count or byte budget is exhausted."""


@dataclass(slots=True)
class PluginInstallCandidate:
    """One inspected archive awaiting explicit installation approval."""

    candidate_id: str
    archive_path: Path
    archive_suffix: str
    original_filename: str
    archive_sha256: str
    manifest: PluginManifest
    created_at: float
    expires_at: float
    claimed_at: float | None = None
    archive_bytes: bytes | None = None


class PluginInstallCandidateStore:
    """Own short-lived upload directories and single-use candidate records."""

    def __init__(
        self,
        root_dir: Path | None = None,
        *,
        ttl_seconds: int = DEFAULT_CANDIDATE_TTL_SECONDS,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        max_candidate_bytes: int = DEFAULT_MAX_CANDIDATE_BYTES,
        now=time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_candidates <= 0 or max_candidate_bytes <= 0:
            raise ValueError("Candidate capacity limits must be positive")
        default_root = get_runtime_paths().cache_dir / "plugin-install-candidates"
        self._root_dir = (root_dir or default_root).resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._ttl_seconds = ttl_seconds
        self._max_candidates = max_candidates
        self._max_candidate_bytes = max_candidate_bytes
        self._now = now
        self._records: dict[str, PluginInstallCandidate] = {}
        self._reserved_until: dict[str, float] = {}
        self._expiry_timers: dict[str, threading.Timer] = {}
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
            if len(self._records) + len(self._reserved_until) >= self._max_candidates:
                raise PluginInstallCandidateCapacityError(
                    "Too many plugin install candidates are already waiting"
                )
            candidate_id = uuid.uuid4().hex
            candidate_dir = self._candidate_dir(candidate_id)
            candidate_dir.mkdir(mode=0o700)
            archive_path = candidate_dir / f"archive{archive_suffix}"
            expires_at = self._now() + self._ttl_seconds
            self._reserved_until[candidate_id] = expires_at
            self._schedule_expiry_locked(candidate_id, expires_at)
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
            if candidate_id not in self._reserved_until:
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
            archive_size = resolved_archive.stat().st_size
            if archive_size + self._active_candidate_bytes_locked() > self._max_candidate_bytes:
                raise PluginInstallCandidateCapacityError(
                    "Plugin install candidates exceed the process byte budget"
                )
            created_at = self._now()
            candidate = PluginInstallCandidate(
                candidate_id=candidate_id,
                archive_path=resolved_archive,
                archive_suffix=(".tar.gz" if resolved_archive.name.endswith(".tar.gz") else ".zip"),
                original_filename=original_filename,
                archive_sha256=archive_sha256,
                manifest=manifest,
                created_at=created_at,
                expires_at=created_at + self._ttl_seconds,
            )
            self._reserved_until.pop(candidate_id, None)
            self._records[candidate_id] = candidate
            self._schedule_expiry_locked(candidate.candidate_id, candidate.expires_at)
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
            try:
                archive_bytes = candidate.archive_path.read_bytes()
            except OSError as exc:
                raise PluginInstallCandidateDigestMismatchError(
                    "Inspected plugin package is no longer available"
                ) from exc
            actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
            if actual_sha256 != candidate.archive_sha256:
                raise PluginInstallCandidateDigestMismatchError(
                    "Inspected plugin package changed before installation"
                )
            candidate.archive_path.unlink(missing_ok=True)
            candidate.archive_bytes = archive_bytes
            candidate.claimed_at = self._now()
            timer = self._expiry_timers.pop(candidate_id, None)
            if timer is not None:
                timer.cancel()
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
        expired_ids.extend(
            candidate_id
            for candidate_id, expires_at in self._reserved_until.items()
            if expires_at <= now
        )
        for candidate_id in expired_ids:
            self._remove_candidate_locked(candidate_id)

    def _active_candidate_bytes_locked(self) -> int:
        total = 0
        for candidate in self._records.values():
            if candidate.archive_bytes is not None:
                total += len(candidate.archive_bytes)
                continue
            try:
                total += candidate.archive_path.stat().st_size
            except OSError:
                continue
        return total

    def _schedule_expiry_locked(self, candidate_id: str, expires_at: float) -> None:
        previous_timer = self._expiry_timers.pop(candidate_id, None)
        if previous_timer is not None:
            previous_timer.cancel()
        delay = max(0.0, expires_at - self._now())
        timer = threading.Timer(delay, self._expire_candidate, args=(candidate_id,))
        timer.daemon = True
        self._expiry_timers[candidate_id] = timer
        timer.start()

    def _expire_candidate(self, candidate_id: str) -> None:
        with self._lock:
            candidate = self._records.get(candidate_id)
            candidate_expired = (
                candidate is not None
                and candidate.claimed_at is None
                and candidate.expires_at <= self._now()
            )
            reservation_expired = (
                self._reserved_until.get(candidate_id, float("inf")) <= self._now()
            )
            if candidate_expired or reservation_expired:
                self._remove_candidate_locked(candidate_id)

    def _prune_orphan_directories(self) -> None:
        for child in self._root_dir.iterdir():
            if not child.is_dir() or not _is_candidate_id(child.name):
                continue
            _remove_owned_directory(self._root_dir, child)

    def _remove_candidate_locked(self, candidate_id: str) -> None:
        self._records.pop(candidate_id, None)
        self._reserved_until.pop(candidate_id, None)
        timer = self._expiry_timers.pop(candidate_id, None)
        if timer is not None:
            timer.cancel()
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
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_MAX_CANDIDATE_BYTES",
    "DEFAULT_CANDIDATE_TTL_SECONDS",
    "PluginInstallCandidate",
    "PluginInstallCandidateCapacityError",
    "PluginInstallCandidateClaimedError",
    "PluginInstallCandidateDigestMismatchError",
    "PluginInstallCandidateError",
    "PluginInstallCandidateNotFoundError",
    "PluginInstallCandidateStore",
    "get_plugin_install_candidate_store",
]
