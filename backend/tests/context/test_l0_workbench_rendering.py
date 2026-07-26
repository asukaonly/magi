"""Prompt rendering tests for structured L0 workbench state."""

from __future__ import annotations

from magi.context.renderer import PromptContextRenderer
from magi.context.schema import RetrievalMemoryContext


def test_structured_l0_workbench_content_reaches_prompt() -> None:
    retrieval = RetrievalMemoryContext(
        l0_workbench=[
            {
                "session": {"session_id": "session-1"},
                "goals": [
                    {
                        "description": "Explain why the context meter is zero",
                        "status": "in_progress",
                    }
                ],
                "active_entities": [
                    {
                        "entity_id": "repo:magi",
                        "entity_type": "repository",
                        "snapshot": {"name": "Magi"},
                    }
                ],
                "temporary_tactics": [
                    {
                        "tactic_type": "verify_first",
                        "tactic_payload": {"mode": "run tests"},
                    }
                ],
            }
        ]
    )

    rendered = "\n".join(PromptContextRenderer()._render_memory_library(retrieval))

    assert "Current goal: Explain why the context meter is zero" in rendered
    assert "Active entity: Magi (repository)" in rendered
    assert "Temporary tactic: verify_first: mode=run tests" in rendered
    assert "## Working Memory (L0)\n* (empty)" not in rendered


def test_flat_l0_summary_remains_renderable() -> None:
    retrieval = RetrievalMemoryContext(
        l0_workbench=[{"summary": "Current goal: help the user"}]
    )

    rendered = "\n".join(PromptContextRenderer()._render_memory_library(retrieval))

    assert "Current goal: help the user" in rendered
