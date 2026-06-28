"""Structure tests for the post-retrieval grounding filter.

The public GroundingFilter entry point should stay as orchestration. Rule
screening, prompt construction/parsing, and trace compatibility live in focused
helpers so changing one filtering concern does not require editing the whole
pipeline.
"""

from __future__ import annotations

import importlib.util
import inspect

import magi.memory.hybrid_retrieval.grounding_filter as grounding_filter


def test_grounding_filter_uses_dedicated_helper_modules() -> None:
    expected_modules = [
        "magi.memory.hybrid_retrieval.grounding_filter_owner",
        "magi.memory.hybrid_retrieval.grounding_filter_prompt",
        "magi.memory.hybrid_retrieval.grounding_filter_trace",
    ]
    missing = [
        module_name
        for module_name in expected_modules
        if importlib.util.find_spec(module_name) is None
    ]
    assert missing == []


def test_grounding_filter_module_stays_orchestrator_only() -> None:
    source = inspect.getsource(grounding_filter)
    moved_helpers = [
        "def _apply_named_person_owner_prefilter",
        "def _build_unified_prompt_payload",
        "def _parse_keep_response",
        "def _degraded_trace",
        "def _compat_l2_trace",
        "_SYSTEM_PROMPT =",
    ]
    assert [helper for helper in moved_helpers if helper in source] == []


def test_grounding_filter_apply_stays_readable() -> None:
    line_count = len(inspect.getsource(grounding_filter.GroundingFilter.apply).splitlines())
    assert line_count <= 220
