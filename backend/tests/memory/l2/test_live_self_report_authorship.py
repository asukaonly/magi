"""Opt-in, synthetic-only live-model authorship evaluation; never use personal history.

Set MAGI_LIVE_LLM_CONFIG to an explicit runtime llm.yaml and optionally set
MAGI_LIVE_REPORT_DIR to keep raw synthetic responses. Normal CI makes no paid calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from magi.config import AppConfig
from magi.config.models import LLMScenario
from magi.events.events import EventTypes
from magi.llm.factory import create_scenario_llm_pool
from magi.memory.l2.extraction_profiles import (
    build_extraction_profile_registry,
    resolve_extraction_profile,
)
from magi.memory.l2.llm_service import L2LLMService
from magi.memory.l2.models import L2BatchEvent, L2EventWindow, L2Phase1Result
from magi.memory.l2.pipeline.claim_grounding import ground_phase1_fact_claims
from magi.memory.l2.self_report_review import review_self_report_claims
from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT
from magi.memory.l2.self_report_review import SELF_REPORT_REVIEW_PROMPT
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from memory.l2.test_conversation_portrait import _profiles
from memory.l2 import test_personal_document_portrait as documents

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("MAGI_LIVE_LLM_CONFIG"),
        reason="Live model evaluation requires an explicit config path",
    ),
]
_FIXTURES = Path(__file__).parent / "fixtures"
_CASES = json.loads((_FIXTURES / "self_report_authorship.json").read_text())
_FAILURES = json.loads((_FIXTURES / "self_report_misattributions.json").read_text())
_SOURCES = ["chat", "history_import", "codex_agent_history", "claude_code_agent_history"]


class _RecordingService(L2LLMService):
    def __init__(self, pool):
        super().__init__(pool)
        self.responses = []

    async def _call_json_with_retries(self, **kwargs):
        response = await super()._call_json_with_retries(**kwargs)
        selected = self._scenario_llm_pool.resolve(kwargs["call"].scenario).context
        self.responses.append(
            {
                "request_kind": kwargs["call"].request_kind,
                "model": selected.model_id,
                "provider": selected.provider_id,
                "input_sha256": hashlib.sha256(
                    (kwargs["call"].system_prompt + kwargs["call"].prompt).encode()
                ).hexdigest(),
                "content": response.content,
                "usage": asdict(response.usage) if response.usage else None,
            }
        )
        return response


@pytest.fixture
def live_pool():
    # pytest's hermetic runtime fixture isolates all implicit config and databases.
    # This file is read only for provider credentials and model selection.
    config = AppConfig(llm=yaml.safe_load(Path(os.environ["MAGI_LIVE_LLM_CONFIG"]).read_text()))
    return create_scenario_llm_pool(config)


def _report(name, pool, service, **result):
    directory = os.environ.get("MAGI_LIVE_REPORT_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        selected = pool.resolve(LLMScenario.AUXILIARY).context
        (target / f"{name}.json").write_text(
            json.dumps(
                {
                "extraction_provider": selected.provider_id,
                "extraction_model": selected.model_id,
                "review_model": pool.resolve(LLMScenario.CORE).context.model_id,
                    "corpus_sha256": hashlib.sha256(
                        (_FIXTURES / "self_report_authorship.json").read_bytes()
                    ).hexdigest(),
                    "prompts_sha256": hashlib.sha256(
                        (PHASE1_EXTRACT_SYSTEM_PROMPT + SELF_REPORT_REVIEW_PROMPT).encode()
                    ).hexdigest(),
                    "responses": service.responses,
                    **result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def _claim_key(claim):
    predicate, polarity = claim.predicate, claim.polarity
    if predicate == "DISLIKES" and polarity == "positive":
        predicate, polarity = "LIKES", "negative"
    return predicate, claim.object_ref, polarity


@pytest.mark.parametrize("source", _SOURCES)
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
async def test_live_authorship(case, source, live_pool):
    content = case["content"]
    if source.endswith("agent_history"):
        content = "## User turn 1\n\n" + content
    event = L2BatchEvent(
        event_id="evt",
        content=content,
        source=source,
        author_type=case["role"],
        event_type="history_import.chat" if source == "history_import" else EventTypes.USER_MESSAGE,
        user_id="synthetic_user",
        session_id=case["id"],
    )
    window = L2EventWindow(events=[event])
    profile = resolve_extraction_profile(
        SimpleNamespace(**event.to_dict()),
        profile_registry=build_extraction_profile_registry(_profiles()),
    )
    context = [
        dict(message, event_id=f"context-{i}", session_seq=i)
        for i, message in enumerate(case["context"])
    ]
    service = _RecordingService(live_pool)
    try:
        result = await asyncio.wait_for(
            service.extract_phase1(
                event_window=window,
                focal_subject={"entity_ref": "user:self"},
                context_messages=context,
                extraction_instructions=profile.extraction_instructions,
            ),
            timeout=120,
        )
        grounding = ground_phase1_fact_claims(result, window, context_messages=context)
        actual = {
            _claim_key(claim) for claim in result.fact_claims if claim.subject_ref == "user:self"
        }
        expected, allowed = (
            {tuple(item) for item in case["expected"]},
            {tuple(item) for item in case["allowed"]},
        )
        missing, unexpected = expected - actual, actual - expected - allowed
        _report(
            f"{source}-{case['id']}",
            live_pool,
            service,
            claims=[c.to_dict() for c in result.fact_claims],
            diagnostics=result.diagnostics,
            grounding=grounding,
            missing=sorted(missing),
            unexpected=sorted(unexpected),
        )
        assert not missing and not unexpected, {"missing": missing, "unexpected": unexpected}
    except Exception as exc:
        _report(f"{source}-{case['id']}-failure", live_pool, service, error_type=type(exc).__name__)
        raise


@pytest.mark.parametrize("case", _FAILURES, ids=lambda case: case["id"])
async def test_live_review_rejects_recorded_model_misattribution(case, live_pool):
    service = _RecordingService(live_pool)
    result = L2Phase1Result.from_dict(case["response"])
    for claim in result.fact_claims:
        claim.supporting_event_ids = ["evt"]
    await asyncio.wait_for(
        review_self_report_claims(
            generate_json=service._generate_json,
            result=result,
            event_window=L2EventWindow(
                events=[L2BatchEvent(event_id="evt", content=case["content"], source="chat")]
            ),
            context_messages=[],
        ),
        timeout=120,
    )
    _report(
        f"review-replay-{case['id']}",
        live_pool,
        service,
        claims=[c.to_dict() for c in result.fact_claims],
    )
    assert result.fact_claims == []


@pytest.mark.parametrize(
    "case_id", ["preferred_address", "mixed_speakers", "translation_request", "assistant_claim"]
)
async def test_live_claims_and_portrait_use_only_user_self_reports(case_id, live_pool, tmp_path):
    case = next(case for case in _CASES if case["id"] == case_id)
    memory = await documents._memory(tmp_path, live_pool.get(LLMScenario.AUXILIARY))
    service = _RecordingService(live_pool)
    memory.l2_llm_service = service
    memory.l2_pipeline._llm_service = service
    try:
        ingest = await memory.ingest_event(
            {
                "id": f"evt-{case_id}",
                "type": EventTypes.USER_MESSAGE,
                "source": "chat",
                "timestamp": 1_790_000_000.0,
                "data": {
                    "user_id": "local_user",
                    "session_id": case_id,
                    "content": case["content"],
                },
            }
        )
        assert ingest["l2_job_enqueued"]
        deadline = asyncio.get_running_loop().time() + 120
        while asyncio.get_running_loop().time() < deadline:
            stats = memory.get_l2_pipeline_stats()
            assert not stats["extract_failed"], stats
            if stats["extract_completed"]:
                break
            await asyncio.sleep(0.1)
        assert stats["extract_completed"] == 1, stats
        claims = await memory.l2.list_grounded_claims(user_id="local_user")
        _report(f"portrait-{case_id}", live_pool, service, claims=claims)
        own = [claim for claim in claims if claim["subject_ref"] == "user:local_user"]
        expected = {item[1] for item in case["expected"]}
        assert {claim["object_surface"] or claim["object_value"] for claim in own} == expected
        for claim in own:
            evidence = (await memory.l2.get_grounded_claim(claim["claim_id"]))["evidence"]
            assert evidence
            for row in evidence:
                assert row["author_type"] == "user"
                locator = row["evidence_locator"]
                assert locator["attribution"] == "author_prose"
                quote = case["content"][locator["start"] : locator["end"]]
                assert quote
                assert locator["quote_hash"] == hashlib.sha256(quote.encode()).hexdigest()
        assertions = await memory.l2.list_current_assertions(
            entity_id="user:local_user", committed_only=False
        )
        portrait = await UserPortraitProjectionBuilder(memory.l2).build("local_user")
        _report(
            f"portrait-{case_id}",
            live_pool,
            service,
            claims=claims,
            assertions=assertions,
            portrait={
                "world": portrait.world,
                "recent": portrait.recent,
                "prompt": portrait.prompt_summary,
            },
        )
        rendered = json.dumps(
            {
                "assertions": assertions,
                "world": portrait.world,
                "recent": portrait.recent,
                "prompt": portrait.prompt_summary,
            },
            ensure_ascii=False,
        )
        assert "赵宁" not in rendered and "Alice" not in rendered and "DIIV" not in rendered
        if not expected:
            assert own == [] and assertions == []
        else:
            assert assertions
        assert service.responses
    finally:
        await memory.shutdown()
