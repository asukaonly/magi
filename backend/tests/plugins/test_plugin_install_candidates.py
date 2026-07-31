from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import time

import pytest

from magi.plugins.contracts import PluginManifest
from magi.plugins.install_candidates import (
    PluginInstallCandidateCapacityError,
    PluginInstallCandidateClaimedError,
    PluginInstallCandidateDigestMismatchError,
    PluginInstallCandidateNotFoundError,
    PluginInstallCandidateStore,
)
from magi.plugins.package_identity import compute_package_sha256


def _manifest() -> PluginManifest:
    return PluginManifest(
        id="demo-plugin",
        name="Demo",
        version="1.0.0",
        entry_module="plugin",
        entry_class="DemoPlugin",
    )


def _package_sha256() -> str:
    with tempfile.TemporaryDirectory(prefix="magi-candidate-package-") as tmp:
        package_dir = Path(tmp)
        (package_dir / "plugin.toml").write_text(
            '[plugin]\nid = "demo-plugin"\nname = "Demo"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )
        (package_dir / "plugin.py").write_text("VALUE = 1\n", encoding="utf-8")
        return compute_package_sha256(package_dir)


def _register_candidate(
    store: PluginInstallCandidateStore,
    *,
    payload: bytes = b"archive",
    original_filename: str = "demo.zip",
):
    candidate_id, archive_path = store.reserve_archive(".zip")
    archive_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return store.register(
        candidate_id=candidate_id,
        archive_path=archive_path,
        original_filename=original_filename,
        archive_sha256=digest,
        package_sha256=_package_sha256(),
        manifest=_manifest(),
    )


def test_candidate_claim_binds_install_to_the_inspected_archive(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _register_candidate(store)

    claimed = store.claim(
        candidate.candidate_id,
        expected_sha256=candidate.archive_sha256,
    )

    assert claimed is candidate
    assert claimed.claimed_at is not None
    assert claimed.archive_bytes == b"archive"
    assert claimed.package_sha256 == candidate.package_sha256
    assert not claimed.archive_path.exists()
    with pytest.raises(PluginInstallCandidateClaimedError):
        store.claim(
            candidate.candidate_id,
            expected_sha256=candidate.archive_sha256,
        )


def test_candidate_claim_rejects_approval_for_different_content(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _register_candidate(store)

    with pytest.raises(PluginInstallCandidateDigestMismatchError):
        store.claim(candidate.candidate_id, expected_sha256="0" * 64)

    assert store.get(candidate.candidate_id).claimed_at is None


def test_candidate_claim_detects_archive_tampering_after_inspection(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _register_candidate(store)
    candidate.archive_path.write_bytes(b"changed")

    with pytest.raises(PluginInstallCandidateDigestMismatchError):
        store.claim(
            candidate.candidate_id,
            expected_sha256=candidate.archive_sha256,
        )


def test_expired_candidate_removes_only_its_owned_directory(tmp_path: Path) -> None:
    current_time = [100.0]
    root = tmp_path / "candidates"
    sentinel = tmp_path / "keep"
    sentinel.mkdir()
    store = PluginInstallCandidateStore(
        root,
        ttl_seconds=10,
        now=lambda: current_time[0],
    )
    candidate = _register_candidate(
        store,
        original_filename="../../keep",
    )

    current_time[0] = 111.0
    store.prune_expired()

    assert sentinel.is_dir()
    assert not candidate.archive_path.parent.exists()
    with pytest.raises(PluginInstallCandidateNotFoundError):
        store.get(candidate.candidate_id)


def test_completed_candidate_cleans_claimed_files(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _register_candidate(store)
    store.claim(candidate.candidate_id, expected_sha256=candidate.archive_sha256)

    store.complete(candidate.candidate_id)

    assert not candidate.archive_path.parent.exists()
    with pytest.raises(PluginInstallCandidateNotFoundError):
        store.get(candidate.candidate_id)


def test_claimed_snapshot_is_not_changed_by_recreating_the_staging_path(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _register_candidate(store, payload=b"approved")

    claimed = store.claim(
        candidate.candidate_id,
        expected_sha256=candidate.archive_sha256,
    )
    candidate.archive_path.write_bytes(b"replacement")

    assert claimed.archive_bytes == b"approved"


def test_candidate_count_limit_applies_before_upload(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(
        tmp_path / "candidates",
        max_candidates=1,
    )
    store.reserve_archive(".zip")

    with pytest.raises(PluginInstallCandidateCapacityError):
        store.reserve_archive(".zip")


def test_abandoned_upload_reservation_expires_without_registration(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(
        tmp_path / "candidates",
        ttl_seconds=1,
        max_candidates=1,
    )
    _candidate_id, archive_path = store.reserve_archive(".zip")
    deadline = time.monotonic() + 2.0

    while archive_path.parent.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not archive_path.parent.exists()
    store.reserve_archive(".zip")


def test_process_restart_removes_unusable_candidate_directories(tmp_path: Path) -> None:
    root = tmp_path / "candidates"
    orphan_dir = root / ("a" * 32)
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "archive.zip").write_bytes(b"orphan")

    PluginInstallCandidateStore(root)

    assert not orphan_dir.exists()


def test_candidate_byte_budget_rejects_excess_staged_content(tmp_path: Path) -> None:
    store = PluginInstallCandidateStore(
        tmp_path / "candidates",
        max_candidate_bytes=8,
    )
    _register_candidate(store, payload=b"12345")
    candidate_id, archive_path = store.reserve_archive(".zip")
    archive_path.write_bytes(b"6789")

    with pytest.raises(PluginInstallCandidateCapacityError):
        store.register(
            candidate_id=candidate_id,
            archive_path=archive_path,
            original_filename="second.zip",
            archive_sha256=hashlib.sha256(b"6789").hexdigest(),
            package_sha256=_package_sha256(),
            manifest=_manifest(),
        )


def test_expiry_timer_removes_abandoned_candidate_without_another_request(
    tmp_path: Path,
) -> None:
    store = PluginInstallCandidateStore(
        tmp_path / "candidates",
        ttl_seconds=1,
    )
    candidate = _register_candidate(store)
    deadline = time.monotonic() + 2.0

    while candidate.archive_path.parent.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not candidate.archive_path.parent.exists()
    with pytest.raises(PluginInstallCandidateNotFoundError):
        store.get(candidate.candidate_id)
