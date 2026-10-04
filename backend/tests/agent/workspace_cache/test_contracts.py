"""Tests for workspace-cache record models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk.workspace_cache.contracts import (
    EditRecord,
    ReadRecord,
    SnapshotRef,
)

SCHEMA_VERSION = 1


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
