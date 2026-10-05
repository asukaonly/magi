"""Tests for workspace-cache record models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk.workspace_cache.contracts import (
    SnapshotRef,
)


def test_snapshot_ref_validates_hex_length():
    SnapshotRef(sha256="d" * 64)
    with pytest.raises(ValidationError):
        SnapshotRef(sha256="d" * 32)
