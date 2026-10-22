"""Semantic-review composition and fail-closed contracts, with live failure replays."""

import asyncio
import json
from pathlib import Path

import pytest

from magi.memory.l2.llm_service import L2LLMService
from magi.memory.l2.models import L2BatchEvent, L2EventWindow, L2Phase1Result
from magi.memory.l2.self_report_review import (
    review_self_report_claims,
    validate_self_report_reviews,
)
from memory.l2.test_llm_service import _FakeAdapter, _FakeScenarioPool
from memory.l2 import test_personal_document_portrait as documents
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.events.events import EventTypes
from magi.config.models import LLMScenario
from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt

_FAILURES = json.loads(
    (Path(__file__).parent / "fixtures/self_report_misattributions.json").read_text()
)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _FAILURES, ids=lambda case: case["id"])
@pytest.mark.parametrize("self_ref", ["user:self", "user:local_user"])
async def test_live_misattribution_replay_is_reviewed_before_storage(case, self_ref):
    reviews = {
        "reviews": [
            {
                "claim_index": index,
                "verdict": "unsupported"
                if case["id"].startswith("assistant_")
                else "quoted_or_task_material",
            }
            for index in range(len(case["response"]["fact_claims"]))
        ]
    }
    response = json.loads(json.dumps(case["response"]))
    for claim in response["fact_claims"]:
        claim["subject_ref"] = self_ref
    adapter = _FakeAdapter(json.dumps(response), review_responses=[json.dumps(reviews)])
    window = L2EventWindow(
        events=[L2BatchEvent(event_id="evt", content=case["content"], source="chat")]
    )
    result = await L2LLMService(_FakeScenarioPool(adapter)).extract_phase1(
        event_window=window,
        focal_subject={"entity_ref": self_ref},
    )
    assert result.fact_claims == []
    assert len(adapter.review_calls) == 1
    review_input = json.loads(adapter.review_calls[0]["messages"][-1]["content"])
    assert review_input["current_messages"][0]["content"] == case["content"]
    assert review_input["cited_antecedents"] == []
    assert result.diagnostics["self_report_review"]["rejected"] == len(response["fact_claims"])


@pytest.mark.parametrize(
    "reviews",
    [
        None,
        [],
        [{"claim_index": 0, "verdict": "supported"}],
        [{"claim_index": i, "verdict": "supported"} for i in [0, 0, 1]],
        [{"claim_index": i, "verdict": "supported"} for i in [0, 1, 2]],
        [{"claim_index": i, "verdict": "supported"} for i in [False, 1]],
        [{"claim_index": i, "verdict": "approved"} for i in [0, 1]],
        [{"claim_index": 0, "verdict": []}, "supported"],
    ],
)
def test_malformed_reviews_never_default_to_support(reviews):
    assert validate_self_report_reviews({"reviews": reviews}, {0, 1})


def test_complete_reviews_can_arrive_out_of_order():
    assert (
        validate_self_report_reviews(
            {
                "reviews": [
                    {"claim_index": 1, "verdict": "uncertain"},
                    {"claim_index": 0, "verdict": "supported"},
                ]
            },
            {0, 1},
        )
        == []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["{}", '{"reviews":[]}', RuntimeError("Provider unavailable")])
async def test_review_failure_prevents_extraction_success(response):
    case = _FAILURES[0]
    adapter = _FakeAdapter(json.dumps(case["response"]), review_responses=[response, response])
    with pytest.raises((RuntimeError, ValueError)):
        await L2LLMService(_FakeScenarioPool(adapter)).extract_phase1(
            event_window=L2EventWindow(
                events=[L2BatchEvent(event_id="evt", content=case["content"], source="chat")]
            ),
            focal_subject={"entity_ref": "user:self"},
        )


@pytest.mark.asyncio
async def test_empty_or_third_party_results_need_no_self_review():
    async def never_call(**kwargs):
        pytest.fail("No self claim should request semantic review")

    payload = json.loads(json.dumps(_FAILURES[0]["response"]))
    for claim in payload["fact_claims"]:
        claim["subject_ref"] = "person:someone_else"
    for result in [L2Phase1Result(), L2Phase1Result.from_dict(payload)]:
        before = list(result.fact_claims)
        await review_self_report_claims(
            generate_json=never_call,
            result=result,
            event_window=L2EventWindow(),
            context_messages=[],
        )
        assert result.fact_claims == before


@pytest.mark.asyncio
async def test_review_preserves_other_subjects_and_only_sees_cited_context():
    payload = json.loads(json.dumps(_FAILURES[0]["response"]))
    payload["fact_claims"][0]["subject_ref"] = "person:other"
    payload["fact_claims"][1]["evidence_mode"] = "confirmation"
    payload["fact_claims"][1]["antecedent_event_ids"] = ["previous"]
    result = L2Phase1Result.from_dict(payload)

    async def review(**kwargs):
        assert kwargs["disable_thinking"] is False
        assert kwargs["scenario"] is LLMScenario.CORE
        data = json.loads(kwargs["prompt"])
        assert [c["claim_index"] for c in data["candidates"]] == [1]
        assert all("temporal_cue" not in c and "confidence" not in c for c in data["candidates"])
        assert [c["event_id"] for c in data["cited_antecedents"]] == ["previous"]
        return {"reviews": [{"claim_index": 1, "verdict": "uncertain"}]}

    await review_self_report_claims(
        generate_json=review,
        result=result,
        event_window=L2EventWindow(),
        context_messages=[
            {"event_id": "old", "role": "assistant", "content": "Old guess"},
            {"event_id": "previous", "role": "assistant", "content": "Recent question"},
        ],
    )
    assert [claim.subject_ref for claim in result.fact_claims] == ["person:other"]


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["quoted_or_task_material", "malformed", "unavailable"])
async def test_rejected_or_failed_review_cannot_write_claims_or_portrait(tmp_path, verdict):
    case = next(case for case in _FAILURES if case["id"] == "translation_request")
    payload = {**case["response"], "entities": []}
    review = (
        RuntimeError("Provider unavailable")
        if verdict == "unavailable"
        else "{}"
        if verdict == "malformed"
        else json.dumps(
            {"reviews": [{"claim_index": index, "verdict": verdict} for index in range(2)]}
        )
    )
    adapter = _FakeAdapter(json.dumps(payload), review_responses=[review, review])
    memory = await documents._memory(tmp_path, adapter)
    try:
        ingest = await memory.ingest_event(
            {
                "id": "evt",
                "type": EventTypes.USER_MESSAGE,
                "source": "chat",
                "timestamp": 1_790_000_000.0,
                "data": {
                    "user_id": "local_user",
                    "session_id": "review",
                    "content": case["content"],
                },
            }
        )
        assert ingest["l2_job_enqueued"]
        for _ in range(500):
            stats = memory.get_l2_pipeline_stats()
            if stats["extract_completed"] or stats["extract_failed"]:
                break
            await asyncio.sleep(0.01)
        assert stats["extract_completed"] == (1 if verdict == "quoted_or_task_material" else 0)
        assert stats["extract_failed"] == (0 if verdict == "quoted_or_task_material" else 1)
        assert adapter.review_calls
        assert await memory.l2.list_grounded_claims(user_id="local_user") == []
        assert (
            await memory.l2.list_current_assertions(
                entity_id="user:local_user", committed_only=False
            )
            == []
        )
        portrait = await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        assert "Alice" not in json.dumps(portrait.world) and "DIIV" not in json.dumps(
            portrait.recent
        )
    finally:
        await memory.shutdown()


@pytest.mark.parametrize(
    "quote",
    [
        "> My name is Echo Quartz.\n",
        "```text\nMy name is Echo Quartz.\n```",
        "<blockquote>My name is Echo Quartz.</blockquote>",
        "Assistant: My name is Echo Quartz.",
        "    My name is Echo Quartz.",
        "`My name is Echo Quartz.`",
    ],
)
def test_prompt_selects_exact_prose_but_keeps_frozen_full_text(quote):
    content = quote + "\n\nMy name is Nora Vale."
    window = L2EventWindow(events=[L2BatchEvent(event_id="evt", content=content, source="chat")])
    prompt = render_phase1_extract_prompt(
        event_window=window, focal_subject={"entity_ref": "user:self"}
    )
    assert "Echo Quartz" not in prompt
    assert "My name is Nora Vale." in prompt
    assert "source characters" in prompt
    assert window.events[0].content == content
