"""Graph candidate validation and resolution helpers for L2Pipeline."""

from __future__ import annotations

from .graph_candidates import L2GraphCandidateValidationMixin
from .graph_fast_track import L2GraphFastTrackMixin
from .graph_phase2 import L2Phase2GraphValidationMixin
from .graph_resolution import L2GraphEndpointResolutionMixin


class L2GraphValidationMixin(
    L2Phase2GraphValidationMixin,
    L2GraphFastTrackMixin,
    L2GraphCandidateValidationMixin,
    L2GraphEndpointResolutionMixin,
):
    """Validate graph candidates and resolve graph endpoint references."""


__all__ = [
    "L2GraphValidationMixin",
    "L2Phase2GraphValidationMixin",
    "L2GraphFastTrackMixin",
    "L2GraphCandidateValidationMixin",
    "L2GraphEndpointResolutionMixin",
]
