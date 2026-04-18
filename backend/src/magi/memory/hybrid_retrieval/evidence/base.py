"""Evidence assembler base protocol and bundle types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import RetrievalPayload, RetrievalQuery


# ---------------------------------------------------------------------------
# Evidence bundle types (one per evidence_shape)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FactCardEvidence:
    """Evidence shape for exact_fact mode."""

    facts: list[dict[str, Any]] = field(default_factory=list)
    entity_context: dict[str, Any] | None = None


@dataclass(slots=True)
class StateCardEvidence:
    """Evidence shape for current_state mode."""

    current: dict[str, Any] | None = None
    supporting_events: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class EpisodeBundleEvidence:
    """Evidence shape for episode_recall mode."""

    episodes: list[dict[str, Any]] = field(default_factory=list)
    key_events: list[dict[str, Any]] = field(default_factory=list)
    state_overlays: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class GroupedListEvidence:
    """Evidence shape for cross_session mode."""

    groups: list[dict[str, Any]] = field(default_factory=list)
    dedup_hints: list[str] = field(default_factory=list)
    total_matches: int = 0


@dataclass(slots=True)
class ComparisonFrameEvidence:
    """Evidence shape for temporal_compare mode."""

    anchor_a: dict[str, Any] = field(default_factory=dict)
    anchor_b: dict[str, Any] = field(default_factory=dict)
    delta: dict[str, Any] = field(default_factory=dict)
    state_trajectory: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PassthroughEvidence:
    """Passthrough shape — wraps the raw payload for summary/strategy modes."""

    payload: dict[str, Any] = field(default_factory=dict)


EvidenceBundle = (
    FactCardEvidence
    | StateCardEvidence
    | EpisodeBundleEvidence
    | GroupedListEvidence
    | ComparisonFrameEvidence
    | PassthroughEvidence
)


# ---------------------------------------------------------------------------
# Assembler protocol
# ---------------------------------------------------------------------------


class EvidenceAssembler(Protocol):
    """Protocol for evidence assemblers."""

    def assemble(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> EvidenceBundle: ...
