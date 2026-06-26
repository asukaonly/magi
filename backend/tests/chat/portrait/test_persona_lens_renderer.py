from unittest.mock import AsyncMock

import pytest

from magi.chat.portrait.contracts import ChatPortraitObservation, RawMemorySnippet
from magi.chat.portrait.persona_lens_renderer import PersonaLensRenderer


_PERSONA_CONFIG = {
    "name": "七号",
    "identity_core": {
        "identity_statement": "陪在 asuka 身边的猫一样的搭档",
        "values_loved": ["真诚"],
        "values_rejected": ["假大空"],
        "attention_biases": [],
    },
    "idiolect": {
        "sentence_style": "短句，偶尔毒舌但有温度",
        "vocab_available": ["子涵", "你"],
        "vocab_avoided": ["用户", "亲爱的"],
        "structural_quirks": [],
    },
}


_SNIPPETS = [
    RawMemorySnippet(id="mem_a", kind="reflection", layer="L3",
                     statement="对失败者有同理心", confidence=0.8),
    RawMemorySnippet(id="mem_b", kind="assertion", layer="L2",
                     statement="不喜欢直播带货", confidence=0.9),
]


@pytest.mark.asyncio
async def test_render_returns_observations_from_llm_json():
    """LLM uses M-tokens (M1, M2) — renderer maps them back to real ids."""
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(return_value={
        "observations": [
            {
                "kind": "reflection",
                "text": "你又开始想那些没做成的事了？",
                "basis_count": 1,
                "basis_summary": "1 条反思",
                "basis_refs": ["M1"],
            },
        ],
    })
    renderer = PersonaLensRenderer(bridge_factory=lambda: mock_bridge)
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=_SNIPPETS,
        recent_message_excerpt="你怎么看罗永浩",
        topic="罗永浩",
    )
    assert len(observations) == 1
    assert isinstance(observations[0], ChatPortraitObservation)
    assert observations[0].kind == "reflection"
    assert "你" in observations[0].text
    # M1 was mapped back to mem_a.
    assert observations[0].basis_refs == ["mem_a"]


@pytest.mark.asyncio
async def test_render_strips_m_tokens_from_text_if_llm_leaks_them():
    """Defense in depth: even when the LLM disobeys and dumps the token
    into the visible text, it is stripped before reaching the UI."""
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(return_value={
        "observations": [
            {
                "kind": "assertion",
                "text": "你不喜欢直播 (M2 记录过)",
                "basis_count": 1,
                "basis_summary": "1 条事实",
                "basis_refs": ["M2"],
            },
        ],
    })
    renderer = PersonaLensRenderer(bridge_factory=lambda: mock_bridge)
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=_SNIPPETS,
        recent_message_excerpt="x",
        topic="t",
    )
    assert len(observations) == 1
    assert "M2" not in observations[0].text
    assert observations[0].basis_refs == ["mem_b"]


@pytest.mark.asyncio
async def test_render_no_snippets_returns_empty():
    renderer = PersonaLensRenderer(bridge_factory=lambda: AsyncMock())
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=[],
        recent_message_excerpt="hi",
        topic="",
    )
    assert observations == []


@pytest.mark.asyncio
async def test_render_llm_failure_returns_empty():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(side_effect=RuntimeError("boom"))
    renderer = PersonaLensRenderer(bridge_factory=lambda: mock_bridge)
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=_SNIPPETS,
        recent_message_excerpt="hi",
        topic="t",
    )
    assert observations == []


@pytest.mark.asyncio
async def test_render_drops_invalid_kind():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(return_value={
        "observations": [
            {"kind": "garbage", "text": "x", "basis_count": 0,
             "basis_summary": "", "basis_refs": []},
            {"kind": "assertion", "text": "你不喜欢直播", "basis_count": 1,
             "basis_summary": "1 条事实", "basis_refs": ["M2"]},
        ],
    })
    renderer = PersonaLensRenderer(bridge_factory=lambda: mock_bridge)
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=_SNIPPETS,
        recent_message_excerpt="hi",
        topic="t",
    )
    assert len(observations) == 1
    assert observations[0].kind == "assertion"
