"""Graph candidate validation and resolution helpers for L2Pipeline."""

from __future__ import annotations

from .graph_candidates import L2GraphCandidateValidationMixin
from .graph_resolution import L2GraphEndpointResolutionMixin
from .phase1_graph import L2Phase1GraphProjectionMixin


class L2GraphValidationMixin(
    L2Phase1GraphProjectionMixin,
    L2GraphCandidateValidationMixin,
    L2GraphEndpointResolutionMixin,
):
    """Validate graph candidates and resolve graph endpoint references."""


__all__ = [
    "L2GraphValidationMixin",
    "L2GraphCandidateValidationMixin",
    "L2GraphEndpointResolutionMixin",
    "L2Phase1GraphProjectionMixin",
]
