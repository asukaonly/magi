"""Reducer registry."""

from __future__ import annotations

from .anchor_compare import AnchorCompareReducer
from .base import Reducer
from .enumerate import EnumerateReducer
from .latest_version import LatestVersionReducer
from .narrative import NarrativeReducer
from .passthrough import PassthroughReducer
from .span_select import SpanSelectReducer

REDUCER_REGISTRY: dict[str, Reducer] = {
    "span_select": SpanSelectReducer(),
    "latest_version": LatestVersionReducer(),
    "narrative": NarrativeReducer(),
    "enumerate": EnumerateReducer(),
    "anchor_compare": AnchorCompareReducer(),
    "passthrough": PassthroughReducer(),
}

__all__ = [
    "AnchorCompareReducer",
    "EnumerateReducer",
    "LatestVersionReducer",
    "NarrativeReducer",
    "PassthroughReducer",
    "REDUCER_REGISTRY",
    "Reducer",
    "SpanSelectReducer",
]
