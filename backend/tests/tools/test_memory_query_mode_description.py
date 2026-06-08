"""Tests that the query_mode parameter description teaches answer-shape selection.

P2-T3: rewrite the query_mode tool-parameter description so the calling LLM
picks the mode by answer-shape rather than being told it's "rare".
"""

from __future__ import annotations


def test_query_mode_description_guides_enumerate_selection():
    """query_mode description must teach answer-shape, not discourage usage."""
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

    tool = MemoryQueryTool()
    schema = tool.get_schema()

    qm = next(p for p in schema.parameters if p.name == "query_mode")
    desc = qm.description.lower()

    # Must NOT tell the LLM the parameter is rarely needed.
    assert "rare" not in desc, "description should not call query_mode rare"

    # Must mention cross_session so the LLM knows when to pick it.
    assert "cross_session" in desc, "description should reference cross_session mode"

    # Must teach enumerate / list / multiple paradigm for cross_session.
    assert (
        "enumerate" in desc or "list" in desc or "multiple" in desc
    ), "description should teach the enumerate/list/multiple answer shape"
