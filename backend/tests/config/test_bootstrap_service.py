"""Tests for BootstrapDialogueService."""

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from magi.personality.bootstrap_service import BootstrapDialogueService
from magi.personality.bootstrap_service import BOOTSTRAP_OPENING_LLM_TIMEOUT_SECONDS
from magi.personality.bootstrap_service import BOOTSTRAP_L2_PRIORITY_MAX_WAIT_SECONDS
from magi.personality.bootstrap_service import BOOTSTRAP_L2_PRIORITY_WINDOW_SECONDS
from magi.personality.bootstrap_service import build_bootstrap_l2_priority_metadata
from magi.personality.growth_memory import GrowthMemoryEngine, Milestone, MilestoneType
from magi.personality.loader import PersonalityConfig


def _make_config(*, with_bootstrap: bool = True) -> PersonalityConfig:
    """Create a test personality config."""
    data = {
        "name": "TestBot",
        "identity_core": {
            "identity_statement": "A test persona.",
        },
        "idiolect": {"sentence_style": "Direct and friendly."},
        "bootstrap": {
            "style_instruction": "Be direct and friendly.",
            "opening_line": "First time meeting, so give me your name, how you want me to call you, and one thing you're into.",
            "max_rounds": 2,
        } if with_bootstrap else None,
    }
    if data["bootstrap"] is None:
        del data["bootstrap"]
    return PersonalityConfig.from_dict(data)


class TestBootstrapConfig:
    def test_from_dict_with_bootstrap(self):
        config = _make_config(with_bootstrap=True)
        assert config.bootstrap is not None
        assert config.bootstrap.style_instruction == "Be direct and friendly."
        assert config.bootstrap.opening_line == "First time meeting, so give me your name, how you want me to call you, and one thing you're into."
        assert config.bootstrap.max_rounds == 2

    def test_from_dict_without_bootstrap(self):
        config = _make_config(with_bootstrap=False)
        assert config.bootstrap is None

    def test_from_dict_defaults(self):
        config = PersonalityConfig.from_dict({"bootstrap": {}})
        assert config.bootstrap is not None
        assert config.bootstrap.max_rounds == 3
        assert config.bootstrap.style_instruction == ""


class TestBootstrapNeedsCheck:
    @pytest.mark.asyncio
    async def test_needs_bootstrap_when_no_milestone(self):

        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = []
        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        # All personas need bootstrap now (even without explicit config)
        assert await service.needs_bootstrap("test") is True

    @pytest.mark.asyncio
    async def test_needs_bootstrap_when_opening_not_injected(self):

        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = []

        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        assert await service.needs_bootstrap("test_persona") is True

    @pytest.mark.asyncio
    async def test_no_bootstrap_when_opening_already_injected(self):

        started_milestone = Milestone(
            id="m1",
            type=MilestoneType.BOOTSTRAP_STARTED,
            title="bootstrap_started_test_persona",
            description="started",
            timestamp=1000.0,
            metadata={"persona_name": "test_persona"},
        )
        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = [started_milestone]

        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        assert await service.needs_bootstrap("test_persona") is False

    @pytest.mark.asyncio
    async def test_needs_bootstrap_init_false_when_opening_already_injected(self):

        started_milestone = Milestone(
            id="m2",
            type=MilestoneType.BOOTSTRAP_STARTED,
            title="bootstrap_started_test_persona",
            description="started",
            timestamp=1000.0,
            metadata={"persona_name": "test_persona"},
        )
        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = [started_milestone]

        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        assert await service.needs_bootstrap_init("test_persona") is False

    @pytest.mark.asyncio
    async def test_mark_bootstrap_started_records_started_milestone_once(self):

        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = []

        service = BootstrapDialogueService(growth_engine=growth)

        await service.mark_bootstrap_started(
            persona_name="test_persona",
            persona_id="persona-1",
            user_id="u1",
            session_id="s1",
            turn_id="turn-1",
        )

        growth.record_milestone.assert_awaited_once()
        kwargs = growth.record_milestone.await_args.kwargs
        assert kwargs["milestone_type"] == MilestoneType.BOOTSTRAP_STARTED
        assert kwargs["metadata"]["session_id"] == "s1"


class TestBootstrapOpening:
    @pytest.mark.asyncio
    async def test_get_opening_llm_success(self):

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Hey there, welcome!"
        mock_pool = MagicMock()
        mock_pool.get.return_value = object()

        service = BootstrapDialogueService(
            growth_engine=AsyncMock(),
        )
        with (
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
            patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
            patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        ):
            opening = await service.get_opening("test")
        assert opening == "Hey there, welcome!"
        system_prompt = mock_bridge.chat.await_args.kwargs["system_prompt"]
        assert "guided first-contact opener" in system_prompt
        assert "what to call them" in system_prompt
        assert "one interest/topic they care about" in system_prompt
        assert "Do not claim physical-human experiences" in system_prompt
        assert "Reply in Simplified Chinese (zh-CN)" in system_prompt
        assert "Never mention you are an AI" not in system_prompt
        mock_bridge.chat.assert_awaited_once_with(
            system_prompt=ANY,
            messages=[{"role": "user", "content": "Generate your opening line."}],
            max_tokens=150,
            temperature=0.9,
            disable_thinking=True,
            timeout_seconds=BOOTSTRAP_OPENING_LLM_TIMEOUT_SECONDS,
            event_context=ANY,
        )

    def test_opening_prompt_includes_persona_voice_and_evidence_tiering(self):
        config = PersonalityConfig.from_dict(
            {
                "name": "司辰",
                "identity_core": {
                    "identity_statement": "直球。",
                    "values_loved": ["逻辑密度"],
                    "values_rejected": ["靠资历压人"],
                    "attention_biases": ["先看论证的隐含假设"],
                },
                "idiolect": {
                    "sentence_style": "直接、密度高。",
                    "chattiness": 0.3,
                    "vocab_available": ["问题在于", "证据呢"],
                    "vocab_avoided": ["作为AI"],
                    "structural_quirks": ["不用缓冲句开场"],
                },
                "registers": {
                    "chat": {
                        "description": "日常",
                        "behavior": "直接",
                        "examples": ["[User: 你是不是 AI？]\n司辰: 是。这影响你想问的问题吗？"],
                    }
                },
                "bootstrap": {"style_instruction": "首次接触保持高冷。"},
            }
        )
        service = BootstrapDialogueService(growth_engine=None)
        prompt = service._build_opening_system_prompt(
            config,
            config.bootstrap,
            None,
            activity_snippet="- Source chrome_history:\n  - 浏览 X",
            target_language="Simplified Chinese (zh-CN)",
        )
        # Layer 1: persona fingerprint fields wired into the opening prompt.
        assert "Signature words/phrases you use: 问题在于; 证据呢" in prompt
        assert "Words/phrasings you NEVER use: 作为AI" in prompt
        assert "Speech quirks: 不用缓冲句开场" in prompt
        assert "Verbosity: terse" in prompt
        assert "You care about: 逻辑密度" in prompt
        assert "You push back on: 靠资历压人" in prompt
        assert "What you notice first about someone: 先看论证的隐含假设" in prompt
        # Few-shot voice anchor pulled from the chat register.
        assert "voice anchors" in prompt
        assert "你是不是 AI" in prompt
        # Layer 2: onboarding goals are subordinate to staying in character.
        assert "subordinate to staying in character" in prompt
        # Layer 3B: tiered evidence use with a creepiness self-check.
        assert "Creepiness check" in prompt
        assert "broad, non-sensitive THEME" in prompt

    @pytest.mark.asyncio
    async def test_get_opening_llm_fails_uses_static_fallback(self):

        service = BootstrapDialogueService(
            growth_engine=AsyncMock(),
        )
        # No LLM pool available → falls back to static opening_line
        with patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)):
            opening = await service.get_opening("test")
        assert opening == "First time meeting, so give me your name, how you want me to call you, and one thing you're into."

    @pytest.mark.asyncio
    async def test_get_opening_no_config_synthesizes_and_falls_back(self):

        service = BootstrapDialogueService(
            growth_engine=AsyncMock(),
        )
        # No bootstrap config → synthesized config has empty opening_line → returns None
        with patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=False)):
            opening = await service.get_opening("test")
        assert opening is None


class TestBootstrapReply:
    @pytest.mark.asyncio
    async def test_reply_calls_llm(self):

        growth = AsyncMock(spec=GrowthMemoryEngine)
        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Nice to meet you, Alice!"

        mock_pool = MagicMock()
        mock_pool.get.return_value = object()

        with (
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
            patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
            patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        ):
            reply = await service.reply(
                persona_name="test",
                user_id="u1",
                session_id="s1",
                user_message="I'm Alice",
                history=[],
            )

        assert reply == "Nice to meet you, Alice!"
        mock_bridge.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_round_one_prompt_prioritizes_name_and_forms_of_address(self):

        growth = AsyncMock(spec=GrowthMemoryEngine)
        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Nice to meet you."
        mock_pool = MagicMock()
        mock_pool.get.return_value = object()

        with (
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
            patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
            patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        ):
            await service.reply(
                persona_name="test",
                user_id="u1",
                session_id="s1",
                user_message="Hi",
                history=[],
            )

        system_prompt = mock_bridge.chat.await_args.kwargs["system_prompt"]
        assert "Prioritize learning the user's name and how they like to be addressed" in system_prompt
        assert "Do not claim physical-human experiences" in system_prompt
        assert "Never mention you are an AI" not in system_prompt

    @pytest.mark.asyncio
    async def test_final_round_does_not_record_bootstrap_completion(self):

        growth = AsyncMock(spec=GrowthMemoryEngine)
        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Got it!"

        mock_pool = MagicMock()
        mock_pool.get.return_value = object()

        # Round 2 (final, because max_rounds=2): history has 1 user message already
        history = [
            {"role": "assistant", "content": "Hey!"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "What do you do?"},
        ]

        with (
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
            patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
            patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        ):
            await service.reply(
                persona_name="my_persona",
                user_id="u1",
                session_id="s1",
                user_message="I'm a developer",
                history=history,
            )

        growth.record_milestone.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_round_does_not_run_bootstrap_specific_l2_extraction(self):

        growth = AsyncMock(spec=GrowthMemoryEngine)
        l2_store = AsyncMock()
        service = BootstrapDialogueService(
            growth_engine=growth,
            l2_store=l2_store,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Got it!"

        mock_pool = MagicMock()
        mock_pool.get.return_value = object()

        history = [
            {"role": "assistant", "content": "Hey!"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "What do you do?"},
        ]

        with (
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
            patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
            patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        ):
            await service.reply(
                persona_name="my_persona",
                user_id="u1",
                session_id="s1",
                user_message="I'm a developer",
                history=history,
            )

        mock_bridge.chat.assert_awaited_once()
        l2_store.upsert_entity_facet.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_final_round_no_milestone(self):
        """Non-final round should not record milestone."""

        growth = AsyncMock(spec=GrowthMemoryEngine)
        service = BootstrapDialogueService(
            growth_engine=growth,
        )

        mock_bridge = AsyncMock()
        mock_bridge.chat.return_value = "Tell me more!"
        mock_pool = MagicMock()
        mock_pool.get.return_value = object()

        with (
            patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
            patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
            patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        ):
            await service.reply(
                persona_name="test",
                user_id="u1",
                session_id="s1",
                user_message="Hi",
                history=[],  # Round 1 of 2 — not final
            )

        growth.record_milestone.assert_not_called()


class TestBootstrapL2PriorityMetadata:
    @pytest.mark.asyncio
    async def test_returns_fast_flush_metadata_after_recent_opening(self):

        started_milestone = Milestone(
            id="m1",
            type=MilestoneType.BOOTSTRAP_STARTED,
            title="bootstrap_started_test",
            description="started",
            timestamp=2000.0,
            metadata={"persona_name": "test", "persona_id": "persona-1", "user_id": "u1", "session_id": "s1"},
        )

        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = [started_milestone]

        with (
            patch(
                "magi.personality.bootstrap_service.get_shared_growth_engine",
                new_callable=AsyncMock,
                return_value=growth,
            ),
            patch("magi.personality.bootstrap_service.time.time", return_value=2001.0),
        ):
            metadata = await build_bootstrap_l2_priority_metadata(
                user_id="u1",
                session_id="s1",
                persona_name="test",
                persona_id="persona-1",
            )

        assert metadata == {
            "l2_batch_owner": "bootstrap:u1:persona-1",
            "l2_batch_max_events": 1,
            "l2_batch_min_ready_events": 1,
            "l2_batch_max_wait_seconds": BOOTSTRAP_L2_PRIORITY_MAX_WAIT_SECONDS,
        }

    @pytest.mark.asyncio
    async def test_returns_empty_metadata_without_recent_matching_opening(self):

        started_milestone = Milestone(
            id="m1",
            type=MilestoneType.BOOTSTRAP_STARTED,
            title="bootstrap_started_test",
            description="started",
            timestamp=1000.0,
            metadata={"persona_name": "test", "persona_id": "persona-1", "user_id": "u1", "session_id": "s1"},
        )
        growth = AsyncMock(spec=GrowthMemoryEngine)
        growth.get_milestones.return_value = [started_milestone]

        with (
            patch(
                "magi.personality.bootstrap_service.get_shared_growth_engine",
                new_callable=AsyncMock,
                return_value=growth,
            ),
            patch(
                "magi.personality.bootstrap_service.time.time",
                return_value=1000.0 + BOOTSTRAP_L2_PRIORITY_WINDOW_SECONDS + 1,
            ),
        ):
            metadata = await build_bootstrap_l2_priority_metadata(
                user_id="u1",
                session_id="s1",
                persona_name="test",
                persona_id="persona-1",
            )

        assert metadata == {}


def test_build_opening_system_prompt_includes_activity_snippet():
    from magi.personality.bootstrap_service import BootstrapDialogueService
    from magi.personality.loader import BootstrapConfig, PersonalityConfig
    svc = BootstrapDialogueService(growth_engine=None)
    cfg = PersonalityConfig()
    bs = BootstrapConfig(style_instruction="warm", opening_line="", max_rounds=3)
    with_snip = svc._build_opening_system_prompt(
        cfg,
        bs,
        None,
        activity_snippet="今天看了关于 X 的网页",
        target_language="Simplified Chinese (zh-CN)",
    )
    without = svc._build_opening_system_prompt(
        cfg,
        bs,
        None,
        target_language="Simplified Chinese (zh-CN)",
    )
    assert "今天看了关于 X 的网页" in with_snip
    assert "How to use it (tiered" in with_snip
    assert "ignore it completely" in with_snip
    assert "MUST include" not in with_snip
    assert "Reply in Simplified Chinese (zh-CN)" in with_snip
    assert "今天看了关于 X 的网页" not in without
    assert "How to use it (tiered" not in without
    assert "Reply in Simplified Chinese (zh-CN)" in without
    # Both still invite the user to share what to call them (persona-gated, optional).
    assert "what to call them" in without


def test_build_opening_system_prompt_includes_governed_portrait_context():
    from magi.personality.bootstrap_service import BootstrapDialogueService
    from magi.personality.loader import BootstrapConfig, PersonalityConfig

    svc = BootstrapDialogueService(growth_engine=None)
    cfg = PersonalityConfig()
    bs = BootstrapConfig(style_instruction="warm", opening_line="", max_rounds=3)
    with_snip = svc._build_opening_system_prompt(
        cfg,
        bs,
        "- 用户关注或偏好：DIIV。\n- 近期线索：正在推进 Magi；不要直接当成长期结论。",
        target_language="Simplified Chinese (zh-CN)",
    )
    without = svc._build_opening_system_prompt(
        cfg,
        bs,
        None,
        target_language="Simplified Chinese (zh-CN)",
    )

    assert "# Existing user understanding" in with_snip
    assert "用户关注或偏好：DIIV" in with_snip
    assert "Treat anything labeled as recent context as tentative" in with_snip
    assert "ignore it completely" in with_snip
    assert "MUST include" not in with_snip
    assert "Reply in Simplified Chinese (zh-CN)" in with_snip
    assert "用户关注或偏好：DIIV" not in without
    assert "# Existing user understanding" not in without
    assert "Reply in Simplified Chinese (zh-CN)" in without
    assert "what to call them" in without


@pytest.mark.asyncio
async def test_fetch_bootstrap_memory_snippet_reads_governed_portrait(monkeypatch):
    import magi.memory.provider as memory_provider
    import magi.api.routers.personality_config_common as mod

    memory = object()
    requested_user_ids: list[str] = []

    class FakeProfileService:
        def __init__(self, *, unified_memory):
            assert unified_memory is memory

        async def get_portrait_prompt_summary(self, user_id: str):
            requested_user_ids.append(user_id)
            return [
                "用户关注或偏好：DIIV。",
                "近期线索：正在推进 Magi；不要直接当成长期结论。",
            ]

    monkeypatch.setattr(memory_provider, "get_unified_memory", lambda: memory)
    monkeypatch.setattr(
        "magi.context.user_profile_service.UserProfileService",
        FakeProfileService,
    )

    snippet = await mod._fetch_bootstrap_memory_snippet()

    assert requested_user_ids == ["local_user"]
    assert snippet == (
        "- 用户关注或偏好：DIIV。\n"
        "- 近期线索：正在推进 Magi；不要直接当成长期结论。"
    )


@pytest.mark.asyncio
async def test_fetch_bootstrap_memory_snippet_returns_none_without_portrait(monkeypatch):
    import magi.memory.provider as memory_provider
    import magi.api.routers.personality_config_common as mod

    class FakeProfileService:
        def __init__(self, *, unified_memory):
            _ = unified_memory

        async def get_portrait_prompt_summary(self, user_id: str):
            _ = user_id
            return []

    monkeypatch.setattr(memory_provider, "get_unified_memory", object)
    monkeypatch.setattr(
        "magi.context.user_profile_service.UserProfileService",
        FakeProfileService,
    )

    assert await mod._fetch_bootstrap_memory_snippet() is None


@pytest.mark.asyncio
async def test_get_opening_uses_governed_portrait_context(monkeypatch):
    import magi.personality.bootstrap_service as mod

    mock_bridge = AsyncMock()
    mock_bridge.chat.return_value = "opening"
    mock_pool = MagicMock()
    mock_pool.get.return_value = object()
    memory_snippet_provider = AsyncMock(
        return_value=(
            "- 用户关注或偏好：DIIV。\n"
            "- 近期线索：正在推进 Magi；不要直接当成长期结论。"
        )
    )
    activity_fetch = AsyncMock(return_value="raw browser sample")
    monkeypatch.setattr(mod, "_fetch_recent_activity_snippet", activity_fetch)

    svc = mod.BootstrapDialogueService(
        growth_engine=None,
        memory_snippet_provider=memory_snippet_provider,
    )
    with (
        patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
        patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
        patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
    ):
        assert await svc.get_opening("test") == "opening"

    activity_fetch.assert_not_awaited()
    system_prompt = mock_bridge.chat.await_args.kwargs["system_prompt"]
    assert "# Existing user understanding" in system_prompt
    assert "用户关注或偏好：DIIV" in system_prompt
    assert "近期线索：正在推进 Magi" in system_prompt
    assert "raw browser sample" not in system_prompt
    assert "Creepiness check" in system_prompt


@pytest.mark.asyncio
async def test_get_opening_prefers_recent_l1_activity_samples_from_each_source(monkeypatch):
    import magi.personality.bootstrap_service as mod

    now = 1_710_000_000.0

    class FakeL1:
        async def query_events(self, *, source_filters, limit, order_by, start_time=None, **_kwargs):
            assert order_by == "timestamp_desc"
            assert start_time == now - mod.BOOTSTRAP_IMPORT_SAMPLE_WINDOW_SECONDS
            source = source_filters[0]
            rows = {
                "chrome_history": [
                    {
                        "source": "chrome_history",
                        "content": "Chrome title: React animation notes https://example.test/path?token=secret",
                        "timestamp": now - 10.0,
                        "created_at": now - 5.0,
                        "memory_domain": "external_activity",
                    },
                    {
                        "source": "chrome_history",
                        "content": "Chrome title: LLM prompt caching article",
                        "timestamp": now - 20.0,
                        "created_at": now - 10.0,
                        "memory_domain": "external_activity",
                    },
                ],
                "git_activity": [
                    {
                        "source": "git_activity",
                        "content": "Commit in magi: improve onboarding plugin flow",
                        "timestamp": now - 30.0,
                        "created_at": now - 15.0,
                        "memory_domain": "external_activity",
                    }
                ],
            }
            return rows.get(source, [])[:limit]

        async def summarize_event_sources(self, **_kwargs):
            return [
                {"source": "chrome_history", "event_count": 1200},
                {"source": "git_activity", "event_count": 80},
            ]

    class FakeMemory:
        l1 = FakeL1()

        async def generate_source_activity_summary(self, **_kwargs):
            raise AssertionError("recent 24h summary should be fallback after L1 import samples")

    mock_bridge = AsyncMock()
    mock_bridge.chat.return_value = "opening"
    mock_pool = MagicMock()
    mock_pool.get.return_value = object()
    import magi.memory.provider as memory_provider

    monkeypatch.setattr(memory_provider, "get_unified_memory", lambda: FakeMemory())
    monkeypatch.setattr(mod.time, "time", lambda: now)
    svc = mod.BootstrapDialogueService(growth_engine=None)
    with (
        patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
        patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
        patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
    ):
        assert await svc.get_opening("test") == "opening"

    system_prompt = mock_bridge.chat.await_args.kwargs["system_prompt"]
    assert "Optional user-authorized activity evidence" in system_prompt
    assert "Recently imported user data" not in system_prompt
    assert "chrome_history" in system_prompt
    assert "git_activity" in system_prompt
    assert "React animation notes" in system_prompt
    assert "improve onboarding plugin flow" in system_prompt
    assert "token=secret" not in system_prompt
    assert "MUST include" not in system_prompt
    assert "Creepiness check" in system_prompt
    assert "broad, non-sensitive THEME" in system_prompt


@pytest.mark.asyncio
async def test_recent_l1_import_samples_include_user_authored_plugin_sources(monkeypatch):
    import magi.personality.bootstrap_service as mod

    now = 1_710_000_000.0

    class FakeL1:
        async def query_events(
            self,
            *,
            source_filters,
            limit,
            order_by,
            start_time=None,
            memory_domain=None,
            **_kwargs,
        ):
            assert order_by == "timestamp_desc"
            assert start_time == now - mod.BOOTSTRAP_IMPORT_SAMPLE_WINDOW_SECONDS
            source = source_filters[0]
            rows = {
                "chrome_history": [
                    {
                        "source": "chrome_history",
                        "content": f"Chrome 浏览 long context sample {idx}",
                        "timestamp": now - idx,
                        "created_at": now - idx,
                    }
                    for idx in range(1, 6)
                ],
                "claude_code_agent_history": [
                    {
                        "source": "claude_code_agent_history",
                        "content": "Claude Code 对话 Magi onboarding context design",
                        "timestamp": now - 1.0,
                        "created_at": now - 1.0,
                    }
                ],
            }
            if source == "claude_code_agent_history" and memory_domain == "external_activity":
                return []
            return rows.get(source, [])[:limit]

        async def summarize_event_sources(self, **_kwargs):
            return [
                {"source": "chrome_history", "event_count": 122},
                {"source": "claude_code_agent_history", "event_count": 35},
            ]

    monkeypatch.setattr(mod.time, "time", lambda: now)

    snippet = await mod._fetch_recent_import_activity_snippet(type("M", (), {"l1": FakeL1()})())

    assert snippet is not None
    assert "claude_code_agent_history" in snippet
    assert "Magi onboarding context design" in snippet
    assert "long context sample 5" in snippet


@pytest.mark.asyncio
async def test_get_opening_uses_current_user_language_for_output(monkeypatch):
    from magi import i18n as core_i18n
    import magi.personality.bootstrap_service as mod

    mock_bridge = AsyncMock()
    mock_bridge.chat.return_value = "opening"
    mock_pool = MagicMock()
    mock_pool.get.return_value = object()

    monkeypatch.setattr(mod, "_fetch_recent_activity_snippet", AsyncMock(return_value=None))
    service = BootstrapDialogueService(growth_engine=AsyncMock())

    with (
        patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
        patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
        patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        core_i18n.language_context("en"),
    ):
        await service.get_opening("test")

    system_prompt = mock_bridge.chat.await_args.kwargs["system_prompt"]
    assert "Reply in English" in system_prompt


@pytest.mark.asyncio
async def test_recent_l1_import_samples_skip_low_signal_private_browser_entries(monkeypatch):
    import magi.personality.bootstrap_service as mod

    now = 1_710_000_000.0

    class FakeL1:
        async def query_events(self, *, source_filters, limit, order_by, start_time=None, **_kwargs):
            assert order_by == "timestamp_desc"
            assert start_time == now - mod.BOOTSTRAP_IMPORT_SAMPLE_WINDOW_SECONDS
            return [
                {
                    "source": source_filters[0],
                    "content": "Chrome 浏览 收件箱 (3) - user@example.com - Gmail",
                    "timestamp": now - 1.0,
                    "created_at": now - 1.0,
                },
                {
                    "source": source_filters[0],
                    "content": "Chrome 浏览 用户登录_2DFan",
                    "timestamp": now - 2.0,
                    "created_at": now - 2.0,
                },
                {
                    "source": source_filters[0],
                    "content": "Chrome 浏览 注册新用户_2DFan",
                    "timestamp": now - 3.0,
                    "created_at": now - 3.0,
                },
                {
                    "source": source_filters[0],
                    "content": "Chrome 浏览 Ever17 -the out of infinity-_时空轮回_2DFan",
                    "timestamp": now - 4.0,
                    "created_at": now - 4.0,
                },
                {
                    "source": source_filters[0],
                    "content": "Chrome 浏览 游戏条目搜索：ever17_2DFan",
                    "timestamp": now - 5.0,
                    "created_at": now - 5.0,
                },
            ][:limit]

        async def summarize_event_sources(self, **_kwargs):
            return [{"source": "chrome_history", "event_count": 110}]

    monkeypatch.setattr(mod.time, "time", lambda: now)

    snippet = await mod._fetch_recent_import_activity_snippet(type("M", (), {"l1": FakeL1()})())

    assert snippet is not None
    assert "Ever17" in snippet
    assert "游戏条目搜索" in snippet
    assert "Gmail" not in snippet
    assert "user@example.com" not in snippet
    assert "用户登录" not in snippet
    assert "注册新用户" not in snippet


@pytest.mark.asyncio
async def test_recent_l1_import_samples_ignore_old_events_imported_recently(monkeypatch):
    import magi.personality.bootstrap_service as mod

    now = 1_710_000_000.0

    class FakeL1:
        async def query_events(self, *, source_filters, limit, order_by, start_time=None, **_kwargs):
            assert order_by in {"timestamp_desc", "created_at_desc"}
            if order_by == "timestamp_desc":
                assert start_time == now - mod.BOOTSTRAP_IMPORT_SAMPLE_WINDOW_SECONDS
            else:
                assert start_time is None
            source = source_filters[0]
            rows = {
                "photo_library_apple_photos": [
                    {
                        "source": "photo_library_apple_photos",
                        "content": "照片 拍摄 2022-11-22 在 Hangzhou 拍摄了 1 张照片",
                        "timestamp": now - (365 * 24 * 60 * 60),
                        "created_at": now - 1.0,
                    }
                ],
                "chrome_history": [
                    {
                        "source": "chrome_history",
                        "content": "Chrome 浏览 Local LLM notes",
                        "timestamp": now - 2.0,
                        "created_at": now - 2.0,
                    }
                ],
            }
            return rows.get(source, [])[:limit]

        async def summarize_event_sources(self, **_kwargs):
            return [
                {"source": "photo_library_apple_photos", "event_count": 20},
                {"source": "chrome_history", "event_count": 5},
            ]

    monkeypatch.setattr(mod.time, "time", lambda: now)

    snippet = await mod._fetch_recent_import_activity_snippet(type("M", (), {"l1": FakeL1()})())

    assert snippet is not None
    assert "chrome_history" in snippet
    assert "Local LLM notes" in snippet
    assert "photo_library_apple_photos" not in snippet
    assert "2022-11-22" not in snippet


@pytest.mark.asyncio
async def test_get_opening_does_not_log_private_context(monkeypatch):
    import magi.personality.bootstrap_service as mod

    mock_bridge = AsyncMock()
    mock_bridge.chat.return_value = "opening"
    mock_pool = MagicMock()
    mock_pool.get.return_value = object()
    service = BootstrapDialogueService(growth_engine=AsyncMock())

    with (
        patch("magi.personality.bootstrap_service.resolve_persona_config", new_callable=AsyncMock, return_value=_make_config(with_bootstrap=True)),
        patch("magi.personality.bootstrap_service.get_scenario_llm_pool", return_value=mock_pool),
        patch("magi.personality.bootstrap_service.LLMProviderBridge", return_value=mock_bridge),
        patch.object(mod.logger, "info") as log_info,
    ):
        await service._generate_opening_via_llm(
            _make_config(with_bootstrap=True),
            _make_config(with_bootstrap=True).bootstrap,
            None,
            activity_snippet="Chrome 浏览 Ever17 -the out of infinity-_2DFan",
            target_language="Simplified Chinese (zh-CN)",
        )

    assert any(
        call.args
        and "Bootstrap opening prompt ready" in str(call.args[0])
        for call in log_info.call_args_list
    )
    assert "Chrome 浏览 Ever17" not in str(log_info.call_args_list)


@pytest.mark.asyncio
async def test_get_opening_survives_snippet_fetch_failure(monkeypatch):
    import magi.personality.bootstrap_service as mod
    # snippet fetch raises -> get_opening must still return (fallback opener path)
    async def boom():
        raise RuntimeError("memory down")
    svc = mod.BootstrapDialogueService(
        growth_engine=None,
        memory_snippet_provider=boom,
    )
    monkeypatch.setattr(mod, "_fetch_recent_activity_snippet", boom)
    # LLM pool unavailable -> falls back to static opening_line (None here) without raising
    result = await svc.get_opening("Echo-01")
    assert result is None or isinstance(result, str)
