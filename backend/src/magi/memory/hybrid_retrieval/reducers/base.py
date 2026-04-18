"""Reducer base protocol — transforms evidence bundles into summary output."""

from __future__ import annotations

from typing import Any, Protocol

from ..evidence.base import EvidenceBundle


class Reducer(Protocol):
    """Protocol for answer reducers."""

    def reduce(self, evidence: EvidenceBundle) -> dict[str, Any]: ...
