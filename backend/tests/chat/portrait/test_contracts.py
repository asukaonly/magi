from magi.chat.portrait.contracts import (
    ChatPortraitObservation,
    ChatPortraitPayload,
    TopicResult,
)


def test_chat_portrait_observation_to_dict_roundtrip():
    obs = ChatPortraitObservation(
        kind="reflection",
        text="你最近老聊'落寞英雄'",
        basis_count=5,
        basis_summary="5 条反思 · 上周以来",
        basis_refs=["mem_a", "mem_b"],
    )
    data = obs.to_dict()
    assert data["kind"] == "reflection"
    assert data["text"].startswith("你最近")
    assert data["basis_count"] == 5
    assert data["basis_refs"] == ["mem_a", "mem_b"]


def test_chat_portrait_payload_cold_start_shape():
    payload = ChatPortraitPayload(
        session_id="s1",
        persona_id="p1",
        topic="",
        generated_at=1700000000,
        observations=[],
        is_cold_start=True,
        cold_start_line="七号还在认识你",
    )
    data = payload.to_dict()
    assert data["is_cold_start"] is True
    assert data["cold_start_line"] == "七号还在认识你"
    assert data["observations"] == []


def test_topic_result_default_empty():
    result = TopicResult(topic="", entities=[])
    assert result.is_empty() is True
    assert TopicResult(topic="罗永浩", entities=[]).is_empty() is False
