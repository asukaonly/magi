from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from pydantic import ValidationError

from magi.api.routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
    PersonalityConfigModel,
)
import magi.api.services.personality_generation.contracts as generation_contracts
import magi.api.services.personality_generation.jobs as generation_jobs
import magi.api.services.personality_generation.model_stages as generation_model_stages
import magi.api.services.personality_generation.normalization as generation_normalization
import magi.api.services.personality_generation.prompting as generation_prompting
import magi.api.services.personality_generation.quality as generation_quality
import magi.api.services.personality_generation.reference as generation_reference
import magi.api.services.personality_generation.stage_pipeline as generation_stage_pipeline
from magi.api.services import (
    personality_generation_prompts as generation_prompts,
)
from magi.config.models import LLMProviderSettings, LLMScenario, LLMSelectionSettings, LLMSettings
from magi.i18n import language_context


class _FakeLLMAdapter:
    provider_name = "openai"
    model_name = "fake-core"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def _capture_chat_call(self, kwargs: dict[str, object]) -> dict[str, object]:
        messages = kwargs.get("messages") if isinstance(kwargs.get("messages"), list) else []
        system_prompt = ""
        prompt = ""
        if messages:
            first = messages[0]
            if isinstance(first, dict) and first.get("role") == "system":
                system_prompt = str(first.get("content") or "")
            last = messages[-1]
            if isinstance(last, dict):
                prompt = str(last.get("content") or "")
        captured = dict(kwargs)
        captured["system_prompt"] = system_prompt
        captured["prompt"] = prompt
        return captured

    async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(self._capture_chat_call(kwargs))
        return self._content()

    async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return self._content()

    def _content(self) -> str:
        return """
        {
                    "name": "Astra",
                    "description": "Helpful",
                    "avatar": "",
                    "_meta_design": {
                        "core_theme": "Calm steadiness with a practical edge.",
                        "failure_mode": "Generic assistant politeness with no recognizable center.",
                        "key_constraint": "Keep most replies ordinary and let precision carry the personality."
                    },
                    "identity_core": {
                        "identity_statement": "A calm character shaped by careful observation and steady judgment in difficult moments.",
                        "values_loved": ["clarity"],
                        "values_rejected": ["panic"],
                        "attention_biases": ["user need"]
          },
                    "idiolect": {"sentence_style": "Calm and supportive"},
                    "registers": {"chat": {"description": "casual", "behavior": "Be calm."}},
                    "appearance_prompt": "simple"
        }
        """


class _NumericAgeLLMAdapter(_FakeLLMAdapter):
    def _content(self) -> str:
        return """
        {
                    "name": 14,
                    "description": "Helpful",
                    "avatar": "",
                    "identity_core": {
                        "identity_statement": "A thoughtful character shaped by observation, duty, and a strong desire to act with precision.",
                        "values_loved": ["precision"],
                        "values_rejected": ["carelessness"],
                        "attention_biases": ["risk"]
          },
                    "idiolect": {"sentence_style": "Calm and supportive"},
                    "registers": {"chat": {"description": "casual", "behavior": "Be calm."}},
                    "appearance_prompt": "simple"
        }
        """


class _RecordingResolver:
    def __init__(self):
        self.requested: list[LLMScenario] = []

    def __call__(self, scenario: LLMScenario, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        self.requested.append(scenario)
        return _FakeLLMAdapter()


class _ConcurrencyTrackingAdapter(_FakeLLMAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.active_calls = 0
        self.max_active_calls = 0

    async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.01)
            return await super().chat(**kwargs)
        finally:
            self.active_calls -= 1


class _SequentialLLMAdapter(_FakeLLMAdapter):
    def __init__(self, responses: list[str]) -> None:
        super().__init__()
        self._responses = list(responses)

    def _content(self) -> str:
        if not self._responses:
            raise AssertionError("No fake LLM response left")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_ai_generate_personality_uses_core_scenario(monkeypatch) -> None:
    from magi.api.routers import personality_config

    resolver = _RecordingResolver()

    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        resolver,
    )

    result = await personality_config.ai_generate_personality("一个冷静可靠的助手", target_language="Chinese")

    assert result.name == "Astra"
    assert set(result.registers) == {"chat", "analysis", "task", "emotional", "crisis"}
    assert len(result.quiet_hours) >= 2
    assert len(result.signature_triggers) >= 3
    assert result.persona_layers[0].layer_id == "surface"
    assert result.bootstrap is not None
    assert "_meta_design" not in result.model_dump()
    assert len(resolver.requested) >= 3
    assert set(resolver.requested) == {LLMScenario.CORE}


@pytest.mark.asyncio
async def test_generate_personality_route_uses_staged_facade_result(monkeypatch) -> None:
    from magi.api.routers import personality_config

    async def _fake_generate_result(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        return personality_config.PersonalityGenerationResult(
            config=personality_config.PersonalityConfigModel(name="Route Persona"),
            stages=[{"stage_id": "base", "status": "completed"}],
        )

    monkeypatch.setattr(personality_config, "ai_generate_personality_result", _fake_generate_result)

    response = await personality_config.generate_personality(
        personality_config.AIGenerateRequest(description="生成一个稳定人格")
    )

    assert response.success is True
    assert response.data["name"] == "Route Persona"
    assert response.stages == [{"stage_id": "base", "status": "completed"}]


@pytest.mark.asyncio
async def test_personality_generation_job_routes_return_progress_snapshots(monkeypatch) -> None:
    from magi.api.routers import personality_config

    async def _fake_start_job(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        return {
            "job_id": "job-1",
            "status": "running",
            "stages": [{"stage_id": "base", "status": "running"}],
        }

    async def _fake_get_job(job_id: str):
        assert job_id == "job-1"
        return {
            "job_id": "job-1",
            "status": "completed",
            "data": {"name": "Generated"},
            "stages": [{"stage_id": "base", "status": "completed"}],
        }

    monkeypatch.setattr(personality_config, "ai_start_personality_generation_job", _fake_start_job)
    monkeypatch.setattr(personality_config, "ai_get_personality_generation_job", _fake_get_job)

    start_response = await personality_config.start_personality_generation(
        personality_config.AIGenerateRequest(description="生成一个稳定人格")
    )
    status_response = await personality_config.get_personality_generation_status("job-1")

    assert start_response.data["job_id"] == "job-1"
    assert start_response.stages == [{"stage_id": "base", "status": "running"}]
    assert status_response.data["status"] == "completed"
    assert status_response.data["data"]["name"] == "Generated"


@pytest.mark.asyncio
async def test_reference_verification_returns_stable_fake_ip_error_code(monkeypatch) -> None:
    from magi.api.routers import personality_config

    class FakeIpCompatibilityError(RuntimeError):
        code = "FAKE_IP_COMPATIBILITY_REQUIRED"

    async def _blocked_verification(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        raise FakeIpCompatibilityError("TUN fake-IP compatibility is required")

    monkeypatch.setattr(
        personality_config,
        "ai_verify_persona_reference_identity",
        _blocked_verification,
    )

    request = personality_config.PersonaIdentityVerifyRequest(
        description="Reference",
        reference=personality_config.PersonaReferenceModel(
            source_kind="fictional_reference",
            name="Reference",
            user_confirmed=True,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await personality_config.verify_personality_reference_identity(request)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "message": "TUN fake-IP compatibility is required",
        "error_code": "FAKE_IP_COMPATIBILITY_REQUIRED",
    }


@pytest.mark.asyncio
async def test_persona_intent_route_returns_editable_reference_candidates(monkeypatch) -> None:
    from magi.api.routers import personality_config

    resolution = personality_config.PersonaIntentResolutionModel(
        status="ambiguous",
        candidates=[
            personality_config.PersonaReferenceCandidateModel(
                candidate_id="candidate-1",
                source_kind="fictional_reference",
                name="孙悟空",
                work_title="西游记",
                confidence=0.52,
            ),
            personality_config.PersonaReferenceCandidateModel(
                candidate_id="candidate-2",
                source_kind="fictional_reference",
                name="孙悟空",
                work_title="龙珠",
                confidence=0.46,
            ),
        ],
        confidence=0.52,
        requires_confirmation=True,
    )

    async def _fake_resolve(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert args == ("孙悟空", "Chinese")
        assert kwargs["llm_override"] is None
        return resolution

    monkeypatch.setattr(
        personality_config,
        "ai_resolve_persona_generation_intent",
        _fake_resolve,
    )

    response = await personality_config.resolve_personality_generation_intent(
        personality_config.PersonaIntentResolveRequest(
            description="孙悟空",
            target_language="Chinese",
        )
    )

    assert response.success is True
    assert response.data.status == "ambiguous"
    assert [candidate.work_title for candidate in response.data.candidates] == ["西游记", "龙珠"]


@pytest.mark.asyncio
async def test_persona_intent_resolver_uses_one_core_json_call() -> None:
    from magi.api.services.personality_generation_intent import (
        resolve_persona_generation_intent,
    )

    adapter = _SequentialLLMAdapter([
        json.dumps(
            {
                "status": "ambiguous",
                "confidence": 0.55,
                "candidates": [
                    {
                        "source_kind": "fictional_reference",
                        "name": "孙悟空",
                        "work_title": "西游记",
                        "version": None,
                        "context": "古典小说人物",
                        "confidence": 0.55,
                    },
                    {
                        "source_kind": "fictional_reference",
                        "name": "孙悟空",
                        "work_title": "龙珠",
                        "version": None,
                        "context": "日本漫画角色",
                        "confidence": 0.44,
                    },
                ],
                "explicit_constraints": ["不要频繁自报作品设定"],
            },
            ensure_ascii=False,
        )
    ])
    scenarios: list[LLMScenario] = []

    def _resolver(scenario: LLMScenario, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        scenarios.append(scenario)
        return adapter

    result = await resolve_persona_generation_intent(
        "孙悟空，但不要频繁自报作品设定",
        target_language="Chinese",
        adapter_resolver=_resolver,
        adapter_factory=None,
    )

    assert scenarios == [LLMScenario.CORE]
    assert result.status == "ambiguous"
    assert result.requires_confirmation is True
    assert [candidate.candidate_id for candidate in result.candidates] == [
        "candidate-1",
        "candidate-2",
    ]
    assert result.explicit_constraints == ["不要频繁自报作品设定"]
    assert len(adapter.calls) == 1
    assert "You resolve a short user description" in str(adapter.calls[0]["system_prompt"])
    assert adapter.calls[0]["max_tokens"] == 800


@pytest.mark.asyncio
async def test_set_current_personality_missing_name_returns_localized_detail() -> None:
    from magi.api.routers import personality_config

    with language_context("zh-CN"):
        with pytest.raises(HTTPException) as exc_info:
            await personality_config.api_set_current_personality({})

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "缺少人格名称"


@pytest.mark.asyncio
async def test_personality_generation_missing_job_returns_localized_detail(monkeypatch) -> None:
    from magi.api.routers import personality_config

    async def _missing_job(job_id: str):
        assert job_id == "missing-job"
        return None

    monkeypatch.setattr(personality_config, "ai_get_personality_generation_job", _missing_job)

    with language_context("zh-CN"):
        with pytest.raises(HTTPException) as exc_info:
            await personality_config.get_personality_generation_status("missing-job")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "未找到人格生成任务"


@pytest.mark.asyncio
async def test_ai_generate_personality_passes_current_draft_to_prompt(monkeypatch) -> None:
    from magi.api.routers import personality_config

    adapter = _FakeLLMAdapter()
    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: adapter,
    )

    current = personality_config.PersonalityConfigModel(
        name="Draft Persona",
        identity_core=personality_config.IdentityCoreModel(identity_statement="Keep this explicit draft core."),
    )

    result = await personality_config.ai_generate_personality(
        "补全这个人格，不要重写名字",
        target_language="Chinese",
        current_config=current,
    )

    assert result.name == "Astra"
    prompt = adapter.calls[0]["prompt"]
    system_prompts = "\n".join(str(call["system_prompt"]) for call in adapter.calls)
    prompts = "\n".join(str(call["prompt"]) for call in adapter.calls)
    assert "# Existing Draft Config" in prompt
    assert "Draft Persona" in prompt
    assert "Keep this explicit draft core" in prompt
    assert "# Design Anchors" in prompts
    assert "failure_mode_to_avoid" in prompts
    assert "Generic assistant politeness" in prompts
    assert "fixed baseline" in system_prompts
    assert "Do not customize, rename, unlock, or put modifiers into surface" in system_prompts


@pytest.mark.asyncio
async def test_ai_generate_personality_defaults_to_concrete_language(monkeypatch) -> None:
    from magi.api.routers import personality_config

    adapter = _FakeLLMAdapter()
    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: adapter,
    )

    await personality_config.ai_generate_personality("Generate an ordinary but vivid assistant")

    prompts = "\n".join(str(call["prompt"]) for call in adapter.calls)
    assert "Target Language: English" in prompts


@pytest.mark.asyncio
async def test_ai_generate_personality_limits_parallel_llm_calls(monkeypatch) -> None:
    from magi.api.routers import personality_config
    from magi.api.services.personality_generation import PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS

    adapter = _ConcurrencyTrackingAdapter()
    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: adapter,
    )

    await personality_config.ai_generate_personality("一个有层次但稳定的人格", target_language="Chinese")

    assert adapter.max_active_calls <= PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS


@pytest.mark.asyncio
async def test_ai_generate_personality_prefers_llm_override(monkeypatch) -> None:
    from magi.api.routers import personality_config

    captured: dict[str, object] = {}

    class _OverrideAdapter(_FakeLLMAdapter):
        provider_name = "anthropic"
        model_name = "claude-sonnet-4-6"

    def _fake_create_llm_adapter(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return _OverrideAdapter()

    monkeypatch.setattr(personality_config, "create_llm_adapter", _fake_create_llm_adapter)

    draft_provider = LLMProviderSettings(
        enabled=True,
        provider_type="custom",
        api_format="anthropic",
        display_name="Draft Claude",
    )
    draft_provider.services.chat.api_key = "draft-key"
    draft_provider.services.chat.base_url = "https://relay.example.com"

    result = await personality_config.ai_generate_personality(
        "一个冷静可靠的助手",
        target_language="Chinese",
        llm_override=LLMSettings(
            providers={
                "draft-provider": draft_provider
            },
            selections={
                "context_decider": LLMSelectionSettings(provider_id="draft-provider", model="claude-sonnet-4-6"),
                "core": LLMSelectionSettings(provider_id="draft-provider", model="claude-sonnet-4-6"),
            },
        ),
    )

    assert result.name == "Astra"
    assert captured == {
        "provider_type": "anthropic",
        "api_key": "draft-key",
        "model": "claude-sonnet-4-6",
        "base_url": "https://relay.example.com",
        "proxy_url": None,
        "timeout": 60,
    }


@pytest.mark.asyncio
async def test_ai_generate_personality_uses_registry_default_base_url_for_builtin_override(monkeypatch) -> None:
    from magi.api.routers import personality_config

    captured: dict[str, object] = {}

    class _OverrideAdapter(_FakeLLMAdapter):
        provider_name = "glm"
        model_name = "glm-4.7-flash"

    def _fake_create_llm_adapter(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return _OverrideAdapter()

    monkeypatch.setattr(personality_config, "create_llm_adapter", _fake_create_llm_adapter)

    glm_provider = LLMProviderSettings(
        enabled=True,
        provider_type="glm",
        display_name="Z.ai",
    )
    glm_provider.services.chat.api_key = "glm-key"
    glm_provider.services.chat.base_url = ""

    result = await personality_config.ai_generate_personality(
        "一个冷静可靠的助手",
        target_language="Chinese",
        llm_override=LLMSettings(
            providers={
                "glm": glm_provider
            },
            selections={
                "context_decider": LLMSelectionSettings(provider_id="glm", model="glm-4.7-flash"),
                "core": LLMSelectionSettings(provider_id="glm", model="glm-4.7-flash"),
            },
        ),
    )

    assert result.name == "Astra"
    assert captured == {
        "provider_type": "glm",
        "api_key": "glm-key",
        "model": "glm-4.7-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "proxy_url": None,
        "timeout": 60,
    }


@pytest.mark.asyncio
async def test_ai_generate_personality_coerces_numeric_top_level_fields(monkeypatch) -> None:
    from magi.api.routers import personality_config

    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: _NumericAgeLLMAdapter(),
    )

    result = await personality_config.ai_generate_personality("eva里的明日香", target_language="Chinese")

    assert result.name == "14"


def test_normalize_generated_personality_payload_completes_sparse_payload() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload({
        "name": "Sparse",
        "registers": {"chat": {"behavior": "Stay ordinary."}},
        "signature_triggers": [{"trigger_id": "focus", "activates_when": "Work", "behavior_shift": "Quieter"}],
    })

    assert set(payload["registers"]) == {"chat", "analysis", "task", "emotional", "crisis"}
    assert len(payload["quiet_hours"]) == 2
    assert len(payload["signature_triggers"]) == 3
    assert payload["persona_layers"][0]["layer_id"] == "surface"
    assert [item["layer_id"] for item in payload["persona_layers"]] == ["surface"]
    assert payload["bootstrap"]["opening_line"]
    assert set(payload["dynamic_state_rules"]) == {"low_energy", "high_stress", "positive_mood"}
    assert sum(len(item["examples"]) for item in payload["registers"].values()) >= 6


def test_normalize_generated_personality_payload_cleans_generation_quality_issues() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload(
        {
            "name": "明日香",
            "description": "强 烈但普通的存在",
            "identity_core": {"identity_statement": "她并不 是为了表演而存在。"},
            "idiolect": {"sentence_style": "说话直 接。"},
            "persona_layers": [
                {"layer_id": "crack", "unlock_condition": {"trust_level_gte": 2, "interaction_count_gte": "15"}, "modifiers": {}},
                {"layer_id": "revealed", "unlock_condition": {"trust_level_gte": 4}, "modifiers": {}},
            ],
            "bootstrap": {"opening_line": "Hi, I'm 明日香. What should I call you?"},
        },
        target_language="Chinese",
    )

    assert payload["description"] == "强烈但普通的存在"
    assert payload["identity_core"]["identity_statement"] == "她并不是为了表演而存在。"
    assert payload["idiolect"]["sentence_style"] == "说话直接。"
    assert payload["bootstrap"]["opening_line"].startswith("我是明日香")
    assert payload["persona_layers"][1]["unlock_condition"]["trust_level_gte"] == 0.2
    assert payload["persona_layers"][1]["unlock_condition"]["interaction_count_gte"] == 15
    assert payload["persona_layers"][2]["unlock_condition"]["trust_level_gte"] == 0.4


def test_normalize_generated_personality_payload_absorbs_misnested_register_examples() -> None:
    from magi.api.routers.personality_config import PersonalityConfigModel, normalize_generated_personality_payload

    payload = normalize_generated_personality_payload(
        {
            "name": "明日香",
            "registers": {
                "chat": {
                    "description": "日常交流",
                    "behavior": ["短句", "直接"],
                },
                "examples": [
                    {
                        "register_id": "ordinary_conversation",
                        "examples": [
                            {
                                "user_input": "今天天气不错。",
                                "assistant_output": "哼，至少你还看得见太阳。",
                            }
                        ],
                    },
                    {
                        "register_id": "task",
                        "examples": [
                            {
                                "user_input": "帮我修这个 bug。",
                                "assistant_output": "先把报错给我，别只说坏了。",
                            }
                        ],
                    },
                ],
            },
        },
        target_language="Chinese",
    )

    assert "examples" not in payload["registers"]
    assert "短句" in payload["registers"]["chat"]["behavior"]
    assert any("今天天气不错" in example for example in payload["registers"]["chat"]["examples"])
    assert any("帮我修这个 bug" in example for example in payload["registers"]["task"]["examples"])
    PersonalityConfigModel(**payload)


def test_normalize_generated_personality_payload_accepts_assistant_reply_examples() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload(
        {
            "name": "明日香",
            "registers": {
                "chat": {
                    "description": "日常交流",
                    "behavior": "短句直接",
                    "examples": [
                        {"user_input": "你好", "assistant_reply": "哼，有事快说。"},
                        {"user_input": "在忙吗", "reply": "在，说重点。"},
                    ],
                },
            },
        },
        target_language="Chinese",
    )

    chat_examples = payload["registers"]["chat"]["examples"]
    assert any("有事快说" in example for example in chat_examples)
    assert any("说重点" in example for example in chat_examples)


def test_normalize_generated_personality_payload_uses_chinese_fallback_copy() -> None:
    import re

    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload({"name": "明日香"}, target_language="Chinese")

    cjk = re.compile(r"[\u3400-\u9fff]")
    assert all(cjk.search(item["condition"]) for item in payload["quiet_hours"])
    assert all(cjk.search(value) for value in payload["dynamic_state_rules"].values())
    for register in payload["registers"].values():
        assert cjk.search(register["description"])
        assert cjk.search(register["behavior"])
        for example in register["examples"]:
            assert cjk.search(example)
    for trigger in payload["signature_triggers"]:
        assert cjk.search(trigger["activates_when"])
        assert cjk.search(trigger["exit_behavior"])


def test_generation_quality_findings_flags_assistantized_identity() -> None:
    combined = {
        "name": "明日香",
        "description": "一位自信、直率且好胜的助手，在自然交流模式下提供帮助。",
        "identity_core": {"identity_statement": "她是被公开形象启发的陪伴者。"},
    }

    findings = generation_quality._generation_quality_findings(combined, "eva里的明日香", None)

    assert any("助手" in item and "description" in item for item in findings)
    assert any("自然交流模式" in item for item in findings)
    assert any("陪伴者" in item and "identity_statement" in item for item in findings)


def test_generation_quality_findings_respect_user_requested_assistant_role() -> None:
    combined = {"name": "Echo", "description": "一个冷静可靠的助手。"}

    findings = generation_quality._generation_quality_findings(combined, "一个冷静可靠的助手", None)

    assert findings == []


@pytest.mark.parametrize(
    ("source_kind", "fidelity_level", "expected"),
    [
        ("original", "natural", False),
        ("fictional_reference", "natural", True),
        ("public_person_reference", "natural", True),
        ("private_person_reference", "traits", False),
    ],
)
def test_reference_profile_stage_only_runs_for_confirmed_public_references(
    source_kind: str,
    fidelity_level: str,
    expected: bool,
) -> None:
    from magi.api.routers.personality_config_schemas import PersonaReferenceModel

    reference = None
    if source_kind != "original":
        reference = PersonaReferenceModel(
            source_kind=source_kind,
            name="Reference",
            user_confirmed=True,
        )
    intent = PersonaGenerationIntentModel(
        source_kind=source_kind,
        reference=reference,
        fidelity_level=fidelity_level,
        expression_level="low" if fidelity_level == "traits" else "balanced",
        research={"preference": "disabled"},
    )

    assert generation_reference._should_prepare_reference_profile(intent) is expected


def test_reference_profile_normalization_preserves_unverified_provenance() -> None:
    from magi.api.routers.personality_config_schemas import PersonaReferenceModel

    intent = PersonaGenerationIntentModel(
        source_kind="fictional_reference",
        reference=PersonaReferenceModel(
            source_kind="fictional_reference",
            name="明日香",
            work_title="新世纪福音战士",
            version="TV版",
            user_confirmed=True,
        ),
        fidelity_level="natural",
        expression_level="balanced",
        research={"preference": "disabled"},
    )

    profile = generation_reference._normalize_reference_profile_payload(
        {
            "provenance_kind": "verified_source",
            "reference": {"name": "Wrong reference"},
            "dimensions": {
                "ordinary_baseline": ["平时直接，但不持续表演高强度情绪。"],
                "signature_markers": "强烈表达只在被挑战时出现。",
                "invented_dimension": ["must be discarded"],
            },
            "unknowns": ["不同版本的细节差异"],
            "confidence_by_dimension": {
                "ordinary_baseline": "high",
                "signature_markers": "uncertain",
                "invented_dimension": "high",
            },
        },
        intent,
    )

    assert profile["provenance_kind"] == "parametric_prior"
    assert profile["reference"] == {
        "source_kind": "fictional_reference",
        "name": "明日香",
        "work_title": "新世纪福音战士",
        "version": "TV版",
    }
    assert profile["dimensions"]["signature_markers"] == ["强烈表达只在被挑战时出现。"]
    assert "invented_dimension" not in profile["dimensions"]
    assert profile["confidence_by_dimension"] == {"ordinary_baseline": "high"}


def test_reference_profile_slices_match_generation_stage_needs() -> None:
    profile = {
        "provenance_kind": "parametric_prior",
        "reference": {"name": "Reference"},
        "dimensions": {
            key: [f"{key} observation"]
            for key in generation_reference.REFERENCE_PROFILE_DIMENSIONS
        },
        "unknowns": ["version unclear"],
        "confidence_by_dimension": {
            key: "medium"
            for key in generation_reference.REFERENCE_PROFILE_DIMENSIONS
        },
    }

    base_block = generation_reference._reference_profile_block(profile, "base")
    rules_block = generation_reference._reference_profile_block(profile, "rules")

    assert "ordinary_baseline observation" in base_block
    assert "judgment_patterns observation" in base_block
    assert "signature_markers observation" not in base_block
    assert "signature_markers observation" in rules_block
    assert "ordinary_baseline observation" not in rules_block
    assert "not verified evidence" in base_block


@pytest.mark.asyncio
async def test_reference_profile_stage_uses_one_unverified_profile_call() -> None:
    from magi.api.routers.personality_config_schemas import PersonaReferenceModel

    adapter = _SequentialLLMAdapter([
        json.dumps(
            {
                "provenance_kind": "parametric_prior",
                "reference": {"name": "明日香"},
                "dimensions": {
                    "ordinary_baseline": ["普通状态更克制。"],
                    "judgment_patterns": ["重视能力与自尊。"],
                    "speech_rhythm": ["直接、短促。"],
                    "interaction_patterns": [],
                    "signature_markers": [],
                    "contrast_contexts": [],
                    "version_notes": [],
                },
                "unknowns": ["版本差异"],
                "confidence_by_dimension": {"ordinary_baseline": "medium"},
            },
            ensure_ascii=False,
        )
    ])
    intent = PersonaGenerationIntentModel(
        source_kind="fictional_reference",
        reference=PersonaReferenceModel(
            source_kind="fictional_reference",
            name="明日香",
            work_title="新世纪福音战士",
            user_confirmed=True,
        ),
        fidelity_level="natural",
        expression_level="balanced",
        research={"preference": "disabled"},
    )
    context = generation_contracts._GenerationRunContext(
        description="EVA里的明日香，日常一点",
        target_language="Chinese",
        current_config=None,
        llm_override=None,
        intent=intent,
        adapter_resolver=lambda *args, **kwargs: adapter,
        adapter_factory=lambda **kwargs: adapter,
        stage_progress_callback=None,
    )

    profile = await generation_reference._run_reference_profile_stage(context)

    assert profile is not None
    assert profile["provenance_kind"] == "parametric_prior"
    assert profile["reference"]["work_title"] == "新世纪福音战士"
    assert len(adapter.calls) == 1
    assert "unverified reference profile" in str(adapter.calls[0]["system_prompt"])
    assert adapter.calls[0]["max_tokens"] == 1300


@pytest.mark.asyncio
async def test_referenced_persona_generation_injects_profile_before_base() -> None:
    from magi.api.routers.personality_config_schemas import PersonaReferenceModel
    from magi.api.services import personality_generation

    adapter = _FakeLLMAdapter()
    intent = PersonaGenerationIntentModel(
        source_kind="fictional_reference",
        reference=PersonaReferenceModel(
            source_kind="fictional_reference",
            name="明日香",
            work_title="新世纪福音战士",
            user_confirmed=True,
        ),
        fidelity_level="natural",
        expression_level="balanced",
        research={"preference": "disabled"},
    )

    result = await personality_generation.generate_personality_config_result(
        "EVA里的明日香，日常一点",
        target_language="Chinese",
        intent=intent,
        adapter_resolver=lambda *args, **kwargs: adapter,
        adapter_factory=lambda **kwargs: adapter,
    )

    assert result.config.name == "Astra"
    assert "unverified reference profile" in str(adapter.calls[0]["system_prompt"])
    base_call = next(
        call
        for call in adapter.calls
        if str(call["system_prompt"]) == generation_prompts.BASE_SPINE_SYSTEM_PROMPT
    )
    assert "# Unverified Reference Profile" in str(base_call["prompt"])
    assert '"provenance_kind": "parametric_prior"' in str(base_call["prompt"])
    assert "not verified evidence" in str(base_call["prompt"])


@pytest.mark.asyncio
async def test_post_integration_quality_check_repairs_and_rechecks(monkeypatch) -> None:
    responses = iter([
        {},
        {
            "description": "一位自信、直接且好胜的角色。",
            "identity_core": {"identity_statement": "她重视能力、自尊与直接判断。"},
        },
    ])
    stage_ids: list[str] = []

    async def _fake_stage(**kwargs):  # type: ignore[no-untyped-def]
        stage_ids.append(str(kwargs["stage_id"]))
        return next(responses)

    monkeypatch.setattr(generation_stage_pipeline, "_run_generation_stage", _fake_stage)
    context = generation_contracts._GenerationRunContext(
        description="EVA里的明日香",
        target_language="Chinese",
        current_config=None,
        llm_override=None,
        intent=None,
        adapter_resolver=lambda *args, **kwargs: _FakeLLMAdapter(),
        adapter_factory=lambda **kwargs: _FakeLLMAdapter(),
        stage_progress_callback=None,
    )
    combined = {
        "description": "一位自信、直接且好胜的助手。",
        "identity_core": {"identity_statement": "她是陪伴用户的角色。"},
    }
    stages: list[dict[str, str]] = []

    await generation_stage_pipeline._run_integration_personality_stage(
        context,
        stages,
        combined,
        None,
    )

    assert stage_ids == ["integrate", "integrate_quality_repair"]
    assert generation_quality._generation_quality_findings(combined, context.description, None) == []


@pytest.mark.asyncio
async def test_post_integration_quality_check_rejects_known_bad_result(monkeypatch) -> None:
    async def _fake_stage(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {}

    monkeypatch.setattr(generation_stage_pipeline, "_run_generation_stage", _fake_stage)
    context = generation_contracts._GenerationRunContext(
        description="EVA里的明日香",
        target_language="Chinese",
        current_config=None,
        llm_override=None,
        intent=None,
        adapter_resolver=lambda *args, **kwargs: _FakeLLMAdapter(),
        adapter_factory=lambda **kwargs: _FakeLLMAdapter(),
        stage_progress_callback=None,
    )
    combined = {"description": "一位自信但通用的助手。"}

    with pytest.raises(ValueError, match="quality checks still fail"):
        await generation_stage_pipeline._run_integration_personality_stage(
            context,
            [],
            combined,
            None,
        )


def test_integration_prompt_includes_quality_findings_block() -> None:
    prompt = generation_prompting._integration_user_prompt(
        "eva里的明日香",
        "Chinese",
        {"name": "明日香"},
        None,
        findings=["description frames the persona as a service role."],
    )

    assert "# Detected Quality Findings" in prompt
    assert "service role" in prompt

    clean_prompt = generation_prompting._integration_user_prompt(
        "eva里的明日香",
        "Chinese",
        {"name": "明日香"},
        None,
    )
    assert "# Detected Quality Findings" not in clean_prompt


def test_persona_generation_shared_directives_avoid_assistant_framing() -> None:
    directives = generation_prompts.PERSONA_GENERATION_SHARED_DIRECTIVES
    assert "always create an assistant" not in directives
    assert "not part of any persona's identity" in directives
    assert "configuration vocabulary" in directives


def test_personality_generation_stage_prompts_share_directives() -> None:
    stage_prompts = [
        generation_prompts.BASE_SPINE_SYSTEM_PROMPT,
        generation_prompts.REGISTER_SYSTEM_PROMPT,
        generation_prompts.RULES_SYSTEM_PROMPT,
        generation_prompts.LAYERS_SYSTEM_PROMPT,
        generation_prompts.BOOTSTRAP_SYSTEM_PROMPT,
        generation_prompts.APPEARANCE_SYSTEM_PROMPT,
        generation_prompts.INTEGRATION_SYSTEM_PROMPT,
    ]

    for prompt in stage_prompts:
        assert generation_prompts.PERSONA_GENERATION_SHARED_DIRECTIVES in prompt
        assert "Output ONLY valid JSON" in prompt
        assert "Stage Quality Checks" in prompt
        assert "state_transition_protocol" in prompt

    assert "generation-only design anchor" in generation_prompts.BASE_SPINE_SYSTEM_PROMPT
    assert (
        "licensed or regulated professional expertise"
        in generation_prompts.PERSONA_GENERATION_SHARED_DIRECTIVES
    )
    assert "Do not add behavior, secrets, modifiers" in generation_prompts.LAYERS_SYSTEM_PROMPT
    assert "single owner of runtime examples" in generation_prompts.REGISTER_SYSTEM_PROMPT
    assert "six to nine good-only examples" in generation_prompts.BOOTSTRAP_SYSTEM_PROMPT
    assert "Never return registers.examples" in generation_prompts.BOOTSTRAP_SYSTEM_PROMPT
    assert "examples must be string arrays" in generation_prompts.BOOTSTRAP_SYSTEM_PROMPT
    assert "few coherent rules" in generation_prompts.RULES_SYSTEM_PROMPT
    assert "cross-field consistency review" in generation_prompts.INTEGRATION_SYSTEM_PROMPT
    assert "Do not include _meta_design" in generation_prompts.INTEGRATION_SYSTEM_PROMPT


def test_personality_generation_root_exposes_only_public_contract() -> None:
    from magi.api.services import personality_generation

    assert personality_generation.__all__ == [
        "GENERATION_STAGE_DEFINITIONS",
        "PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS",
        "PERSONALITY_GENERATION_JOB_TTL_SECONDS",
        "PERSONA_GENERATION_SHARED_DIRECTIVES",
        "PersonalityGenerationJob",
        "PersonalityGenerationResult",
        "REQUIRED_REGISTERS",
        "get_personality_generation_job",
        "generate_personality_config",
        "generate_personality_config_result",
        "normalize_generated_personality_payload",
        "personality_generation_user_content_clear_boundary",
        "start_personality_generation_job",
    ]
    for private_name in (
        "_GenerationRunContext",
        "_deep_merge_payload",
        "_run_generation_stage",
        "_personality_generation_job_snapshot",
        "asyncio",
        "logger",
    ):
        assert not hasattr(personality_generation, private_name)


@pytest.mark.asyncio
async def test_generation_stage_repairs_invalid_json_once() -> None:
    adapter = _SequentialLLMAdapter([
        '{"name": "明日香" "description": "少了逗号"}',
        '{"name": "明日香", "description": "修好了"}',
    ])

    result = await generation_model_stages._run_generation_stage(
        stage_id="integrate",
        prompt="Return final JSON.",
        system_prompt=generation_prompts.INTEGRATION_SYSTEM_PROMPT,
        max_tokens=400,
        temperature=0.4,
        llm_override=None,
        adapter_resolver=lambda *args, **kwargs: adapter,
        adapter_factory=None,
        retry_on_json_error=True,
    )

    assert result == {"name": "明日香", "description": "修好了"}
    assert len(adapter.calls) == 2
    assert "Repair this invalid JSON" in str(adapter.calls[1]["messages"])


@pytest.mark.asyncio
async def test_generation_stage_logs_invalid_json_diagnostics_before_repair(monkeypatch) -> None:
    warning_calls: list[dict[str, object]] = []

    def _capture_warning(event: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        warning_calls.append({"event": event, "args": args, **kwargs})

    monkeypatch.setattr(generation_model_stages.logger, "warning", _capture_warning)

    adapter = _SequentialLLMAdapter([
        '{\n  "name": "明日香"\n  "description": "少了逗号"\n}',
        '{"name": "明日香", "description": "修好了"}',
    ])

    result = await generation_model_stages._run_generation_stage(
        stage_id="integrate",
        prompt="Return final JSON.",
        system_prompt=generation_prompts.INTEGRATION_SYSTEM_PROMPT,
        max_tokens=400,
        temperature=0.4,
        llm_override=None,
        adapter_resolver=lambda *args, **kwargs: adapter,
        adapter_factory=None,
        retry_on_json_error=True,
    )

    assert result == {"name": "明日香", "description": "修好了"}
    diagnostic = next(
        call for call in warning_calls
        if call.get("event") == "personality_generation_invalid_json"
    )
    assert diagnostic["stage_id"] == "integrate"
    assert "Return exactly one JSON object" in str(diagnostic["expected_output_contract"])
    assert "Expecting ',' delimiter" in str(diagnostic["parse_error"])
    assert '"description": "少了逗号"' in str(diagnostic["output_error_context"])
    assert "^" in str(diagnostic["output_error_context"])


def test_generation_json_diagnostics_omit_content_when_disabled(monkeypatch) -> None:
    warning_calls: list[dict[str, object]] = []

    def _capture_warning(event: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        warning_calls.append({"event": event, "args": args, **kwargs})

    monkeypatch.setattr(generation_model_stages.logger, "warning", _capture_warning)
    monkeypatch.setattr(
        generation_model_stages,
        "full_content_logging_enabled",
        lambda: False,
    )
    response_text = '{"name": "PERSONALITY-CONTENT-CANARY" "description": "invalid"}'
    try:
        json.loads(response_text)
    except json.JSONDecodeError as parse_error:
        generation_model_stages._log_invalid_generation_json(
            event="personality_generation_invalid_json",
            stage_id="integrate",
            system_prompt="SYSTEM-PROMPT-CANARY",
            response_text=response_text,
            parse_error=parse_error,
        )

    diagnostic = warning_calls[0]
    assert "expected_output_contract" not in diagnostic
    assert "output_error_context" not in diagnostic
    assert "output_preview" not in diagnostic
    assert diagnostic["system_prompt_chars"] == len("SYSTEM-PROMPT-CANARY")
    assert diagnostic["response_chars"] == len(response_text)
    assert "PERSONALITY-CONTENT-CANARY" not in str(diagnostic)
    assert "SYSTEM-PROMPT-CANARY" not in str(diagnostic)


@pytest.mark.asyncio
async def test_generation_stage_logs_repair_output_when_repair_is_still_invalid(monkeypatch) -> None:
    warning_calls: list[dict[str, object]] = []

    def _capture_warning(event: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        warning_calls.append({"event": event, "args": args, **kwargs})

    monkeypatch.setattr(generation_model_stages.logger, "warning", _capture_warning)

    adapter = _SequentialLLMAdapter([
        '{\n  "name": "明日香"\n  "description": "少了逗号"\n}',
        '{\n  "name": "明日香"\n  "description": "还是少了逗号"\n}',
    ])

    with pytest.raises(json.JSONDecodeError):
        await generation_model_stages._run_generation_stage(
            stage_id="integrate",
            prompt="Return final JSON.",
            system_prompt=generation_prompts.INTEGRATION_SYSTEM_PROMPT,
            max_tokens=400,
            temperature=0.4,
            llm_override=None,
            adapter_resolver=lambda *args, **kwargs: adapter,
            adapter_factory=None,
            retry_on_json_error=True,
        )

    repair_diagnostic = next(
        call for call in warning_calls
        if call.get("event") == "personality_generation_json_repair_invalid"
    )
    assert repair_diagnostic["stage_id"] == "integrate"
    assert "Expecting ',' delimiter" in str(repair_diagnostic["repair_parse_error"])
    assert '"description": "还是少了逗号"' in str(repair_diagnostic["repair_output_error_context"])
    assert "Return exactly one JSON object" in str(repair_diagnostic["expected_output_contract"])


def test_personality_generation_module_prompt_injects_meta_design_anchors() -> None:
    prompt = generation_prompting._module_user_prompt(
        "一个锋利但可靠的人格",
        "Chinese",
        {
            "name": "Seven",
            "_meta_design": {
                "core_theme": "Sharp outside, curious inside.",
                "failure_mode": "AI stacking stale snark to sound edgy.",
                "key_constraint": "Use plain speech first; let critique appear only when useful.",
            },
        },
        None,
        "Design registers.",
    )

    assert "# Design Anchors" in prompt
    assert "core_theme: Sharp outside, curious inside." in prompt
    assert "failure_mode_to_avoid: AI stacking stale snark" in prompt
    assert "key_constraint: Use plain speech first" in prompt


def test_personality_generation_runtime_payload_drops_internal_meta_design() -> None:
    runtime_payload = generation_normalization._runtime_payload_from_combined({
        "name": "Seven",
        "_meta_design": {
            "core_theme": "Sharp outside, curious inside.",
            "failure_mode": "AI stacking stale snark to sound edgy.",
            "key_constraint": "Use plain speech first.",
        },
        "identity_core": {"identity_statement": "Stable core."},
    })

    assert runtime_payload == {
        "name": "Seven",
        "identity_core": {"identity_statement": "Stable core."},
    }


def test_personality_generation_cleanup_uses_lifecycle_ttl(monkeypatch) -> None:
    monkeypatch.setattr(
        "magi.config.get_config",
        lambda: SimpleNamespace(
            lifecycle=SimpleNamespace(
                ephemeral_jobs=SimpleNamespace(personality_generation_ttl_seconds=10)
            )
        ),
    )
    monkeypatch.setattr(
        generation_jobs,
        "_PERSONALITY_GENERATION_JOBS",
        {
            "expired": generation_contracts.PersonalityGenerationJob(
                job_id="expired",
                status="completed",
                stages=[],
                created_at=0,
                updated_at=80,
            ),
            "recent": generation_contracts.PersonalityGenerationJob(
                job_id="recent",
                status="completed",
                stages=[],
                created_at=0,
                updated_at=95,
            ),
        },
    )

    generation_jobs._cleanup_personality_generation_jobs(now=100)

    assert set(generation_jobs._PERSONALITY_GENERATION_JOBS) == {"recent"}


def test_personality_generation_job_snapshot_preserves_error_code() -> None:
    snapshot = generation_jobs._personality_generation_job_snapshot(
        generation_contracts.PersonalityGenerationJob(
            job_id="failed-job",
            status="failed",
            stages=[],
            created_at=0,
            updated_at=1,
            error="TUN fake-IP compatibility is required",
            error_code="FAKE_IP_COMPATIBILITY_REQUIRED",
        )
    )

    assert snapshot["error_code"] == "FAKE_IP_COMPATIBILITY_REQUIRED"


@pytest.mark.asyncio
async def test_personality_generation_job_records_pipeline_failure(monkeypatch) -> None:
    class _GenerationFailure(RuntimeError):
        code = "GENERATION_FAILED"

    async def _fail_generation(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        raise _GenerationFailure("generation stopped")

    monkeypatch.setattr(
        generation_jobs,
        "generate_personality_config_result",
        _fail_generation,
    )
    job = generation_contracts.PersonalityGenerationJob(
        job_id="failed-job",
        status="running",
        stages=[],
        created_at=0,
        updated_at=0,
    )
    generation_jobs._PERSONALITY_GENERATION_JOBS[job.job_id] = job

    try:
        await generation_jobs._run_personality_generation_job(
            job,
            description="A stable persona",
            target_language="English",
            current_config=None,
            llm_override=None,
            intent=None,
            adapter_resolver=lambda *args, **kwargs: object(),
            adapter_factory=lambda *args, **kwargs: object(),
            search_port=None,
            fetch_port=None,
        )
    finally:
        generation_jobs._PERSONALITY_GENERATION_JOBS.pop(job.job_id, None)

    assert job.status == "failed"
    assert job.error == "generation stopped"
    assert job.error_code == "GENERATION_FAILED"
    snapshot = generation_jobs._personality_generation_job_snapshot(job)
    assert snapshot["status"] == "failed"
    assert snapshot["error_code"] == "GENERATION_FAILED"


def test_normalize_generated_personality_payload_keeps_surface_fixed() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload({
        "name": "Layered",
        "persona_layers": [
            {"layer_id": "surface", "unlock_condition": {"trust": 0.2}, "modifiers": {"secret": "too much"}},
            {"layer_id": "crack", "unlock_condition": {"trust_level_gte": 0.4}, "modifiers": {"warmth": "slightly higher"}},
            {"layer_id": "surface", "unlock_condition": None, "modifiers": {"duplicate": "ignored"}},
        ],
    })

    assert payload["persona_layers"][0] == {"layer_id": "surface", "unlock_condition": None, "modifiers": {}}
    assert [item["layer_id"] for item in payload["persona_layers"]] == ["surface", "crack"]


def test_persona_generation_intent_rejects_private_reference_faithful_fidelity() -> None:
    from magi.api.routers.personality_config_schemas import PersonaGenerationIntentModel

    with pytest.raises(ValidationError):
        PersonaGenerationIntentModel(
            source_kind="private_person_reference",
            reference={
                "source_kind": "private_person_reference",
                "name": "Private Person",
                "user_confirmed": True,
            },
            fidelity_level="faithful",
            expression_level="high_contextual",
            research={"preference": "disabled"},
        )


def test_personality_generation_prompt_includes_confirmed_reference_intent() -> None:
    from magi.api.routers.personality_config_schemas import PersonaGenerationIntentModel

    intent = PersonaGenerationIntentModel(
        source_kind="fictional_reference",
        reference={
            "source_kind": "fictional_reference",
            "name": "孙悟空",
            "work_title": "龙珠",
            "version": "漫画后期",
            "user_confirmed": True,
        },
        fidelity_level="natural",
        expression_level="balanced",
        research={"preference": "disabled"},
        explicit_constraints=["少用作品黑话"],
    )

    prompt = generation_prompting._base_user_prompt(
        "孙悟空",
        "Chinese",
        None,
        intent,
    )

    assert "# Resolved Generation Intent" in prompt
    assert '"work_title": "龙珠"' in prompt
    assert '"fidelity_level": "natural"' in prompt
    assert "少用作品黑话" in prompt


@pytest.mark.asyncio
async def test_personality_generation_request_id_is_idempotent(monkeypatch) -> None:
    generation_jobs._PERSONALITY_GENERATION_JOBS.clear()
    generation_jobs._PERSONALITY_GENERATION_REQUEST_INDEX.clear()
    generation_jobs._PERSONALITY_GENERATION_TASKS.clear()
    release = asyncio.Event()

    async def _hold_generation(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        await release.wait()

    monkeypatch.setattr(
        generation_jobs,
        "_run_personality_generation_job",
        _hold_generation,
    )

    first = await generation_jobs.start_personality_generation_job(
        "一个冷静的人格",
        draft_id="draft-1",
        request_id="request-1",
    )
    second = await generation_jobs.start_personality_generation_job(
        "一个冷静的人格",
        draft_id="draft-1",
        request_id="request-1",
    )

    assert first["job_id"] == second["job_id"]
    assert second["draft_id"] == "draft-1"
    assert second["request_id"] == "request-1"
    async with generation_jobs.personality_generation_user_content_clear_boundary():
        pass


@pytest.mark.asyncio
async def test_personality_generation_clear_cancels_and_fences_late_result(
    monkeypatch,
) -> None:
    generation_jobs._PERSONALITY_GENERATION_JOBS.clear()
    generation_jobs._PERSONALITY_GENERATION_REQUEST_INDEX.clear()
    generation_jobs._PERSONALITY_GENERATION_TASKS.clear()
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()

    async def _late_result(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()
        return generation_contracts.PersonalityGenerationResult(
            config=PersonalityConfigModel(name="stale"),
            stages=[],
        )

    monkeypatch.setattr(
        generation_jobs,
        "generate_personality_config_result",
        _late_result,
    )
    snapshot = await generation_jobs.start_personality_generation_job(
        "stale persona request",
        request_id="request-before-clear",
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    clear_entered = asyncio.Event()

    async def _clear() -> None:
        async with generation_jobs.personality_generation_user_content_clear_boundary():
            clear_entered.set()

    clear_task = asyncio.create_task(_clear())
    await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
    assert await generation_jobs.get_personality_generation_job(snapshot["job_id"]) is None

    blocked_start = asyncio.create_task(
        generation_jobs.start_personality_generation_job("new persona request")
    )
    await asyncio.sleep(0)
    assert not blocked_start.done()

    release.set()
    await asyncio.wait_for(clear_task, timeout=1)
    await asyncio.wait_for(clear_entered.wait(), timeout=1)
    new_snapshot = await asyncio.wait_for(blocked_start, timeout=1)

    assert new_snapshot["job_id"] != snapshot["job_id"]
    assert await generation_jobs.get_personality_generation_job(snapshot["job_id"]) is None
    assert "request-before-clear" not in generation_jobs._PERSONALITY_GENERATION_REQUEST_INDEX
    async with generation_jobs.personality_generation_user_content_clear_boundary():
        pass


@pytest.mark.asyncio
async def test_persona_adjustment_filters_unrelated_identity_changes() -> None:
    from magi.api.services.personality_adjustment import adjust_personality_config
    from magi.api.routers.personality_config_schemas import PersonalityConfigModel

    adapter = _SequentialLLMAdapter([
        json.dumps(
            {
                "name": "Wrong replacement",
                "identity_core": {"identity_statement": "Wrong identity"},
                "idiolect": {
                    "sentence_style": "Use shorter, more natural sentences.",
                    "chattiness": 0.2,
                },
            }
        )
    ])
    current = PersonalityConfigModel(
        name="Stable Persona",
        identity_core={"identity_statement": "Keep this identity."},
        idiolect={"sentence_style": "Long and elaborate", "chattiness": 0.8},
    )

    adjusted = await adjust_personality_config(
        current,
        "回复短一点",
        scope="voice",
        target_language="Chinese",
        adapter_resolver=lambda *args, **kwargs: adapter,
        adapter_factory=None,
    )

    assert adjusted.name == "Stable Persona"
    assert adjusted.identity_core.identity_statement == "Keep this identity."
    assert adjusted.idiolect.sentence_style == "Use shorter, more natural sentences."
    assert adjusted.idiolect.chattiness == 0.2


@pytest.mark.asyncio
async def test_persona_adjustment_route_returns_new_draft(monkeypatch) -> None:
    from magi.api.routers import personality_config

    async def _fake_adjust(current_config, instruction, **kwargs):  # type: ignore[no-untyped-def]
        assert current_config.name == "Stable Persona"
        assert instruction == "少一点表演感"
        assert kwargs["scope"] == "expression"
        return current_config.model_copy(update={"description": "Adjusted"})

    monkeypatch.setattr(personality_config, "ai_adjust_personality", _fake_adjust)

    response = await personality_config.adjust_personality(
        personality_config.PersonaAdjustmentRequest(
            current_config=personality_config.PersonalityConfigModel(name="Stable Persona"),
            instruction="少一点表演感",
            scope="expression",
            target_language="Chinese",
        )
    )

    assert response.success is True
    assert response.data["name"] == "Stable Persona"
    assert response.data["description"] == "Adjusted"


def test_persona_intent_route_is_reachable_through_public_router() -> None:
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
    from magi.api.routers.personality_config import personality_config_router

    public = _build_public_router(
        personality_config_router,
        _PUBLIC_ROUTE_METHODS["personality_config"],
    )
    methods_by_path = {
        route.path: set(route.methods or set())
        for route in public.routes
    }

    assert methods_by_path["/generation-intents/resolve"] == {"POST"}
    assert methods_by_path["/generation-intents/verify"] == {"POST"}
    assert methods_by_path["/adjust"] == {"POST"}


def test_personality_config_model_rejects_unknown_layer_modifier_keys() -> None:
    from magi.api.routers.personality_config_schemas import PersonalityConfigModel

    with pytest.raises(ValidationError):
        PersonalityConfigModel(
            persona_layers=[
                {
                    "layer_id": "crack",
                    "unlock_condition": {"trust_level_gte": 0.4},
                    "modifiers": {"persona_override": "do not allow"},
                }
            ]
        )


def test_personality_config_model_coerces_supported_layer_modifier_shapes() -> None:
    from magi.api.routers.personality_config_schemas import PersonalityConfigModel

    model = PersonalityConfigModel(
        persona_layers=[
            {
                "layer_id": "crack",
                "unlock_condition": {"trust_level_gte": 0.4},
                "modifiers": {
                    "memory_behavior": "  May reference prior context lightly.  ",
                    "voice_unlocks": "rare direct sincerity\nquiet admission",
                    "humor_delta": "0.25",
                    "trigger_threshold_shifts": {"intimacy": "-0.15", "hostility": "bad"},
                },
            }
        ]
    )

    assert model.persona_layers[0].modifiers.model_dump() == {
        "memory_behavior": "May reference prior context lightly.",
        "voice_unlocks": ["rare direct sincerity", "quiet admission"],
        "humor_delta": 0.25,
        "trigger_threshold_shifts": {"intimacy": -0.15},
    }


def test_normalize_generated_personality_payload_prunes_unknown_layer_modifiers() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload(
        {
            "name": "Layered",
            "persona_layers": [
                {
                    "layer_id": "crack",
                    "unlock_condition": {"trust_level_gte": 0.4},
                    "modifiers": {
                        "voice_unlocks": "rare direct sincerity\nquiet admission",
                        "directness_delta": "+0.2",
                        "persona_override": "legacy",
                    },
                }
            ],
        }
    )

    assert payload["persona_layers"][1]["modifiers"] == {
        "voice_unlocks": ["rare direct sincerity", "quiet admission"],
        "directness_delta": 0.2,
    }
