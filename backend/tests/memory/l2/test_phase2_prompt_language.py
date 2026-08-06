"""Phase 2 system prompt builds with explicit user-language directive."""

from __future__ import annotations

from magi.memory.l2.pipeline.prompts import (
    PHASE2_INTEGRATE_SYSTEM_PROMPT,
    build_phase2_integrate_system_prompt,
)
from magi.memory.l2.models import L2Phase2Result


def test_baseline_when_language_is_none():
    assert build_phase2_integrate_system_prompt(None) == PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert build_phase2_integrate_system_prompt("") == PHASE2_INTEGRATE_SYSTEM_PROMPT


def test_appends_language_directive():
    prompt = build_phase2_integrate_system_prompt("zh-CN")
    assert prompt.startswith(PHASE2_INTEGRATE_SYSTEM_PROMPT)
    assert "## Language directive" in prompt
    assert "`zh-CN`" in prompt
    assert "Write every summary in that language" in prompt


def test_directive_is_appended_not_inlined():
    """The baseline stays first; directive comes after."""
    prompt = build_phase2_integrate_system_prompt("ja")
    baseline_end = prompt.index(PHASE2_INTEGRATE_SYSTEM_PROMPT) + len(PHASE2_INTEGRATE_SYSTEM_PROMPT)
    assert "## Language directive" in prompt[baseline_end:]


def test_phase2_contract_does_not_request_unused_refinements():
    assert '"refinements"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT


def test_phase2_result_ignores_unused_refinements_payload():
    result = L2Phase2Result.from_dict(
        {
            "refinements": [
                {
                    "existing_triple_id": "triple-1",
                    "refined_by_object": "topic:rainy-weather",
                    "explanation": "unused",
                }
            ],
            "summaries": [],
        }
    )

    assert "refinements" not in result.to_dict()
