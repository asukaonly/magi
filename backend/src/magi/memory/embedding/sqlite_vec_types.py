"""Shared sqlite-vec index contracts and serialization helpers."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

import sqlite_vec


def _deserialize_float32_blob(raw: Any) -> list[float]:
    """Decode a sqlite-vec float32 blob across package versions."""
    deserialize = getattr(sqlite_vec, "deserialize_float32", None)
    if callable(deserialize):
        return list(deserialize(raw))

    blob = bytes(raw)
    if len(blob) % 4 != 0:
        raise ValueError("sqlite-vec embedding blob length must be a multiple of 4 bytes")
    return [value[0] for value in struct.iter_unpack("<f", blob)]


@dataclass(slots=True)
class VectorSearchHit:
    """One nearest-neighbor match from a sqlite-vec index."""

    entity_id: str
    distance: float


__all__ = ["VectorSearchHit", "_deserialize_float32_blob"]
