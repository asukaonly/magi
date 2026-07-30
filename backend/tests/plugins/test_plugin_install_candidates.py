from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from magi.plugins.contracts import PluginManifest
from magi.plugins.install_candidates import (
    PluginInstallCandidateClaimedError,
    PluginInstallCandidateDigestMismatchError,
    PluginInstallCandidateNotFoundError,
    PluginInstallCandidateStore,
)


def _manifest() -> PluginManifest:
    return PluginManifest(
        id="demo-plugin",
        name="Demo",
        version="1.0.0",
        entry_module="plugin",
        entry_class="DemoPlugin",
    )


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
