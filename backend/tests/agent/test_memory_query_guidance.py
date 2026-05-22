"""Verify the chat LLM's MEMORY_QUERY_GUIDANCE_BLOCK contains the
do-not-paraphrase instruction so the LLM doesn't rewrite the user's
question before calling memory_query (Phase 4)."""


def test_guidance_block_forbids_paraphrasing():
    from magi.agent.task_agents.chat.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    block = MEMORY_QUERY_GUIDANCE_BLOCK
    # Must explicitly tell the LLM to pass the original query verbatim
    assert "verbatim" in block.lower() or "do not paraphrase" in block.lower(), (
        f"MEMORY_QUERY_GUIDANCE_BLOCK must explicitly forbid paraphrasing; got:\n{block}"
    )
    # Should mention that query_mode is automatic
    assert "auto" in block.lower() or "automatic" in block.lower() or "optional" in block.lower()


def test_guidance_block_does_not_instruct_to_pick_query_mode():
    """Phase 4: the block should no longer tell the LLM to select query_mode
    from an enum. Either omit the instruction or mark it optional."""
    from magi.agent.task_agents.chat.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    block = MEMORY_QUERY_GUIDANCE_BLOCK.lower()
    # No instruction to "choose" or "pick" a query_mode
    assert "choose query_mode" not in block
    assert "pick query_mode" not in block
    assert "select query_mode" not in block
