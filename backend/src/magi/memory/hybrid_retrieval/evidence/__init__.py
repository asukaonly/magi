"""Evidence assembler registry."""

from __future__ import annotations

from .base import (
    ComparisonFrameEvidence,
    EpisodeBundleEvidence,
    EvidenceAssembler,
    EvidenceBundle,
    FactCardEvidence,
    GroupedListEvidence,
    PassthroughEvidence,
    StateCardEvidence,
)
from .comparison_frame import ComparisonFrameAssembler
from .episode_bundle import EpisodeBundleAssembler
from .fact_card import FactCardAssembler
from .grouped_list import GroupedListAssembler
from .passthrough import PassthroughAssembler
from .state_card import StateCardAssembler

ASSEMBLER_REGISTRY: dict[str, EvidenceAssembler] = {
    "fact_card": FactCardAssembler(),
    "state_card": StateCardAssembler(),
    "episode_bundle": EpisodeBundleAssembler(),
    "grouped_list": GroupedListAssembler(),
    "comparison_frame": ComparisonFrameAssembler(),
    "passthrough": PassthroughAssembler(),
}

__all__ = [
    "ASSEMBLER_REGISTRY",
    "ComparisonFrameAssembler",
    "ComparisonFrameEvidence",
    "EpisodeBundleAssembler",
    "EpisodeBundleEvidence",
    "EvidenceAssembler",
    "EvidenceBundle",
    "FactCardAssembler",
    "FactCardEvidence",
    "GroupedListAssembler",
    "GroupedListEvidence",
    "PassthroughAssembler",
    "PassthroughEvidence",
    "StateCardAssembler",
    "StateCardEvidence",
]
