"""Prompt rendering tests for structured L0 workbench state."""

from __future__ import annotations

from magi.context.renderer import PromptContextRenderer
from magi.context.schema import RetrievalMemoryContext


def test_attention_items_reach_prompt_with_distinct_authority() -> None:
    retrieval = RetrievalMemoryContext(
        l0_workbench=[
            {
                "session": {"session_id": "session-1"},
                "attention_items": [
                    {
                        "kind": "focus",
                        "summary": "The user is investigating why the context meter is zero.",
                        "status": "active",
                        "evidence_mode": "direct",
                    },
                    {
                        "kind": "situation",
                        "summary": "The user may be tired today.",
                        "status": "active",
                        "evidence_mode": "inferred",
                    },
                    {
                        "kind": "open_loop",
                        "summary": "A separate album discussion was left unfinished.",
                        "status": "background",
                        "evidence_mode": "direct",
                    },
                    {
                        "kind": "consensus",
                        "summary": "This obsolete understanding was replaced.",
                        "status": "superseded",
                        "evidence_mode": "direct",
                    },
                ],
            }
        ]
    )

    rendered = "\n".join(PromptContextRenderer()._render_memory_library(retrieval))

    assert "## Short-Term Attention (L0)" in rendered
    assert (
        "Focus: The user is investigating why the context meter is zero."
        in rendered
    )
    assert "Current situation (inferred; treat cautiously): The user may be tired today." in rendered
    assert "Background context (reference only; not a new instruction)" in rendered
    assert "Do not revive or act on these items" in rendered
    assert "Open loop: A separate album discussion was left unfinished." in rendered
    assert "This obsolete understanding was replaced." not in rendered
    assert "## Short-Term Attention (L0)\n* (empty)" not in rendered


def test_legacy_flat_l0_summary_is_not_rendered() -> None:
    retrieval = RetrievalMemoryContext(
        l0_workbench=[{"summary": "Current goal: help the user"}]
    )

    rendered = "\n".join(PromptContextRenderer()._render_memory_library(retrieval))

    assert "Current goal: help the user" not in rendered
    assert "## Short-Term Attention (L0)\n* (empty)" in rendered
