"""Tests for workspace-cache record models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk.workspace_cache.contracts import (
    EditRecord,
    ReadRecord,
    SnapshotRef,
    WorkspaceMetadata,
)

SCHEMA_VERSION = 1


def test_read_record_round_trip():
    rec = ReadRecord(
        path="src/foo.py",
        sha256="0" * 64,
        size_bytes=42,
        line_count=7,
        mtime_ms=1_700_000_000_000,
        ts_ms=1_700_000_000_500,
    )
    payload = rec.model_dump()
    assert ReadRecord.model_validate(payload) == rec


def test_read_record_rejects_short_hash():
    with pytest.raises(ValidationError):
        ReadRecord(
            path="x",
            sha256="abc",
            size_bytes=0,
            line_count=0,
            mtime_ms=0,
            ts_ms=0,
        )


def test_read_record_rejects_negative_size():
    with pytest.raises(ValidationError):
        ReadRecord(
            path="x",
            sha256="0" * 64,
            size_bytes=-1,
            line_count=0,
            mtime_ms=0,
            ts_ms=0,
        )


def test_edit_record_round_trip():
    rec = EditRecord(
        path="src/foo.py",
        op="replace",
        sha256_before="a" * 64,
        sha256_after="b" * 64,
        snapshot_ref="a" * 64,
        ts_ms=1_700_000_000_000,
    )
    assert EditRecord.model_validate(rec.model_dump()) == rec


def test_edit_record_op_enum():
    with pytest.raises(ValidationError):
        EditRecord(
            path="x",
            op="not-a-real-op",
            sha256_before="a" * 64,
            sha256_after="b" * 64,
            snapshot_ref="a" * 64,
            ts_ms=0,
        )


def test_snapshot_ref_validates_hex_length():
    SnapshotRef(sha256="d" * 64)
    with pytest.raises(ValidationError):
        SnapshotRef(sha256="d" * 32)


def test_workspace_metadata_round_trip():
    meta = WorkspaceMetadata(
        workspace_root="/abs/path",
        schema_version=SCHEMA_VERSION,
        created_at_ms=1_700_000_000_000,
    )
    assert WorkspaceMetadata.model_validate(meta.model_dump()) == meta
