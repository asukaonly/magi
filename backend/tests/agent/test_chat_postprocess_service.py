from __future__ import annotations

import asyncio
import json
import pytest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from magi.chat import ChatStore
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
from magi.chat.task_agent.postprocess.components import (
    ChatOutcomeWriter,
    ChatRuntimeNotifier,
)
from magi.chat.task_agent.postprocess_service import ChatPostProcessService
from magi.chat.task_agent.session_run_decisions import TurnSupersession
from magi.agent.task_agents.common import (
    AssistantResponsePlan,
    AssistantResponseSegment,
    ExecutionMode,
    ExecutionResult,
    IncomingFactKind,
    UserMessagePayload,
)
from magi.agent.runtime.contracts import FactRecord
from magi.events.events import EventTypes
from magi.personality.interaction_analyzer import (
    DEFAULT_ANALYSIS,
    InteractionAnalysis,
    InteractionObservation,
)
from magi.personality.behavior_evolution import SatisfactionLevel
from magi.personality.emotional_state import EngagementLevel, InteractionOutcome
from magi.runtime_trace.store import RuntimeTraceStore


def _chat_sse_seam(runtime_trace_store: RuntimeTraceStore):
    """P3 Step 5 test helper: the production agent_response delivery seam,
    backed by the REAL ChatSseChannel. ChatSseChannel.deliver appends the
    ``agent_response`` RuntimeNotificationRecord (same payload the legacy
    notifier used to write), so tests that assert on that notification row keep
    working now that the notifier path is gone — the channel is the sole writer.
    """
    from magi.channels.chat_sse_channel import ChatSseChannel
    from magi_plugin_sdk.channels import ChannelTarget

    channel = ChatSseChannel(trace_store=runtime_trace_store)

    async def _seam(context, *, content):
        target = ChannelTarget(
            channel_type="chat_sse",
            external_chat_id="",
            magi_session_id=getattr(context, "session_id", "") or "",
            magi_user_id=getattr(context, "user_id", "") or "",
        )
        return [await channel.deliver(target, content)]

    return _seam


class _FakeToolStateView:
    """Test stand-in for ChatToolStateView; only ``record`` is needed
    because the postprocess service forwards through ``host._tool_state_view.record``."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, history_key: str, record: dict) -> None:
        self.records.append({"history_key": history_key, **record})


class _FakeContextAssembler:
    def __init__(self) -> None:
        self.history: list[dict] = []
        # Step 1 of the ChatHistoryService decomposition moved tool-call
        # tracking into a separate ChatToolStateView. The postprocess
        # service aliases ``context_assembler.tool_state_view`` onto its
        # own ``_tool_state_view`` so the mixin can call
        # ``host._tool_state_view.record(...)`` directly; this fake must
        # expose the same attribute. Tests that previously asserted on
        # ``tool_records`` should look at ``tool_state_view.records``.
        self.tool_state_view = _FakeToolStateView()

    @property
    def tool_records(self) -> list[dict]:
        """Back-compat alias so existing tests that read ``tool_records``
        keep working without per-test edits."""
        return self.tool_state_view.records

    def require_session_id(self, user_id: str, session_id: str | None = None) -> str:
        return session_id or "generated-session"

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def append_user_message(self, history_key: str, user_message: str) -> None:
        self.history.append({"history_key": history_key, "role": "user", "content": user_message})

    def append_assistant_message(self, history_key: str, response_text: str) -> None:
        self.history.append({"history_key": history_key, "role": "assistant", "content": response_text})


class _FakeEventEmitter:
    def __init__(self) -> None:
        self.chat_response_events: list[dict] = []
        self.runtime_events: list[dict] = []

    async def emit_chat_response_event(
        self,
        *,
        user_id: str,
        session_id: str,
        response: str,
        correlation_id: str | None = None,
        turn_id: str | None = None,
        orchestration_id: str | None = None,
        trace_summary: dict | None = None,
        trace_available: bool = False,
    ) -> None:
        self.chat_response_events.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "response": response,
                "correlation_id": correlation_id,
                "turn_id": turn_id,
                "orchestration_id": orchestration_id,
                "trace_summary": trace_summary,
                "trace_available": trace_available,
            }
        )

    async def emit_runtime_event(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
        success: bool = True,
    ) -> None:
        self.runtime_events.append(
            {
                "event_type": event_type,
                "payload": payload,
                "correlation_id": correlation_id,
                "success": success,
            }
        )


class _FakeSensorHub:
    def __init__(self) -> None:
        self.sensor_events = []

    async def push_sensor_event(self, sensor_event) -> None:
        self.sensor_events.append(sensor_event)


class _FakeRuntime:
    def __init__(self) -> None:
        self.sensor_hub = _FakeSensorHub()

    def get_sensor_hub(self):
        return self.sensor_hub


class _RecordingTaskAgentManager:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object]] = []

    async def add_fact_to_agent(self, agent_type, agent_id, fact):  # type: ignore[no-untyped-def]
        self.calls.append((agent_type, agent_id, fact))
        return True


class _FakeIntentDecision:
    def __init__(self) -> None:
        self.intent = "chat"
        self.execution_mode = ExecutionMode.DIRECT_LLM
        self.tools: list[str] = []
        self.task_hint: dict[str, object] = {}
        self.recommended_tools: list[dict[str, object]] = []
        self.reasoning = "direct response"
        self.orchestration_plan = None
        self.ux_plan = type(
            "_UxPlan",
            (),
            {
                "to_dict": staticmethod(
                    lambda: {
                        "assistant_surface_mode": "final_only",
                        "thinking_indicator": "hidden",
                        "trace_display_mode": "none",
                        "allow_trace_collapse": False,
                    }
                )
            },
        )()
        self.llm_trace = {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "input_tokens": 48,
            "output_tokens": 12,
            "total_tokens": 60,
            "reasoning_tokens": 0,
            "thinking_enabled": False,
            "duration_ms": 310,
        }


class _FakeL1Store:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = events

    async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return list(self._events)


class _FakeUnifiedMemory:
    def __init__(self, events: list[dict[str, object]] | None = None, l0=None) -> None:
        self.l0 = l0
        self.l1 = _FakeL1Store(events or [])
        self.l2 = None
        self.l4 = _RecordingL4Store()
        self.task_packets = []

    def memory_operation_epoch(self) -> int:
        return 0

    @asynccontextmanager
    async def memory_operation_guard(self):  # type: ignore[no-untyped-def]
        yield

    async def persist_task_outcome_reflection(self, packet):  # type: ignore[no-untyped-def]
        self.task_packets.append(packet)
        return {"summary_id": "summary-1", "summary_category": "task_reflection"}


class _RecordingPersonalityMemory:
    def __init__(self) -> None:
        self.process_calls: list[dict[str, object]] = []
        self.relationship_signal_calls: list[dict[str, object]] = []

    async def get_core_personality(self):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            milestone_conditions={},
        )

    async def process_turn_outcome(self, **kwargs):  # type: ignore[no-untyped-def]
        self.process_calls.append(dict(kwargs))
        return True

    async def record_observer_relationship_signal(self, **kwargs):  # type: ignore[no-untyped-def]
        self.relationship_signal_calls.append(dict(kwargs))
        return True


class _RecordingL4Store:
    def __init__(self) -> None:
        self.task_preference_calls: list[dict[str, object]] = []

    async def record_task_preference(self, **kwargs):  # type: ignore[no-untyped-def]
        self.task_preference_calls.append(dict(kwargs))
        return "task-pref-1"


class _RecordingL2Store:
    def __init__(self) -> None:
        self.candidates: list[dict[str, object]] = []

    async def upsert_assertion_candidate(self, candidate):  # type: ignore[no-untyped-def]
        self.candidates.append(dict(candidate))
        return "assert-observer"


class _FakeChatProjector:
    def __init__(self) -> None:
        self.assistant_messages: list[dict[str, object]] = []

    async def project_assistant_message(self, **kwargs):  # type: ignore[no-untyped-def]
        self.assistant_messages.append(dict(kwargs))


@pytest.mark.asyncio
async def test_memory_updates_do_not_pass_stp_rules_after_response(monkeypatch) -> None:
    import magi.chat.task_agent.postprocess.memory as postprocess_module

    analysis_calls: list[dict[str, object]] = []

    async def _fake_analyze_interaction(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args
        analysis_calls.append(dict(kwargs))
        return DEFAULT_ANALYSIS

    monkeypatch.setattr(
        postprocess_module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=True,
            deep_persona_enabled=False,
        ),
    )
    monkeypatch.setattr(postprocess_module, "analyze_interaction", _fake_analyze_interaction)
    memory = _RecordingPersonalityMemory()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        memory=memory,
    )

    await service._record_memory_updates(
        user_id="local_user",
        user_message="say something funny",
        response_text="funny response",
        incoming_fact_kind="user_message",
        execution_mode="direct_llm",
        session_id="session-1",
        turn_id="turn-1",
    )

    assert analysis_calls[-1].get("stp_rules") is None
    assert "allow_state_transition" not in memory.process_calls[-1]


@pytest.mark.asyncio
async def test_memory_updates_skip_stp_rules_outside_direct_chat_scope(monkeypatch) -> None:
    import magi.chat.task_agent.postprocess.memory as postprocess_module

    analysis_calls: list[dict[str, object]] = []

    async def _fake_analyze_interaction(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args
        analysis_calls.append(dict(kwargs))
        return DEFAULT_ANALYSIS

    monkeypatch.setattr(
        postprocess_module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=True,
            deep_persona_enabled=False,
        ),
    )
    monkeypatch.setattr(postprocess_module, "analyze_interaction", _fake_analyze_interaction)
    memory = _RecordingPersonalityMemory()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        memory=memory,
    )

    await service._record_memory_updates(
        user_id="local_user",
        user_message="analyze apple stock",
        response_text="analysis report",
        incoming_fact_kind="explore_task_completed",
        execution_mode="explore_task_render",
        session_id="session-1",
        turn_id="turn-1",
    )

    assert analysis_calls[-1].get("stp_rules") is None
    assert "allow_state_transition" not in memory.process_calls[-1]


@pytest.mark.asyncio
async def test_memory_updates_route_observer_candidates(monkeypatch) -> None:
    import magi.chat.task_agent.postprocess.memory as postprocess_module

    async def _fake_analyze_interaction(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        return InteractionAnalysis(
            sentiment=0.4,
            engagement=EngagementLevel.HIGH,
            complexity=0.6,
            outcome=InteractionOutcome.SUCCESS,
            satisfaction=SatisfactionLevel.HIGH,
            memory_observations=[
                InteractionObservation(
                    kind="profile_signal",
                    arguments={
                        "trait_family": "communication_profile",
                        "trait_name": "communication.response_style.preferred",
                        "trait_value": "先说结论，再说风险",
                        "evidence_text": "以后这种方案讨论，先说结论，再说风险。",
                        "confidence": 0.9,
                    },
                ),
                InteractionObservation(
                    kind="persona_relationship_signal",
                    arguments={
                        "signal_type": "milestone",
                        "milestone_key": "seven_guard_down",
                        "evidence_text": "七号这里可以稍微软一点。",
                        "confidence": 0.86,
                    },
                ),
            ],
        )

    monkeypatch.setattr(
        postprocess_module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=True,
            deep_persona_enabled=True,
        ),
    )
    monkeypatch.setattr(postprocess_module, "analyze_interaction", _fake_analyze_interaction)
    memory = _RecordingPersonalityMemory()
    unified_memory = _FakeUnifiedMemory()
    unified_memory.l2 = _RecordingL2Store()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        memory=memory,
        unified_memory=unified_memory,
    )

    await service._record_memory_updates(
        user_id="local_user",
        user_message="以后这种方案讨论，先说结论，再说风险。七号这里可以稍微软一点。",
        response_text="好，我按这个顺序说。",
        incoming_fact_kind="user_message",
        execution_mode="direct_llm",
        session_id="session-1",
        turn_id="turn-1",
        persona_id="seven",
    )

    assert unified_memory.l2.candidates == [
        {
            "entity_id": "user:local_user",
            "entity_type": "user",
            "trait_family": "communication_profile",
            "trait_name": "communication.response_style.preferred",
            "trait_value": "先说结论，再说风险",
            "confidence_score": 0.9,
            "evidence_events": ["turn-1"],
            "volatility_index": 0.25,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "tentative",
            "first_inferred_at": pytest.approx(unified_memory.l2.candidates[0]["first_inferred_at"]),
            "last_validated_at": pytest.approx(unified_memory.l2.candidates[0]["last_validated_at"]),
            "target_entity_id": "",
            "target_entity_type": "",
            "target_scope": "global",
            "temporal_scope": "stable",
            "decay_policy": None,
            "decay_anchor_at": pytest.approx(unified_memory.l2.candidates[0]["decay_anchor_at"]),
            "context_ref_id": "turn-1",
            "expires_at": None,
            "memory_subdomain": "semantic",
            "natural_summary": "以后这种方案讨论，先说结论，再说风险。",
        }
    ]
    assert memory.relationship_signal_calls == [
        {
            "user_id": "local_user",
            "persona_id": "seven",
            "signal_type": "milestone",
            "milestone_key": "seven_guard_down",
            "trust_delta": 0.0,
            "evidence_text": "七号这里可以稍微软一点。",
            "confidence": 0.86,
            "turn_id": "turn-1",
            "session_id": "session-1",
        }
    ]


@pytest.mark.asyncio
async def test_memory_updates_route_task_preferences_to_l4(monkeypatch) -> None:
    import magi.chat.task_agent.postprocess.memory as postprocess_module

    async def _fake_analyze_interaction(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        return InteractionAnalysis(
            sentiment=0.4,
            engagement=EngagementLevel.HIGH,
            complexity=0.6,
            outcome=InteractionOutcome.SUCCESS,
            satisfaction=SatisfactionLevel.HIGH,
            memory_observations=[
                InteractionObservation(
                    kind="task_preference",
                    arguments={
                        "task_category": "coding",
                        "preference": "改代码前先讲完成标准",
                        "polarity": "prefer",
                        "evidence_text": "以后改代码前先讲完成标准。",
                        "confidence": 0.9,
                    },
                )
            ],
        )

    monkeypatch.setattr(
        postprocess_module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=True,
            deep_persona_enabled=True,
        ),
    )
    monkeypatch.setattr(postprocess_module, "analyze_interaction", _fake_analyze_interaction)
    memory = _RecordingPersonalityMemory()
    unified_memory = _FakeUnifiedMemory()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        memory=memory,
        unified_memory=unified_memory,
    )

    await service._record_memory_updates(
        user_id="local_user",
        user_message="以后改代码前先讲完成标准。",
        response_text="好，之后我会先说明完成标准。",
        incoming_fact_kind="user_message",
        execution_mode="direct_llm",
        session_id="session-1",
        turn_id="turn-1",
        persona_id="seven",
    )

    assert unified_memory.l4.task_preference_calls == [
        {
            "user_id": "local_user",
            "persona_id": "seven",
            "task_category": "coding",
            "preference": "改代码前先讲完成标准",
            "polarity": "prefer",
            "evidence_text": "以后改代码前先讲完成标准。",
            "confidence": 0.9,
            "turn_id": "turn-1",
            "session_id": "session-1",
        }
    ]


@pytest.mark.asyncio
async def test_outcome_writer_persists_interim_then_final_messages(chat_store: ChatStore) -> None:
    projector = _FakeChatProjector()
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        chat_projector=projector,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-1",
        message_text="hello",
        created_at_ms=1710000000000,
    )

    await writer.persist_turn_ux_plan(
        turn_id="turn-1",
        execution_mode="direct_llm",
        ux_plan={
            "assistant_surface_mode": "interim_then_final",
            "interim_text": "let me check",
        },
        updated_at_ms=1710000000100,
    )
    await writer.persist_final_chat_outcome(
        turn_id="turn-1",
        orchestration_id=None,
        execution_mode="direct_llm",
        ux_plan={
            "assistant_surface_mode": "interim_then_final",
            "interim_text": "let me check",
        },
        response_text="final answer",
        started_at_ms=1710000000000,
        completed_at_ms=1710000000200,
    )

    notification_message = await writer.get_notification_chat_message(
        turn_id="turn-1",
        ux_plan={"assistant_surface_mode": "interim_then_final"},
    )
    await writer.project_final_chat_message(
        user_id="local_user",
        session_id="session-1",
        final_message=notification_message,
    )

    messages = await chat_store.list_messages(session_id="session-1")
    assert [message.message_kind for message in messages] == [
        "user_text",
        "assistant_interim",
        "assistant_final",
    ]
    assert messages[-1].replaces_message_id == messages[-2].message_id
    assert projector.assistant_messages[0]["message_id"] == messages[-1].message_id


@pytest.mark.asyncio
async def test_outcome_writer_bumps_history_version_for_assistant_final(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        chat_projector=None,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-1",
        message_text="hello",
        created_at_ms=1710000000000,
    )

    before_version = await chat_store.get_history_version("session-1")

    await writer.persist_final_chat_outcome(
        turn_id="turn-1",
        orchestration_id=None,
        execution_mode="direct_llm",
        ux_plan={
            "assistant_surface_mode": "final_only",
        },
        response_text="final answer",
        started_at_ms=1710000000000,
        completed_at_ms=1710000000200,
    )

    after_version = await chat_store.get_history_version("session-1")

    assert before_version == 1
    assert after_version == 2


@pytest.mark.asyncio
async def test_outcome_writer_persists_assistant_attachments(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        chat_projector=None,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-attachments",
        message_text="show me photos",
        created_at_ms=1710000000000,
    )

    await writer.persist_final_chat_outcome(
        turn_id="turn-attachments",
        orchestration_id=None,
        execution_mode="function_calling",
        ux_plan={"assistant_surface_mode": "final_only"},
        response_text="Here are the photos.",
        attachments=[{"attachment_id": "att-1", "kind": "image", "original_name": "photo.jpg"}],
        started_at_ms=1710000000000,
        completed_at_ms=1710000000200,
    )

    messages = await chat_store.list_messages(session_id="session-1")
    payload = json.loads(messages[-1].payload_json)

    assert messages[-1].message_kind == "assistant_final"
    assert payload["attachments"] == [
        {"attachment_id": "att-1", "kind": "image", "original_name": "photo.jpg"}
    ]


@pytest.mark.asyncio
async def test_outcome_writer_persists_assistant_message_payload(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        chat_projector=None,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-asset-refs",
        message_text="show me the candidate assets",
        created_at_ms=1710000000000,
    )

    await writer.persist_final_chat_outcome(
        turn_id="turn-asset-refs",
        orchestration_id=None,
        execution_mode="function_calling",
        ux_plan={"assistant_surface_mode": "final_only"},
        response_text="Here are the candidate assets.",
        attachments=[{"attachment_id": "att-1", "kind": "image", "original_name": "photo.jpg"}],
        message_payload={
            "asset_refs": [
                {"asset_ref_id": "asset-1", "event_id": "evt-1", "original_name": "hangzhou.jpg"}
            ]
        },
        started_at_ms=1710000000000,
        completed_at_ms=1710000000200,
    )

    messages = await chat_store.list_messages(session_id="session-1")
    payload = json.loads(messages[-1].payload_json)

    assert payload["attachments"] == [
        {"attachment_id": "att-1", "kind": "image", "original_name": "photo.jpg"}
    ]
    assert payload["asset_refs"] == [
        {"asset_ref_id": "asset-1", "event_id": "evt-1", "original_name": "hangzhou.jpg"}
    ]


@pytest.mark.asyncio
async def test_outcome_writer_persists_segmented_chat_outcome(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        chat_projector=None,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-rhythm",
        message_text="explain rhythm",
        created_at_ms=1710000000000,
    )

    records = await writer.persist_segmented_chat_outcome(
        turn_id="turn-rhythm",
        orchestration_id=None,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
        response_plan=AssistantResponsePlan(
            mode="multi_message",
            aggregate_text="完整回答",
            segments=[
                AssistantResponseSegment(
                    content="先接住问题。",
                    intent="acknowledge",
                    delay_ms=0,
                    segment_index=0,
                    source_unit_ids=["u1"],
                ),
                AssistantResponseSegment(
                    content="再说明核心答案。",
                    intent="answer",
                    delay_ms=700,
                    segment_index=1,
                    source_unit_ids=["u2"],
                ),
            ],
        ),
        attachments=[
            {
                "attachment_id": "att-1",
                "kind": "image",
                "original_name": "generated.png",
                "mime_type": "image/png",
                "size_bytes": 10,
            }
        ],
        message_payload={
            "asset_refs": [{"asset_ref_id": "asset-1"}],
            "recalled_memories": [
                {
                    "kind": "event",
                    "source_layer": "L1",
                    "statement": "Visited example.com",
                    "topic": "example.com",
                }
            ],
            "recalled_memory_summary": {
                "coverage_kind": "exhaustive",
                "can_claim_total": True,
                "total_count": 12,
            },
        },
        started_at_ms=1710000000000,
        completed_at_ms=1710000000200,
    )

    messages = await chat_store.list_messages(session_id="session-1")
    assert [message.message_kind for message in messages] == [
        "user_text",
        "assistant_rhythm_segment",
        "assistant_rhythm_segment",
    ]
    assert [record.message_id for record in records] == [message.message_id for message in messages[1:]]

    first_payload = json.loads(messages[1].payload_json)
    second_payload = json.loads(messages[2].payload_json)
    assert first_payload["rhythm"] == {
        "segment_index": 0,
        "segment_count": 2,
        "intent": "acknowledge",
        "delay_ms": 0,
        "source_unit_ids": ["u1"],
    }
    assert second_payload["rhythm"]["segment_index"] == 1
    assert first_payload["asset_refs"] == [{"asset_ref_id": "asset-1"}]
    assert "recalled_memories" not in first_payload
    assert "recalled_memory_summary" not in first_payload
    assert second_payload["recalled_memories"][0]["topic"] == "example.com"
    assert second_payload["recalled_memory_summary"]["total_count"] == 12
    assert second_payload["asset_refs"] == [{"asset_ref_id": "asset-1"}]
    assert second_payload["attachments"] == [
        {
            "attachment_id": "att-1",
            "kind": "image",
            "original_name": "generated.png",
            "mime_type": "image/png",
            "size_bytes": 10,
        }
    ]


@pytest.mark.asyncio
async def test_outcome_writer_uses_cumulative_segment_timestamps(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        chat_projector=None,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-rhythm-time",
        message_text="explain rhythm",
        created_at_ms=1710000000000,
    )

    await writer.persist_segmented_chat_outcome(
        turn_id="turn-rhythm-time",
        orchestration_id=None,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
        response_plan=AssistantResponsePlan(
            mode="multi_message",
            aggregate_text="完整回答",
            segments=[
                AssistantResponseSegment(content="第一段", delay_ms=0, segment_index=0, source_unit_ids=["u1"]),
                AssistantResponseSegment(content="第二段", delay_ms=1000, segment_index=1, source_unit_ids=["u2"]),
                AssistantResponseSegment(content="第三段", delay_ms=1500, segment_index=2, source_unit_ids=["u3"]),
            ],
        ),
        started_at_ms=1710000000000,
        completed_at_ms=1710000000200,
    )

    messages = [
        message
        for message in await chat_store.list_messages(session_id="session-1")
        if message.message_kind == "assistant_rhythm_segment"
    ]
    assert [message.created_at_ms for message in messages] == [
        1710000000200,
        1710000001200,
        1710000002700,
    ]


@pytest.mark.asyncio
async def test_handle_worker_result_persists_reply_anchor_to_original_message(
    chat_store: ChatStore,
) -> None:
    original_user_message = await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-a",
        message_text="Please audit the release checklist.",
        created_at_ms=1710000000000,
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-b",
        message_text="Unrelated question while that runs.",
        created_at_ms=1710000001000,
    )

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-a",
            "worker_id": "worker-1",
            "stage": "completed",
            "orchestration_id": "orch-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000002.0,
        correlation_id="worker-corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="Please audit the release checklist.",
        incoming_fact_kind=IncomingFactKind.WORKER_UPDATE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="Please audit the release checklist.",
            turn_id="turn-a",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        response_text="Here is the completed audit.",
        correlation_id="worker-corr-1",
        orchestration_id="orch-1",
        turn_id="turn-a",
    )

    await service.handle(context, result)

    messages = await chat_store.list_messages(session_id="session-1")

    assert [message.turn_id for message in messages] == ["turn-a", "turn-b", "turn-a"]
    assert messages[-1].message_kind == "assistant_final"
    assert messages[-1].reply_to_message_id == original_user_message.message_id


@pytest.mark.asyncio
async def test_runtime_notifier_appends_response_and_trace_notifications(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    notifier = ChatRuntimeNotifier(
        runtime_trace_store=runtime_trace_store,
        chat_read_service_factory=lambda: None,
    )

    # P3 Step 5: the notifier's legacy agent_response writer was removed (the
    # agent_response is now written solely by ChatSseChannel.deliver). The
    # notifier still owns trace_update + execution_control.
    await notifier.emit_trace_update(
        user_id="local_user",
        session_id="session-1",
        turn_id="turn-1",
    )
    await notifier.emit_execution_control(
        user_id="local_user",
        session_id="session-1",
        turn_id="turn-1",
        run_id="run-1",
        orchestration_id="orch-1",
        state="cancelling",
        can_cancel=False,
        label="Cancelling run",
    )

    notifications = await runtime_trace_store.list_notifications(after_id=0)
    assert [notification.channel for notification in notifications] == [
        "trace_update",
        "execution_control",
    ]


@pytest.fixture
async def runtime_trace_store(runtime_paths_with_schema):
    store = RuntimeTraceStore(
        db_path=str(runtime_paths_with_schema.runtime_trace_db_path)
    )
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


@pytest.fixture
async def trace_event_bus(runtime_trace_store):
    """In-process message bus with RuntimeTraceSubscriber wired up.

    Tests that exercise the SpanCompleted -> trace_store projection path
    pass this bus into ChatPostProcessService(event_bus=...).

    The returned object has a ``drain()`` coroutine that flushes pending
    SpanCompleted events into the trace store before assertions.
    """
    from magi.events.in_memory_backend import InMemoryMessageBusBackend
    from magi.runtime_trace.subscribers.runtime_trace_subscriber import (
        RuntimeTraceSubscriber,
    )

    bus = InMemoryMessageBusBackend()
    await bus.start()
    subscriber = RuntimeTraceSubscriber(event_bus=bus, trace_store=runtime_trace_store)
    await subscriber.start()

    async def _drain() -> None:
        # Wait until the bus's internal queue is empty AND the subscriber's
        # in-flight projection tasks finish. Because SpanCompleted handling
        # is two-stage (queue -> handler -> create_task -> store write),
        # we loop until both stabilize.
        for _ in range(50):
            queue = bus._queue
            if queue is not None:
                await queue.join()
            await subscriber.drain()
            if (queue is None or queue.empty()) and not subscriber._inflight:
                return
        raise RuntimeError("trace bus did not drain")

    bus.drain = _drain  # type: ignore[attr-defined]
    try:
        yield bus
    finally:
        await subscriber.stop()
        await bus.stop()


@pytest.fixture
async def chat_store(runtime_paths_with_schema):
    store = ChatStore(
        db_path=str(runtime_paths_with_schema.chat_db_path)
    )
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_record_tool_interaction_preserves_trace_identity() -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )

    await service.record_tool_interaction(
        {
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "orchestration_id": "orch-1",
            "tool_call_id": "call-1",
            "iteration": 3,
            "tool_name": "web-search",
            "arguments": {"query": "Hangzhou news"},
            "execution_time": 0.25,
            "success": True,
            "error": None,
            "error_code": None,
            "data": {"provider": "duckduckgo"},
            "intent": "news_query",
        }
    )

    assert len(event_emitter.runtime_events) == 1
    runtime_payload = event_emitter.runtime_events[0]["payload"]
    assert runtime_payload["turn_id"] == "turn-1"
    assert runtime_payload["tool_call_id"] == "call-1"
    assert runtime_payload["iteration"] == 3


@pytest.mark.asyncio
async def test_record_tool_interaction_projects_memory_query_tactic_into_l0(tmp_path) -> None:
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    l0_store = L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "l0_memory_query_tactics.db"),
        restore_on_restart=False,
    )
    await l0_store.initialize()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        unified_memory=_FakeUnifiedMemory(l0=l0_store),
        max_fact_memory=10,
    )

    await service.record_tool_interaction(
        {
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "tool_call_id": "call-memory-1",
            "iteration": 1,
            "tool_name": "memory_query",
            "arguments": {"query": "我喜欢什么天气"},
            "execution_time": 0.18,
            "success": True,
            "data": {"events": [{"event_id": "evt-1"}]},
            "intent": "preference_recall",
        }
    )

    workbench = await l0_store.get_workbench("session-1")

    assert [tactic["tactic_type"] for tactic in workbench["temporary_tactics"]] == ["memory_query_active"]
    assert workbench["temporary_tactics"][0]["tactic_payload"]["turn_id"] == "turn-1"
    assert workbench["temporary_tactics"][0]["tactic_payload"]["tool_name"] == "memory_query"


@pytest.mark.asyncio
async def test_record_tool_interaction_uses_historical_recall_summary_for_recent_tool_state() -> None:
    context_assembler = _FakeContextAssembler()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=context_assembler,  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )

    await service.record_tool_interaction(
        {
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "tool_name": "memory_query",
            "execution_time": 0.18,
            "success": True,
            "data": {
                "historical_recall": {
                    "summary": "2022年9月2号傍晚在杭州拍了一张照片。",
                    "asset_refs": [{"asset_ref_id": "asset-1", "event_id": "evt-1"}],
                }
            },
            "intent": "episode_recall",
        }
    )

    assert context_assembler.tool_records[0]["result_summary"] == "2022年9月2号傍晚在杭州拍了一张照片。"


@pytest.mark.asyncio
async def test_record_intent_resolution_stops_emitting_runtime_trace_events(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )

    await service.record_intent_resolution(context, _FakeIntentDecision())

    assert event_emitter.runtime_events == []


@pytest.mark.asyncio
async def test_record_intent_resolution_persists_turn_and_intent_trace_rows(
    runtime_trace_store: RuntimeTraceStore,
    trace_event_bus,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
        event_bus=trace_event_bus,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )

    await service.record_intent_resolution(context, _FakeIntentDecision())
    await trace_event_bus.drain()

    turn = await runtime_trace_store.get_turn("turn-1")
    intent_span = await runtime_trace_store.get_span("turn-1:intent_resolution")
    intent_resolution = await runtime_trace_store.get_intent_resolution("turn-1:intent_resolution")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert turn.trace_id == "trace:turn-1"
    assert turn.status == "running"
    assert turn.user_message_preview == "hello"
    assert intent_span is not None
    assert intent_span.parent_span_id == "turn-1:turn"
    assert intent_span.node_type == "intent_resolution"
    assert intent_span.status == "completed"
    assert intent_resolution is not None
    assert intent_resolution.intent == "chat"
    assert intent_resolution.execution_mode == "direct_llm"
    assert json.loads(intent_resolution.selected_tools_json) == {
        "router_tools": [],
        "selected_tools": [],
        "task_hint": {},
        "recommended_tools": [],
        # commit efc3161b (align runtime trace flow) added the optional
        # llm_trace payload to the persisted selected_tools_json so the
        # frontend can render provider/model/token details inline.
        "llm_trace": {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "input_tokens": 48,
            "output_tokens": 12,
            "total_tokens": 60,
            "reasoning_tokens": 0,
            "thinking_enabled": False,
            "duration_ms": 310,
        },
    }
    assert len(notifications) == 1
    assert notifications[0].channel == "turn_ux_plan"
    assert json.loads(notifications[0].payload_json)["ux_plan"]["assistant_surface_mode"] == "final_only"


@pytest.mark.asyncio
async def test_record_tool_selection_updates_structured_intent_trace_payload(
    runtime_trace_store: RuntimeTraceStore,
    trace_event_bus,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
        event_bus=trace_event_bus,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "分析 backend/src/magi/agent 的调用链路",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-tools",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="分析 backend/src/magi/agent 的调用链路",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="分析 backend/src/magi/agent 的调用链路",
            turn_id="turn-tools",
        ),
    )
    decision = _FakeIntentDecision()
    decision.execution_mode = ExecutionMode.FUNCTION_CALLING
    decision.tools = ["file_read", "grep", "glob"]
    decision.task_hint = {
        "task_intent": "trace_implementation",
        "domain": "codebase",
        "operation": "discover",
    }

    await service.record_intent_resolution(context, decision)
    await trace_event_bus.drain()
    await service.record_tool_selection(
        context,
        decision,
        type(
            "_ToolSelection",
            (),
            {
                "tools": ["glob", "grep", "file_read"],
                "task_hint": decision.task_hint,
                "recommended_tools": [{"tool": "glob"}, {"tool": "grep"}],
            },
        )(),
    )
    await trace_event_bus.drain()

    intent_resolution = await runtime_trace_store.get_intent_resolution("turn-tools:intent_resolution")

    assert intent_resolution is not None
    payload = json.loads(intent_resolution.selected_tools_json)
    assert payload["router_tools"] == ["file_read", "grep", "glob"]
    assert payload["selected_tools"] == ["glob", "grep", "file_read"]
    assert payload["task_hint"]["task_intent"] == "trace_implementation"
    assert payload["recommended_tools"][0]["tool"] == "glob"


@pytest.mark.asyncio
async def test_record_intent_resolution_commits_interim_turn_state_before_notification(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-interim",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-interim",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-interim",
        message_text="hello",
        created_at_ms=1710000000000,
    )
    decision = _FakeIntentDecision()
    decision.execution_mode = ExecutionMode.ORCHESTRATION_LAUNCH
    decision.ux_plan = type(
        "_UxPlan",
        (),
        {
            "to_dict": staticmethod(
                lambda: {
                    "assistant_surface_mode": "interim_then_final",
                    "thinking_indicator": "hidden",
                    "trace_display_mode": "collapsible",
                    "allow_trace_collapse": True,
                    "interim_text": "稍等我查一下",
                }
            )
        },
    )()

    seen_kinds_at_notify: list[str] = []
    original_emit = service._emit_turn_ux_plan_notification

    async def _wrapped_emit_turn_ux_plan_notification(**kwargs):  # type: ignore[no-untyped-def]
        messages = await chat_store.list_messages(session_id="session-1")
        seen_kinds_at_notify.extend(message.message_kind for message in messages)
        await original_emit(**kwargs)

    service._emit_turn_ux_plan_notification = _wrapped_emit_turn_ux_plan_notification  # type: ignore[method-assign]

    await service.record_intent_resolution(context, decision)

    turn = await chat_store.get_turn("turn-interim")
    messages = await chat_store.list_messages(session_id="session-1")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert json.loads(turn.ux_plan_json)["assistant_surface_mode"] == "interim_then_final"
    assert "assistant_interim" in seen_kinds_at_notify
    assert [message.message_kind for message in messages] == ["user_text", "assistant_interim"]
    assert messages[-1].content_text == "稍等我查一下"
    payload = json.loads(notifications[0].payload_json)
    assert payload["message_id"] == messages[-1].message_id
    assert payload["message_kind"] == "assistant_interim"


@pytest.mark.asyncio
async def test_record_intent_resolution_commits_reaction_turn_state_before_notification(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "嗯",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-reaction",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="嗯",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="嗯",
            turn_id="turn-reaction",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-reaction",
        message_text="嗯",
        created_at_ms=1710000000000,
    )
    decision = _FakeIntentDecision()
    decision.execution_mode = ExecutionMode.DIRECT_LLM
    decision.ux_plan = type(
        "_UxPlan",
        (),
        {
            "to_dict": staticmethod(
                lambda: {
                    "assistant_surface_mode": "reaction_only",
                    "thinking_indicator": "hidden",
                    "trace_display_mode": "none",
                    "allow_trace_collapse": False,
                    "reaction_style": "acknowledge",
                }
            )
        },
    )()

    await service.record_intent_resolution(context, decision)

    turn = await chat_store.get_turn("turn-reaction")
    messages = await chat_store.list_messages(session_id="session-1")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert json.loads(turn.ux_plan_json)["assistant_surface_mode"] == "reaction_only"
    assert [message.message_kind for message in messages] == ["user_text"]
    assert messages[-1].label is not None
    assert messages[-1].label.to_dict() == {
        "kind": "emoji",
        "text": "👌",
        "applied_by": "assistant",
        "source": "reaction_only",
        "created_at_ms": 1710000000000,
    }
    payload = json.loads(notifications[0].payload_json)
    assert payload["message_id"] is None
    assert payload["message_kind"] is None


@pytest.mark.asyncio
async def test_record_tool_loop_fact_stops_persisting_llm_trace_rows(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )

    await service.record_tool_loop_fact(
        {
            "stage": "llm_requested_tools",
            "iteration": 2,
            "tool_names": ["web-search", "file_read"],
            "tool_count": 2,
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "execution_agent_id": "chat:local_user",
            "llm_trace": {
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 120,
                "output_tokens": 28,
                "total_tokens": 148,
                "thinking_enabled": False,
                "duration_ms": 840,
            },
        }
    )

    llm_span = await runtime_trace_store.get_span("turn-1:llm_call:llm_requested_tools:2")
    llm_call = await runtime_trace_store.get_llm_call("turn-1:llm_call:llm_requested_tools:2")

    assert llm_span is None
    assert llm_call is None


@pytest.mark.asyncio
async def test_record_tool_loop_fact_emits_runtime_events_without_enqueuing_chat_fact() -> None:
    event_emitter = _FakeEventEmitter()
    manager = _RecordingTaskAgentManager()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: manager,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )

    await service.record_tool_loop_fact(
        {
            "stage": "tool_executed",
            "iteration": 1,
            "tool_name": "file_read",
            "tool_call_id": "call-1",
            "success": True,
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        }
    )

    assert manager.calls == []
    assert service._local_fact_memory == []
    assert len(event_emitter.runtime_events) == 1
    assert event_emitter.runtime_events[0]["event_type"] == "CHAT_TOOL_LOOP_STEP"
    assert event_emitter.runtime_events[0]["payload"]["tool_name"] == "file_read"


@pytest.mark.asyncio
async def test_record_tool_loop_fact_projects_replan_tactic_into_l0(tmp_path) -> None:
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    l0_store = L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "l0_replan_tactics.db"),
        restore_on_restart=False,
    )
    await l0_store.initialize()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        unified_memory=_FakeUnifiedMemory(l0=l0_store),
        max_fact_memory=10,
    )

    await service.record_tool_loop_fact(
        {
            "stage": "iteration_all_tools_failed",
            "iteration": 2,
            "replan_allowed": True,
            "consecutive_failed_iterations": 1,
            "tool_names": ["web-search", "file_read"],
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "execution_agent_id": "chat:local_user",
        }
    )

    workbench = await l0_store.get_workbench("session-1")

    assert [tactic["tactic_type"] for tactic in workbench["temporary_tactics"]] == [
        "replan_after_tool_failure"
    ]
    assert workbench["temporary_tactics"][0]["tactic_payload"]["turn_id"] == "turn-1"
    assert workbench["temporary_tactics"][0]["tactic_payload"]["replan_allowed"] is True


@pytest.mark.asyncio
async def test_persist_turn_supersessions_closes_old_trace_and_links_new_trace(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
    trace_event_bus,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        max_fact_memory=10,
        event_bus=trace_event_bus,
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-1",
        message_text="Inspect login flow",
        created_at_ms=1710000000000,
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-2",
        message_text="Switch to checkout flow",
        created_at_ms=1710000001000,
    )
    first_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "Inspect login flow",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    second_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "Switch to checkout flow",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-2",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000001.0,
        correlation_id="corr-2",
    )
    first_context = ChatRuntimeContext(
        latest_fact=first_fact,
        recent_facts=[first_fact],
        batch_facts=[first_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="Inspect login flow",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="Inspect login flow",
            turn_id="turn-1",
        ),
    )
    second_context = ChatRuntimeContext(
        latest_fact=second_fact,
        recent_facts=[second_fact],
        batch_facts=[second_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="Switch to checkout flow",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="Switch to checkout flow",
            turn_id="turn-2",
        ),
    )
    decision = _FakeIntentDecision()
    decision.execution_mode = ExecutionMode.FUNCTION_CALLING

    await service.record_intent_resolution(first_context, decision)
    await service.persist_turn_supersessions(
        superseded_turns=[
            TurnSupersession(turn_id="turn-1", anchor_turn_id="turn-2", reason="interrupt"),
        ],
        updated_at_ms=1710000001000,
    )
    await service.record_intent_resolution(second_context, decision)
    await trace_event_bus.drain()

    first_trace = await runtime_trace_store.get_turn("turn-1")
    second_trace = await runtime_trace_store.get_turn("turn-2")

    assert first_trace is not None
    assert first_trace.status == "interrupted"
    assert first_trace.superseded_by_turn_id == "turn-2"
    assert first_trace.supersession_reason == "interrupted"
    assert second_trace is not None
    assert second_trace.continued_from_turn_id == "turn-1"
    assert second_trace.continued_from_trace_id == "trace:turn-1"


@pytest.mark.asyncio
async def test_handle_does_not_emit_chat_timeline_event(monkeypatch: pytest.MonkeyPatch) -> None:
    event_emitter = _FakeEventEmitter()
    runtime = _FakeRuntime()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=runtime.get_sensor_hub,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "I still like Asuka best.",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="I still like Asuka best.",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="I still like Asuka best.",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="You bring up Asuka a lot.",
        correlation_id="corr-1",
        turn_id="turn-1",
    )

    outcome = await service.handle(context, result)

    assert outcome.emitted is True
    assert len(event_emitter.chat_response_events) == 1
    assert runtime.sensor_hub.sensor_events == []
    assert event_emitter.runtime_events == []


@pytest.mark.asyncio
async def test_handle_stops_emitting_runtime_trace_events_when_llm_trace_exists(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="final answer",
        correlation_id="corr-1",
        turn_id="turn-1",
        llm_trace={
            "provider": "openai",
            "model": "gpt-test",
            "input_tokens": 64,
            "output_tokens": 18,
            "total_tokens": 82,
            "thinking_enabled": False,
            "duration_ms": 920,
        },
        ux_plan={
            "assistant_surface_mode": "final_only",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
        },
    )

    await service.handle(context, result)

    assert event_emitter.runtime_events == []


@pytest.mark.asyncio
async def test_handle_persists_turn_response_and_llm_trace_rows(
    runtime_trace_store: RuntimeTraceStore,
    trace_event_bus,
) -> None:
    event_emitter = _FakeEventEmitter()
    completed_runs: list[tuple[str, str, int]] = []
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        complete_session_run=lambda session_id, run_id, revision: completed_runs.append(
            (session_id, run_id, revision)
        ),
        max_fact_memory=10,
        event_bus=trace_event_bus,
        deliver_final_response=_chat_sse_seam(runtime_trace_store),
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        session_run_id="run-1",
        session_run_revision=0,
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="final answer",
        correlation_id="corr-1",
        turn_id="turn-1",
        llm_trace={
            "provider": "openai",
            "model": "gpt-test",
            "input_tokens": 64,
            "output_tokens": 18,
            "total_tokens": 82,
            "thinking_enabled": False,
            "duration_ms": 920,
        },
        ux_plan={
            "assistant_surface_mode": "final_only",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
        },
    )

    await service.handle(context, result)
    await trace_event_bus.drain()

    turn = await runtime_trace_store.get_turn("turn-1")
    llm_span = await runtime_trace_store.get_span("turn-1:llm_call:direct")
    llm_call = await runtime_trace_store.get_llm_call("turn-1:llm_call:direct")
    response_span = await runtime_trace_store.get_span("turn-1:response_emit")
    root_span = await runtime_trace_store.get_span("turn-1:turn")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert turn.status == "completed"
    assert turn.response_preview == "final answer"
    # D phase 4: chat post-process no longer publishes llm_call SpanCompleted;
    # the canonical publish now comes from provider_bridge on real LLM calls.
    assert llm_span is None
    assert llm_call is None
    assert response_span is not None
    assert response_span.node_type == "response_emit"
    assert root_span is not None
    assert root_span.status == "completed"
    assert len(notifications) == 1
    assert completed_runs == [("session-1", "run-1", 0)]
    payload = json.loads(notifications[0].payload_json)
    assert payload["ux_plan"]["assistant_surface_mode"] == "final_only"


@pytest.mark.asyncio
async def test_handle_commits_final_chat_message_before_notification(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    chat_projector = _FakeChatProjector()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        chat_projector=chat_projector,
        max_fact_memory=10,
        deliver_final_response=_chat_sse_seam(runtime_trace_store),
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-final",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-final",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-final",
        message_text="hello",
        created_at_ms=1710000000000,
        persona_id="persona-seven",
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="final answer",
        correlation_id="corr-1",
        turn_id="turn-final",
        ux_plan={
            "assistant_surface_mode": "final_only",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
        },
    )

    seen_kinds_at_notify: list[str] = []
    original_deliver = service._deliver_agent_response

    async def _wrapped_deliver_agent_response(**kwargs):  # type: ignore[no-untyped-def]
        messages = await chat_store.list_messages(session_id="session-1")
        seen_kinds_at_notify.extend(message.message_kind for message in messages)
        await original_deliver(**kwargs)

    service._deliver_agent_response = _wrapped_deliver_agent_response  # type: ignore[method-assign]

    await service.handle(context, result)

    turn = await chat_store.get_turn("turn-final")
    messages = await chat_store.list_messages(session_id="session-1")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert turn.status == "completed"
    assert "assistant_final" in seen_kinds_at_notify
    assert [message.message_kind for message in messages] == ["user_text", "assistant_final"]
    assert messages[-1].content_text == "final answer"
    assert chat_projector.assistant_messages[0]["message_id"] == messages[-1].message_id
    payload = json.loads(notifications[0].payload_json)
    assert payload["message_id"] == messages[-1].message_id
    assert payload["message_kind"] == "assistant_final"
    assert payload["persona_id"] == "persona-seven"


@pytest.mark.asyncio
async def test_handle_falls_back_to_final_message_when_segment_persistence_fails(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    class _SegmentAppendFailsOnSecond:
        def __init__(self, delegate: ChatStore) -> None:
            self._delegate = delegate
            self.segment_appends = 0

        def __getattr__(self, name: str) -> Any:
            return getattr(self._delegate, name)

        async def append_message(self, record, attachment_payloads=None):  # type: ignore[no-untyped-def]
            if record.message_kind == "assistant_rhythm_segment":
                self.segment_appends += 1
                if self.segment_appends == 2:
                    raise RuntimeError("segment write failed")
            return await self._delegate.append_message(
                record,
                attachment_payloads=attachment_payloads,
            )

    class _StaticRhythmPlanner:
        async def plan(self, **_kwargs):  # type: ignore[no-untyped-def]
            return AssistantResponsePlan(
                mode="multi_message",
                aggregate_text="first part second part",
                segments=[
                    AssistantResponseSegment(content="first part", delay_ms=0, segment_index=0, source_unit_ids=["u1"]),
                    AssistantResponseSegment(content="second part", delay_ms=1000, segment_index=1, source_unit_ids=["u2"]),
                ],
            )

    event_emitter = _FakeEventEmitter()
    flaky_store = _SegmentAppendFailsOnSecond(chat_store)
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=flaky_store,  # type: ignore[arg-type]
        max_fact_memory=10,
        response_rhythm_planner=_StaticRhythmPlanner(),
        deliver_final_response=_chat_sse_seam(runtime_trace_store),
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-fallback",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-fallback",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-fallback",
        message_text="hello",
        created_at_ms=1710000000000,
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="first part second part",
        correlation_id="corr-1",
        turn_id="turn-fallback",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    await service.handle(context, result)

    messages = await chat_store.list_messages(session_id="session-1")
    visible_messages = [message for message in messages if message.is_visible]
    assert [message.message_kind for message in visible_messages] == [
        "user_text",
        "assistant_final",
    ]
    assert visible_messages[-1].content_text == "first part second part"
    hidden_segments = [
        message
        for message in messages
        if message.message_kind == "assistant_rhythm_segment" and not message.is_visible
    ]
    assert len(hidden_segments) == 1


@pytest.mark.asyncio
async def test_handle_strips_sentinel_from_history_and_events() -> None:
    event_emitter = _FakeEventEmitter()
    context_assembler = _FakeContextAssembler()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=context_assembler,  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "tell me something",
            "user_id": "local_user",
            "session_id": "session-sentinel",
            "turn_id": "turn-sentinel",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-sentinel",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-sentinel",
        history_key="local_user::session-sentinel",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="tell me something",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-sentinel",
            content="tell me something",
            turn_id="turn-sentinel",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="alpha‖beta",
        correlation_id="corr-sentinel",
        turn_id="turn-sentinel",
    )

    outcome = await service.handle(context, result)

    assert outcome.emitted is True
    assistant_entries = [entry for entry in context_assembler.history if entry["role"] == "assistant"]
    assert len(assistant_entries) == 1
    assert assistant_entries[0]["content"] == "alpha beta"
    assert "‖" not in event_emitter.chat_response_events[0]["response"]
    assert event_emitter.chat_response_events[0]["response"] == "alpha beta"


@pytest.mark.asyncio
async def test_handle_suppresses_final_response_when_session_run_is_cancelling(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    completed_runs: list[tuple[str, str, int]] = []
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        complete_session_run=lambda session_id, run_id, revision: completed_runs.append(
            (session_id, run_id, revision)
        ),
        resolve_session_run_status=lambda session_id, run_id, revision: "cancelling",
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-cancelled",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-cancelled",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        session_run_id="run-cancelled",
        session_run_revision=0,
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-cancelled",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-cancelled",
        message_text="hello",
        created_at_ms=1710000000000,
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="this should be suppressed",
        correlation_id="corr-cancelled",
        turn_id="turn-cancelled",
        ux_plan={
            "assistant_surface_mode": "final_only",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
        },
    )

    outcome = await service.handle(context, result)

    messages = await chat_store.list_messages(session_id="session-1")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert outcome.emitted is False
    assert [message.message_kind for message in messages] == ["user_text"]
    assert event_emitter.chat_response_events == []
    assert notifications == []
    assert completed_runs == [("session-1", "run-cancelled", 0)]


@pytest.mark.asyncio
async def test_handle_maps_reaction_only_turn_to_user_label(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    chat_projector = _FakeChatProjector()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        chat_projector=chat_projector,
        max_fact_memory=10,
        deliver_final_response=_chat_sse_seam(runtime_trace_store),
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "嗯",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-react-final",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="嗯",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="嗯",
            turn_id="turn-react-final",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-react-final",
        message_text="嗯",
        created_at_ms=1710000000000,
    )
    reaction_decision = _FakeIntentDecision()
    reaction_decision.execution_mode = ExecutionMode.DIRECT_LLM
    reaction_decision.ux_plan = type(
        "_UxPlan",
        (),
        {
            "to_dict": staticmethod(
                lambda: {
                    "assistant_surface_mode": "reaction_only",
                    "thinking_indicator": "hidden",
                    "trace_display_mode": "none",
                    "allow_trace_collapse": False,
                    "reaction_style": "acknowledge",
                }
            )
        },
    )()
    await service.record_intent_resolution(context, reaction_decision)

    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="收到啦",
        correlation_id="corr-1",
        turn_id="turn-react-final",
        ux_plan={
            "assistant_surface_mode": "reaction_only",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
            "reaction_style": "acknowledge",
        },
    )

    await service.handle(context, result)

    turn = await chat_store.get_turn("turn-react-final")
    messages = await chat_store.list_messages(session_id="session-1")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert turn.status == "completed"
    assert [message.message_kind for message in messages] == ["user_text"]
    assert messages[-1].label is not None
    assert messages[-1].label.to_dict() == {
        "kind": "emoji",
        "text": "👌",
        "applied_by": "assistant",
        "source": "reaction_only",
        "created_at_ms": 1710000000000,
    }
    assert chat_projector.assistant_messages == []
    payload = json.loads(notifications[-1].payload_json)
    assert payload["message_kind"] == "assistant_reaction"
    assert payload["content"] == "👌"


@pytest.mark.asyncio
async def test_handle_completes_none_surface_turn_without_final_message(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "嗯",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-none",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-none",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="嗯",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="嗯",
            turn_id="turn-none",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-none",
        message_text="嗯",
        created_at_ms=1710000000000,
    )

    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="",
        skip_emit=True,
        correlation_id="corr-none",
        turn_id="turn-none",
        ux_plan={
            "assistant_surface_mode": "none",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
        },
    )

    await service.handle(context, result)

    turn = await chat_store.get_turn("turn-none")
    messages = await chat_store.list_messages(session_id="session-1")

    assert turn is not None
    assert turn.status == "completed"
    assert [message.message_kind for message in messages] == ["user_text"]


@pytest.mark.asyncio
async def test_handle_completes_reaction_only_turn_without_final_text(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "嗯",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-react-empty",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-react-empty",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="嗯",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="嗯",
            turn_id="turn-react-empty",
        ),
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-react-empty",
        message_text="嗯",
        created_at_ms=1710000000000,
    )
    reaction_decision = _FakeIntentDecision()
    reaction_decision.execution_mode = ExecutionMode.DIRECT_LLM
    reaction_decision.ux_plan = type(
        "_UxPlan",
        (),
        {
            "to_dict": staticmethod(
                lambda: {
                    "assistant_surface_mode": "reaction_only",
                    "thinking_indicator": "hidden",
                    "trace_display_mode": "none",
                    "allow_trace_collapse": False,
                    "reaction_style": "acknowledge",
                }
            )
        },
    )()
    await service.record_intent_resolution(context, reaction_decision)

    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="",
        skip_emit=True,
        correlation_id="corr-react-empty",
        turn_id="turn-react-empty",
        ux_plan={
            "assistant_surface_mode": "reaction_only",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
            "reaction_style": "acknowledge",
        },
    )

    await service.handle(context, result)

    turn = await chat_store.get_turn("turn-react-empty")
    messages = await chat_store.list_messages(session_id="session-1")

    assert turn is not None
    assert turn.status == "completed"
    assert [message.message_kind for message in messages] == ["user_text"]
    assert messages[-1].label is not None
    assert messages[-1].label.to_dict() == {
        "kind": "emoji",
        "text": "👌",
        "applied_by": "assistant",
        "source": "reaction_only",
        "created_at_ms": 1710000000000,
    }


@pytest.mark.asyncio
async def test_handle_records_task_reflection_for_explore_completion() -> None:
    event_emitter = _FakeEventEmitter()
    unified_memory = _FakeUnifiedMemory(
        events=[
            {"event_id": "evt-1"},
            {"event_id": "evt-2"},
        ]
    )
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        unified_memory=unified_memory,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type="EXPLORE_TASK_COMPLETED",
        payload={
            "user_id": "local_user",
            "session_id": "session-1",
            "root_user_message": "Analyze the repository architecture",
            "markdown_dossier": "# Request\nAnalyze the repository architecture",
            "orchestration_id": "orch-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="Analyze the repository architecture",
        incoming_fact_kind=IncomingFactKind.EXPLORE_TASK_COMPLETED,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="Analyze the repository architecture",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.EXPLORE_TASK_RENDER,
        response_text="Here is the final architecture analysis.",
        root_user_message="Analyze the repository architecture",
        correlation_id="corr-1",
        orchestration_id="orch-1",
        turn_id="turn-1",
    )

    outcome = await service.handle(context, result)

    # Memory/reflection updates run as a background task; drain before asserting.
    if service._background_tasks:
        await asyncio.gather(*service._background_tasks)

    assert outcome.emitted is True
    assert outcome.memory_updated is True
    assert len(unified_memory.task_packets) == 1
    packet = unified_memory.task_packets[0]
    assert packet.task_id == "orch-1"
    assert packet.task_kind == "user_goal_task"
    assert packet.user_goal == "Analyze the repository architecture"
    assert packet.result_summary == "Here is the final architecture analysis."
    assert packet.evidence_event_ids == ["evt-1", "evt-2"]


@pytest.mark.asyncio
async def test_handle_does_not_record_task_reflection_for_plain_chat_reply() -> None:
    event_emitter = _FakeEventEmitter()
    unified_memory = _FakeUnifiedMemory(events=[{"event_id": "evt-1"}])
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        unified_memory=unified_memory,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "Hello there",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="Hello there",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="Hello there",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="Hi!",
        correlation_id="corr-1",
        turn_id="turn-1",
    )

    await service.handle(context, result)

    assert unified_memory.task_packets == []


@pytest.mark.asyncio
async def test_handle_emits_execution_control_completed_for_streamed_result(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    """Streamed turns must emit turn_execution_control(completed) so the frontend unlocks the input."""
    class _FakeDisplayMessage:
        def to_dict(self) -> dict[str, object]:
            return {
                "message_id": "msg-streamed",
                "message_kind": "assistant_final",
                "role": "assistant",
                "kind": "assistant",
                "content": "Why did the chicken cross the road?",
                "timestamp": 1710000001,
                "turn_id": "turn-streamed",
                "attachments": [
                    {
                        "attachment_id": "att-streamed",
                        "kind": "image",
                        "original_name": "road.jpg",
                    }
                ],
            }

    class _FakeSessionSummary:
        def to_dict(self) -> dict[str, object]:
            return {
                "session_id": "session-1",
                "title": "New Chat",
                "last_message_preview": "Why did the chicken cross the road?",
                "last_timestamp": 1710000001,
                "message_count": 2,
            }

    class _FakeReadService:
        async def aget_display_message(self, user_id: str, session_id: str, message_id: str):
            _ = (user_id, session_id, message_id)
            return _FakeDisplayMessage()

        async def aget_session_summary(self, user_id: str, session_id: str):
            _ = (user_id, session_id)
            return _FakeSessionSummary()

    action_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        chat_read_service_factory=lambda: _FakeReadService(),
        max_fact_memory=10,
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-streamed",
        message_text="Tell me a joke.",
        created_at_ms=1710000000000,
    )
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "Tell me a joke.",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-streamed",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-stream",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="Tell me a joke.",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="Tell me a joke.",
            turn_id="turn-streamed",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="Why did the chicken cross the road?",
        correlation_id="corr-stream",
        turn_id="turn-streamed",
        streamed=True,
    )

    outcome = await service.handle(context, result)

    assert outcome.emitted is True
    # agent_response notification must NOT be present for streamed turns
    notifications = await runtime_trace_store.list_notifications(after_id=0)
    channels = [n.channel for n in notifications]
    assert "agent_response" not in channels
    assert "chat_message_upserted" in channels
    # execution_control with state=completed must be present
    control_notifs = [n for n in notifications if n.channel == "execution_control"]
    assert len(control_notifs) == 1
    import json as _json
    payload = _json.loads(control_notifs[0].payload_json)
    assert payload["state"] == "completed"
    assert payload["turn_id"] == "turn-streamed"
    upsert_notifs = [n for n in notifications if n.channel == "chat_message_upserted"]
    assert len(upsert_notifs) == 1
    upsert_payload = _json.loads(upsert_notifs[0].payload_json)
    assert upsert_payload["message"]["attachments"] == [
        {"attachment_id": "att-streamed", "kind": "image", "original_name": "road.jpg"}
    ]


@pytest.mark.asyncio
async def test_drain_deferred_turns_callback_invoked_on_finalize() -> None:
    calls: list[str] = []

    async def _drain(session_id: str) -> None:
        calls.append(session_id)

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
        drain_deferred_turns=_drain,
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message=None,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=None,
        active_run=None,
        session_run_id=None,
        session_run_revision=0,
        planner_fact=None,
        planner_fact_kind=IncomingFactKind.USER_MESSAGE,
        planner_payload=None,
        pending_turns=[],
    )

    await service._drain_deferred_user_turns(context)

    assert calls == ["session-1"]


@pytest.mark.asyncio
async def test_drain_deferred_turns_callback_absent_is_noop() -> None:
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message=None,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=None,
        active_run=None,
        session_run_id=None,
        session_run_revision=0,
        planner_fact=None,
        planner_fact_kind=IncomingFactKind.USER_MESSAGE,
        planner_payload=None,
        pending_turns=[],
    )

    # Must not raise; simply returns without calling anything.
    await service._drain_deferred_user_turns(context)


@pytest.mark.asyncio
async def test_drain_deferred_turns_swallows_callback_exception() -> None:
    def _raising(session_id: str) -> None:
        raise RuntimeError("boom")

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
        drain_deferred_turns=_raising,
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message=None,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=None,
        active_run=None,
        session_run_id=None,
        session_run_revision=0,
        planner_fact=None,
        planner_fact_kind=IncomingFactKind.USER_MESSAGE,
        planner_payload=None,
        pending_turns=[],
    )

    # Exception is logged as a warning but not re-raised.
    await service._drain_deferred_user_turns(context)


# ---------------------------------------------------------------------------
# P3 Step 3: non-streamed agent_response converges onto ChatSseChannel.deliver
# via the injected ``deliver_final_response`` seam (rich DeliveryContent).
# ---------------------------------------------------------------------------


def _plain_non_streamed_context_and_result(*, turn_id: str = "turn-1"):
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": turn_id,
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        session_run_id="run-1",
        session_run_revision=0,
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id=turn_id,
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="final answer",
        correlation_id="corr-1",
        turn_id=turn_id,
        ux_plan={
            "assistant_surface_mode": "final_only",
            "thinking_indicator": "hidden",
            "trace_display_mode": "none",
            "allow_trace_collapse": False,
        },
    )
    return context, result


@pytest.mark.asyncio
async def test_handle_routes_plain_non_streamed_agent_response_through_delivery_seam(
    runtime_trace_store: RuntimeTraceStore,
    trace_event_bus,
) -> None:
    """When a ``deliver_final_response`` seam is wired, a plain non-streamed
    turn routes its agent_response through the channel deliver seam carrying
    the FULL payload, and the legacy notifier writes NO agent_response row."""
    seam_calls: list[dict] = []

    async def _fake_seam(context, *, content):
        seam_calls.append({"context": context, "content": content})
        return []

    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
        event_bus=trace_event_bus,
        deliver_final_response=_fake_seam,
    )
    context, result = _plain_non_streamed_context_and_result()

    await service.handle(context, result)
    await trace_event_bus.drain()

    # Seam called exactly once with the full rich DeliveryContent.
    assert len(seam_calls) == 1, seam_calls
    content = seam_calls[0]["content"]
    assert content.text == "final answer"
    assert content.turn_id == "turn-1"
    assert content.ux_plan == result.ux_plan
    # orchestration_id rides along (None here, but the field is populated path).
    assert hasattr(content, "message_id")
    assert hasattr(content, "trace_summary")

    # The legacy notifier must NOT have written an agent_response row.
    notifications = await runtime_trace_store.list_notifications(after_id=0)
    channels = [n.channel for n in notifications]
    assert "agent_response" not in channels, channels


@pytest.mark.asyncio
async def test_handle_writes_no_agent_response_without_delivery_seam(
    runtime_trace_store: RuntimeTraceStore,
    trace_event_bus,
) -> None:
    """P3 Step 5: the legacy notifier agent_response fallback is removed —
    ChatSseChannel.deliver (the seam) is the sole writer. With no seam wired,
    a plain non-streamed turn writes NO agent_response row (and does not crash);
    in production the seam is always wired when chat_sse is registered."""
    event_emitter = _FakeEventEmitter()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
        event_bus=trace_event_bus,
    )
    context, result = _plain_non_streamed_context_and_result()

    await service.handle(context, result)
    await trace_event_bus.drain()

    notifications = await runtime_trace_store.list_notifications(after_id=0)
    channels = [n.channel for n in notifications]
    assert "agent_response" not in channels, channels


@pytest.mark.asyncio
async def test_handle_streamed_does_not_call_delivery_seam(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    """Streamed turns keep their current behavior: no agent_response and no
    seam call — they rely on chunks + chat_message_upserted + execution_control."""
    seam_calls: list[dict] = []

    async def _fake_seam(context, *, content):
        seam_calls.append({"context": context, "content": content})
        return []

    class _FakeDisplayMessage:
        def to_dict(self):
            return {
                "message_id": "msg-streamed",
                "turn_id": "turn-streamed",
                "role": "assistant",
                "content": "Why did the chicken cross the road?",
                "attachments": [],
            }

    class _FakeSessionSummary:
        def to_dict(self):
            return {"session_id": "session-1", "title": "New Chat"}

    class _FakeReadService:
        async def aget_display_message(self, user_id, session_id, message_id):
            return _FakeDisplayMessage()

        async def aget_session_summary(self, user_id, session_id):
            return _FakeSessionSummary()

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        chat_read_service_factory=lambda: _FakeReadService(),
        max_fact_memory=10,
        deliver_final_response=_fake_seam,
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-streamed",
        message_text="Tell me a joke.",
        created_at_ms=1710000000000,
    )
    context, result = _plain_non_streamed_context_and_result(turn_id="turn-streamed")
    result.response_text = "Why did the chicken cross the road?"
    result.streamed = True

    await service.handle(context, result)

    # Streamed turn must NOT call the deliver seam (no agent_response).
    assert seam_calls == []
    notifications = await runtime_trace_store.list_notifications(after_id=0)
    channels = [n.channel for n in notifications]
    assert "agent_response" not in channels, channels
    assert "execution_control" in channels, channels


@pytest.mark.asyncio
async def test_segmented_agent_response_routes_each_segment_through_seam(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    """P3 Step 5: segmented (conversation-rhythm) turns route EACH segment
    through the ChatSseChannel deliver seam (sole writer), not the legacy
    notifier. One seam call per segment, carrying that segment's content +
    message_id; no ``agent_response`` row written via the notifier."""
    from types import SimpleNamespace

    seam_calls: list[Any] = []

    async def _fake_seam(context, *, content):
        seam_calls.append(content)
        return []

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
        deliver_final_response=_fake_seam,
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="explain rhythm",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="part one part two",
        turn_id="turn-seg",
        ux_plan={"assistant_surface_mode": "final_only"},
        attachments=[],
    )
    messages = [
        SimpleNamespace(
            content_text="part one", message_id="m0",
            message_kind="assistant_rhythm_segment", persona_id="p1",
            payload_json=None,
        ),
        SimpleNamespace(
            content_text="part two", message_id="m1",
            message_kind="assistant_rhythm_segment", persona_id="p1",
            payload_json=None,
        ),
    ]
    response_plan = SimpleNamespace(
        segments=[SimpleNamespace(delay_ms=0), SimpleNamespace(delay_ms=0)]
    )

    await service._emit_segmented_agent_response_notifications(
        context=context,
        result=result,
        turn_id="turn-seg",
        response_plan=response_plan,
        messages=messages,
        trace_summary=None,
        trace_available=False,
    )

    # One seam delivery per segment, in order, carrying per-segment identity.
    assert len(seam_calls) == 2
    assert [c.text for c in seam_calls] == ["part one", "part two"]
    assert [c.message_id for c in seam_calls] == ["m0", "m1"]
    assert all(c.turn_id == "turn-seg" for c in seam_calls)
    # No notifier agent_response rows written.
    notifications = await runtime_trace_store.list_notifications(after_id=0)
    assert [n.channel for n in notifications] == []
