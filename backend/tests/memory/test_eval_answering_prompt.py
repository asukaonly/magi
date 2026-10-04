"""Regression coverage for eval answer synthesis prompt rules."""

from __future__ import annotations

import pytest

from magi.memory.eval_support.answer_synthesis import _build_eval_answer_system_prompt


def test_eval_system_prompt_declares_speaker_attribution_policy():
    prompt = _build_eval_answer_system_prompt()
    assert "DIALOGUE OWNERSHIP:" in prompt
    assert (
        "first-person dialogue evidence from another speaker belongs to that other speaker"
        in prompt
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,temporal", [("Which event happened first?", True), ("What do I like?", False)]
)
async def test_synthesis_composes_temporal_evidence_without_claiming_answer_quality(
    monkeypatch, question, temporal
):
    from types import SimpleNamespace
    from magi.memory.eval_support import answer_synthesis
    from magi.memory.answering import build_answer_prompt_payload

    relative_instruction = "RELATIVE-TIME-POLICY-CANARY\n"
    monkeypatch.setattr(
        answer_synthesis, "_relative_time_instruction", lambda: relative_instruction
    )
    user_text = "I attended a workshop last Saturday."
    assistant_text = "Assistant background context canary."
    bundles = [
        {
            "session_id": "s1",
            "events": [
                {
                    "turn_id": "t1",
                    "author_type": "user",
                    "content": user_text,
                    "timestamp": 1680307200.0,
                },
                {
                    "turn_id": "t2",
                    "author_type": "assistant",
                    "content": assistant_text,
                    "timestamp": 1680393600.0,
                },
            ],
        }
    ]
    timeline = [
        {
            "timestamp": 1680307200.0,
            "session_id": "s1",
            "turn_id": "t1",
            "author_type": "user",
            "summary": "Workshop timeline canary.",
        }
    ]
    timeline[0]["event_date"] = "2023-03-25"
    timeline.append(
        {
            "timestamp": 1680480000.0,
            "session_id": "s2",
            "turn_id": "t3",
            "author_type": "user",
            "summary": "Later webinar timeline canary.",
            "event_date": "2023-04-01",
        }
    )
    hits = [{"turn_id": "t1", "session_id": "s1", "content": user_text}]
    payload = build_answer_prompt_payload(
        question=question, hits=hits, evidence_bundles=bundles, timeline_summary=timeline
    )
    assert payload.prioritize_timeline is temporal
    assert payload.bundle_text.count(user_text) == 1
    assert user_text not in payload.evidence_text
    assert assistant_text in payload.bundle_text
    assert payload.timeline_text == (
        "[1] 2023-04-01 session=s1 role=user turn=t1 (event date: 2023-03-25)\nWorkshop timeline canary.\n\n"
        "[2] 2023-04-03 session=s2 role=user turn=t3 (event date: 2023-04-01)\nLater webinar timeline canary."
    )
    assert (
        payload.bundle_text
        == f"[bundle 1] session=s1\n- role=user turn=t1: {user_text}\n- role=assistant turn=t2: {assistant_text}"
    )
    assert ("TIMELINE PRIORITY" in payload.timeline_instruction) is temporal
    captured = []

    class Adapter:
        async def chat(self, messages, **kwargs):
            captured.extend(messages)
            return "stub-response"

    _, trace = await answer_synthesis.synthesize_eval_answer(
        question=question,
        hits=hits,
        evidence_bundles=bundles,
        timeline_summary=timeline,
        query_timestamp=1680722700.0,
        show_prompt=True,
        llm_pool=SimpleNamespace(get=lambda _: Adapter()),
    )
    prompt = captured[-1]["content"]
    assert prompt.startswith(relative_instruction)
    assert "Question date: 2023-04-05" in prompt
    assert user_text in prompt and assistant_text in prompt
    assert (prompt.index("Workshop timeline canary.") > prompt.index(assistant_text)) is temporal
    assert prompt.index("Workshop timeline canary.") < prompt.index(
        "Later webinar timeline canary."
    )
    assert prompt.count(user_text) == prompt.count(assistant_text) == 1
    assert captured[0]["content"] == _build_eval_answer_system_prompt()
    assert trace["prompt"] == prompt
    assert trace["evidence_timeline_count"] == 2
