"""Decode relational event records before crossing the repository boundary."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.event_mapping import (
    decode_event_metadata as decode_event_metadata,
    event_record_from_mapping as event_record_from_mapping,
)
