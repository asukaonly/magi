from __future__ import annotations

import asyncio
import json
import time
import pytest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from magi.chat import ChatMessageRecord, ChatStore
from magi.core.chat_assets.io import write_managed_chat_asset_atomically
from magi.core.chat_assets.mutations import run_chat_asset_mutation
from magi.chat.contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_TERMINAL,
)
from magi.chat.rhythm_completion import (
    MAX_RHYTHM_SEGMENT_COUNT,
    complete_visible_rhythm_segments,
)
from magi.delivery.contracts import DeliveryFanoutResult
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
from magi.chat.task_agent.postprocess.components import (
    ChatOutcomeWriter,
    ChatRuntimeNotifier,
)
from magi.chat.task_agent.postprocess_service import ChatPostProcessService
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.chat.task_agent.session_run_decisions import TurnSupersession
from magi.agent.task_agents.common import (
    AssistantResponsePlan,
    AssistantResponseSegment,
    ExecutionMode,
    ExecutionResult,
    IncomingFactKind,
    ToolSelection,
    UserMessagePayload,
)
from magi.agent.runtime.contracts import FactRecord
from magi.agent.post_turn_understanding import (
    AcceptedConversationOutcome,
    PostTurnUnderstandingService,
)
from magi.events.events import EventTypes
from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.l0.attention_update_scheduler import AcceptedL0AttentionTurn
from magi.personality.interaction_analyzer import (
    DEFAULT_ANALYSIS,
    InteractionAnalysis,
    InteractionObservation,
)
from magi.personality.interaction_batch_analyzer import BatchInteractionAnalysis
from magi.personality.behavior_evolution import SatisfactionLevel
from magi.personality.emotional_state import EngagementLevel, InteractionOutcome
from magi.runtime_trace.store import RuntimeTraceStore


async def _managed_test_attachment(
    chat_store: ChatStore,
    *,
    session_id: str,
    turn_id: str,
    attachment_id: str,
    original_name: str,
    content: bytes,
    include_mime_and_size: bool = False,
) -> dict[str, object]:
    target_path = (
        chat_store._runtime_paths.chat_images_dir
        / session_id
        / turn_id
        / f"{attachment_id}__{original_name}"
    )

    def write_attachment() -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        write_managed_chat_asset_atomically(target_path, content)

    await run_chat_asset_mutation(write_attachment)
    payload: dict[str, object] = {
        "attachment_id": attachment_id,
        "kind": "image",
        "original_name": original_name,
        "storage_path": str(target_path),
        "session_id": session_id,
        "turn_id": turn_id,
    }
    if include_mime_and_size:
        payload["mime_type"] = "image/png"
        payload["size_bytes"] = len(content)
    return payload


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
        receipt = await channel.deliver(target, content)
        return DeliveryFanoutResult(receipts=(receipt,))

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


async def _create_admitted_user_turn(
    chat_store: ChatStore,
    *,
    turn_id: str,
    message_text: str = "hello",
    command_id: int = 101,
    run_disposition: str | None = None,
) -> None:
    """Create one durable user turn whose current attempt is admitted."""

    await chat_store.create_user_turn_once(
        session_id="session-1",
        user_id="local_user",
        turn_id=turn_id,
        message_text=message_text,
        created_at_ms=1710000000000,
        run_disposition=run_disposition,
        runtime_envelope={
            "source": "api",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": turn_id,
            "message": message_text,
            "attachments": [],
            "workspace_path": None,
            "interaction_kind": None,
            "metadata": {},
            "runtime_namespace": "desktop",
        },
        request_fingerprint=f"fingerprint:{turn_id}",
    )
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id=turn_id,
        delivery_attempt_no=0,
        command_id=command_id,
        updated_at_ms=1710000000001,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id=turn_id,
        delivery_attempt_no=0,
        command_id=command_id,
        updated_at_ms=1710000000002,
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
        self.execution_mode = None
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
    def __init__(
        self,
        events: list[dict[str, object]] | None = None,
        l0=None,
        *,
        epoch: int = 0,
        attention_turn_threshold: int = 3,
    ) -> None:
        self.l0 = l0
        self.l1 = _FakeL1Store(events or [])
        self.l2 = None
        self.l4 = _RecordingL4Store()
        self.task_packets = []
        self._epoch = epoch
        self._memory_config_getter = lambda: SimpleNamespace(
            l0=SimpleNamespace(
                attention_update_turn_threshold=attention_turn_threshold,
                attention_update_idle_seconds=30,
                attention_update_max_delay_seconds=90,
            )
        )

    def memory_operation_epoch(self) -> int:
        return self._epoch

    @asynccontextmanager
    async def memory_operation_guard(self):  # type: ignore[no-untyped-def]
        yield

    async def persist_task_outcome_reflection(self, packet):  # type: ignore[no-untyped-def]
        self.task_packets.append(packet)
        return {"summary_id": "summary-1", "summary_category": "task_reflection"}


class _RecordingAttentionL0:
    def __init__(
        self,
        *,
        revision: int = 4,
        conflict_once: bool = False,
        forget_cutoff_at: float = 0.0,
    ) -> None:
        self.revision = revision
        self.conflict_once = conflict_once
        self.forget_cutoff_at = forget_cutoff_at
        self.snapshot_calls: list[str] = []
        self.apply_calls: list[dict[str, object]] = []

    async def get_attention_snapshot(self, session_id: str) -> dict[str, object]:
        self.snapshot_calls.append(session_id)
        return {
            "revision": self.revision,
            "forget_cutoff_at": self.forget_cutoff_at,
            "last_processed_turn_id": None,
            "items": [
                {
                    "item_id": "attention-existing",
                    "kind": "situation",
                    "summary": "Existing situation",
                    "status": "active",
                }
            ],
        }

    async def apply_attention_actions(self, **kwargs):  # type: ignore[no-untyped-def]
        call = dict(kwargs)
        call["actions"] = tuple(call["actions"])
        call["source_texts"] = tuple(call["source_texts"])
        self.apply_calls.append(call)
        if self.conflict_once:
            self.conflict_once = False
            self.revision += 1
            return None
        if int(call["expected_revision"]) != self.revision:
            return None
        self.revision += 1
        return {
            "revision": self.revision,
            "last_processed_turn_id": call["last_processed_turn_id"],
            "items": [],
        }


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


def _accepted_attention_turn(
    *,
    user_message: str,
    assistant_response: str,
    incoming_fact_kind: str = "user_message",
    execution_mode: str = "direct_llm",
    persona_id: str | None = None,
) -> AcceptedConversationOutcome:
    return AcceptedConversationOutcome(
        outcome_id="chat-turn:turn-1:accepted",
        source_turn_id="turn-1",
        user_id="local_user",
        session_id="session-1",
        user_message=user_message,
        assistant_response=assistant_response,
        epoch=0,
        accepted_at=time.time(),
        persona_id=persona_id,
        incoming_fact_kind=incoming_fact_kind,
        execution_mode=execution_mode,
        immediate=True,
    )


async def _admit_and_wait(
    service: PostTurnUnderstandingService,
    outcome: AcceptedConversationOutcome,
) -> None:
    assert await service.admit(outcome) is True
    scheduler = service.scheduler
    assert scheduler is not None
    assert await scheduler.wait_idle(timeout_seconds=1.0) is True


@pytest.mark.asyncio
async def test_memory_updates_do_not_pass_stp_rules_after_response(monkeypatch) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    analysis_calls: list[dict[str, object]] = []

    async def _fake_analyze_interaction(batch, **kwargs):  # type: ignore[no-untyped-def]
        analysis_calls.append(dict(kwargs))
        return BatchInteractionAnalysis(
            turn_analyses={batch[0].turn_id: DEFAULT_ANALYSIS},
            attention_actions=(),
        )

    monkeypatch.setattr(
        postprocess_module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=True,
            deep_persona_enabled=False,
        ),
    )
    monkeypatch.setattr(
        postprocess_module,
        "analyze_interaction_batch",
        _fake_analyze_interaction,
    )
    memory = _RecordingPersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=None,
        self_memory=memory,
    )

    await _admit_and_wait(
        service,
        _accepted_attention_turn(
            user_message="say something funny",
            assistant_response="funny response",
            incoming_fact_kind="user_message",
            execution_mode="direct_llm",
        ),
    )
    await service.shutdown(flush=False)

    assert analysis_calls[-1].get("stp_rules") is None
    assert "allow_state_transition" not in memory.process_calls[-1]


@pytest.mark.asyncio
async def test_memory_updates_skip_stp_rules_outside_direct_chat_scope(monkeypatch) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    analysis_calls: list[dict[str, object]] = []

    async def _fake_analyze_interaction(batch, **kwargs):  # type: ignore[no-untyped-def]
        analysis_calls.append(dict(kwargs))
        return BatchInteractionAnalysis(
            turn_analyses={batch[0].turn_id: DEFAULT_ANALYSIS},
            attention_actions=(),
        )

    monkeypatch.setattr(
        postprocess_module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=True,
            deep_persona_enabled=False,
        ),
    )
    monkeypatch.setattr(
        postprocess_module,
        "analyze_interaction_batch",
        _fake_analyze_interaction,
    )
    memory = _RecordingPersonalityMemory()
    service = PostTurnUnderstandingService(
        unified_memory=None,
        self_memory=memory,
    )

    await _admit_and_wait(
        service,
        _accepted_attention_turn(
            user_message="analyze apple stock",
            assistant_response="analysis report",
            incoming_fact_kind="explore_task_completed",
            execution_mode="explore_task_render",
        ),
    )
    await service.shutdown(flush=False)

    assert analysis_calls[-1].get("stp_rules") is None
    assert "allow_state_transition" not in memory.process_calls[-1]


@pytest.mark.asyncio
async def test_memory_updates_route_observer_candidates(monkeypatch) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    async def _fake_analyze_interaction(batch, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        turn_analysis = InteractionAnalysis(
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
        return BatchInteractionAnalysis(
            turn_analyses={batch[0].turn_id: turn_analysis},
            attention_actions=(),
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
    monkeypatch.setattr(
        postprocess_module,
        "analyze_interaction_batch",
        _fake_analyze_interaction,
    )
    memory = _RecordingPersonalityMemory()
    unified_memory = _FakeUnifiedMemory()
    unified_memory.l2 = _RecordingL2Store()
    service = PostTurnUnderstandingService(
        unified_memory=unified_memory,
        self_memory=memory,
    )

    await _admit_and_wait(
        service,
        _accepted_attention_turn(
            user_message="以后这种方案讨论，先说结论，再说风险。七号这里可以稍微软一点。",
            assistant_response="好，我按这个顺序说。",
            incoming_fact_kind="user_message",
            execution_mode="direct_llm",
            persona_id="seven",
        ),
    )
    await service.shutdown(flush=False)

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
    import magi.agent.post_turn_understanding as postprocess_module

    async def _fake_analyze_interaction(batch, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        turn_analysis = InteractionAnalysis(
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
        return BatchInteractionAnalysis(
            turn_analyses={batch[0].turn_id: turn_analysis},
            attention_actions=(),
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
    monkeypatch.setattr(
        postprocess_module,
        "analyze_interaction_batch",
        _fake_analyze_interaction,
    )
    memory = _RecordingPersonalityMemory()
    unified_memory = _FakeUnifiedMemory()
    service = PostTurnUnderstandingService(
        unified_memory=unified_memory,
        self_memory=memory,
    )

    await _admit_and_wait(
        service,
        _accepted_attention_turn(
            user_message="以后改代码前先讲完成标准。",
            assistant_response="好，之后我会先说明完成标准。",
            incoming_fact_kind="user_message",
            execution_mode="direct_llm",
            persona_id="seven",
        ),
    )
    await service.shutdown(flush=False)

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
async def test_committed_chat_turns_share_one_batched_attention_analysis(
    chat_store: ChatStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    l0_store = _RecordingAttentionL0()
    unified_memory = _FakeUnifiedMemory(
        l0=l0_store,
        epoch=7,
        attention_turn_threshold=3,
    )
    personality_memory = _RecordingPersonalityMemory()
    analyzed_batches: list[tuple[AcceptedL0AttentionTurn, ...]] = []
    current_attention_inputs: list[list[dict[str, object]]] = []
    understanding_service = PostTurnUnderstandingService(
        unified_memory=unified_memory,
        self_memory=personality_memory,
    )

    async def _fake_analyze_interaction_batch(
        batch,
        *,
        current_attention,
        **_kwargs,
    ):  # type: ignore[no-untyped-def]
        analyzed_batches.append(tuple(batch))
        current_attention_inputs.append(list(current_attention))
        return BatchInteractionAnalysis(
            turn_analyses={
                turn.turn_id: DEFAULT_ANALYSIS
                for turn in batch
            },
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.FOCUS,
                    summary="Reviewing the current design",
                    source_turn_ids=(batch[-1].turn_id,),
                ),
            ),
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
    monkeypatch.setattr(
        postprocess_module,
        "analyze_interaction_batch",
        _fake_analyze_interaction_batch,
    )
    service = ChatPostProcessService(
        agent_id="session-1",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        memory=personality_memory,
        unified_memory=unified_memory,
        post_turn_understanding_service=understanding_service,
        chat_store=chat_store,
        max_fact_memory=10,
    )

    try:
        outcomes = []
        for index in range(1, 4):
            turn_id = f"turn-batch-{index}"
            await _create_admitted_user_turn(chat_store, turn_id=turn_id)
            context, result = _plain_non_streamed_context_and_result(turn_id=turn_id)
            context.latest_user_message = f"user message {index}"
            context.active_persona_id = "seven"
            result.root_user_message = context.latest_user_message
            result.response_text = f"assistant response {index}"
            outcomes.append(await service.handle(context, result))
            await asyncio.sleep(0)

        scheduler = understanding_service.scheduler
        assert scheduler is not None
        assert await scheduler.wait_idle(timeout_seconds=1.0) is True

        assert [outcome.memory_updated for outcome in outcomes] == [True, True, True]
        assert len(analyzed_batches) == 1
        assert [turn.turn_id for turn in analyzed_batches[0]] == [
            "chat-turn:turn-batch-1:accepted",
            "chat-turn:turn-batch-2:accepted",
            "chat-turn:turn-batch-3:accepted",
        ]
        assert [turn.epoch for turn in analyzed_batches[0]] == [7, 7, 7]
        persisted_messages = await chat_store.list_messages(
            session_id="session-1"
        )
        assistant_commit_times = {
            str(message.turn_id): int(message.created_at_ms) / 1000.0
            for message in persisted_messages
            if str(message.role) == "assistant"
        }
        assert [turn.accepted_at for turn in analyzed_batches[0]] == [
            assistant_commit_times[f"turn-batch-{index}"]
            for index in range(1, 4)
        ]
        assert [turn.incoming_fact_kind for turn in analyzed_batches[0]] == [
            "user_message",
            "user_message",
            "user_message",
        ]
        assert [turn.execution_mode for turn in analyzed_batches[0]] == [
                "agent_run",
                "agent_run",
                "agent_run",
        ]
        assert [turn.persona_id for turn in analyzed_batches[0]] == [
            "seven",
            "seven",
            "seven",
        ]
        assert current_attention_inputs == [
            [
                {
                    "item_id": "attention-existing",
                    "kind": "situation",
                    "summary": "Existing situation",
                    "status": "active",
                }
            ]
        ]
        assert len(l0_store.apply_calls) == 1
        assert l0_store.apply_calls[0]["expected_revision"] == 4
        assert l0_store.apply_calls[0]["last_processed_turn_id"] == "turn-batch-3"
        assert l0_store.apply_calls[0]["source_texts"] == (
            "user message 1",
            "user message 2",
            "user message 3",
        )
        assert [
            call["user_message"]
            for call in personality_memory.process_calls
        ] == [
            "user message 1",
            "user message 2",
            "user message 3",
        ]
        assert understanding_service.has_pending_work() is False
    finally:
        await service.shutdown_background_tasks()
        await understanding_service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_attention_batch_drops_turns_from_an_old_memory_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    l0_store = _RecordingAttentionL0()
    unified_memory = _FakeUnifiedMemory(l0=l0_store, epoch=8)
    analysis_calls = 0

    async def _unexpected_analysis(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal analysis_calls
        analysis_calls += 1
        return None

    monkeypatch.setattr(
        postprocess_module,
        "analyze_interaction_batch",
        _unexpected_analysis,
    )
    service = PostTurnUnderstandingService(
        unified_memory=unified_memory,
        self_memory=None,
    )

    try:
        await _admit_and_wait(
            service,
            AcceptedConversationOutcome(
                outcome_id="chat-turn:turn-old-epoch:accepted",
                source_turn_id="turn-old-epoch",
                user_id="local_user",
                session_id="session-1",
                user_message="old message",
                assistant_response="old response",
                epoch=7,
                accepted_at=time.time(),
                immediate=True,
            ),
        )

        assert analysis_calls == 0
        assert l0_store.snapshot_calls == []
        assert l0_store.apply_calls == []
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_attention_revision_conflict_reanalyzes_fixed_scheduler_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    l0_store = _RecordingAttentionL0(conflict_once=True)
    unified_memory = _FakeUnifiedMemory(l0=l0_store, epoch=3)
    personality_memory = _RecordingPersonalityMemory()
    analysis_calls = 0

    async def _fake_analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal analysis_calls
        analysis_calls += 1
        return BatchInteractionAnalysis(
            turn_analyses={batch[0].turn_id: DEFAULT_ANALYSIS},
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.ACTIVE_OBJECT,
                    summary="A person from the stale pre-forget batch",
                    source_turn_ids=(batch[0].turn_id,),
                    source_event_ids=("event-id-invented-by-model",),
                    entity_id="person:forgotten",
                ),
            ),
        )

    monkeypatch.setattr(
        postprocess_module,
        "get_personality_feature_flags",
        lambda: SimpleNamespace(
            state_memory_enabled=True,
            state_transition_enabled=True,
            deep_persona_enabled=False,
        ),
    )
    monkeypatch.setattr(postprocess_module, "analyze_interaction_batch", _fake_analyze)
    service = PostTurnUnderstandingService(
        unified_memory=unified_memory,
        self_memory=personality_memory,
    )
    outcome = AcceptedConversationOutcome(
        outcome_id="chat-turn:turn-conflict:accepted",
        source_turn_id="turn-conflict",
        user_id="local_user",
        session_id="session-1",
        user_message="message",
        assistant_response="response",
        epoch=3,
        accepted_at=time.time(),
        immediate=True,
    )

    try:
        scheduler = service.scheduler
        assert scheduler is not None
        scheduler._retry_initial_seconds = 0.0
        scheduler._retry_max_seconds = 0.0
        assert await service.admit(outcome) is True
        assert await scheduler.wait_idle(timeout_seconds=2.0) is True

        assert len(personality_memory.process_calls) == 1
        assert analysis_calls == 2
        assert len(l0_store.apply_calls) == 2
        assert tuple(l0_store.apply_calls[-1]["actions"])[0].entity_id == (
            "person:forgotten"
        )
        assert tuple(l0_store.apply_calls[-1]["actions"])[0].source_event_ids == ()
        assert await service.admit(outcome) is False
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_entity_forget_drops_queued_old_turn_but_allows_new_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    cutoff_at = time.time()
    l0_store = _RecordingAttentionL0()
    unified_memory = _FakeUnifiedMemory(
        l0=l0_store,
        epoch=3,
        attention_turn_threshold=20,
    )
    analyzed_turn_ids: list[str] = []

    async def _fake_analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        analyzed_turn_ids.extend(turn.turn_id for turn in batch)
        return BatchInteractionAnalysis(
            turn_analyses={turn.turn_id: DEFAULT_ANALYSIS for turn in batch},
            attention_actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.ACTIVE_OBJECT,
                    summary="A newly mentioned person",
                    source_turn_ids=(batch[-1].turn_id,),
                    entity_id="person:forgotten",
                ),
            ),
        )

    monkeypatch.setattr(postprocess_module, "analyze_interaction_batch", _fake_analyze)
    service = PostTurnUnderstandingService(
        unified_memory=unified_memory,
        self_memory=None,
    )
    scheduler = service.scheduler
    assert scheduler is not None

    old_turn = AcceptedConversationOutcome(
        outcome_id="chat-turn:turn-before-forget:accepted",
        source_turn_id="turn-before-forget",
        user_id="local_user",
        session_id="session-1",
        user_message="old private context",
        assistant_response="old response",
        epoch=3,
        accepted_at=cutoff_at - 1,
    )
    new_turn = AcceptedConversationOutcome(
        outcome_id="chat-turn:turn-after-forget:accepted",
        source_turn_id="turn-after-forget",
        user_id="local_user",
        session_id="session-1",
        user_message="newly mentioned context",
        assistant_response="new response",
        epoch=3,
        accepted_at=cutoff_at + 1,
        immediate=True,
    )

    try:
        assert await service.admit(old_turn) is True
        await asyncio.sleep(0.01)
        assert analyzed_turn_ids == []

        l0_store.forget_cutoff_at = cutoff_at
        unified_memory._memory_config_getter = lambda: SimpleNamespace(
            l0=SimpleNamespace(
                attention_update_turn_threshold=1,
                attention_update_idle_seconds=30,
                attention_update_max_delay_seconds=90,
            )
        )
        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert analyzed_turn_ids == []
        assert l0_store.apply_calls == []

        assert await service.admit(new_turn) is True
        assert await scheduler.wait_idle(timeout_seconds=1.0) is True
        assert analyzed_turn_ids == ["chat-turn:turn-after-forget:accepted"]
        assert len(l0_store.apply_calls) == 1
        assert l0_store.apply_calls[0]["source_turn_accepted_at"] == {
            "turn-after-forget": cutoff_at + 1
        }
    finally:
        await service.shutdown(flush=False)


@pytest.mark.asyncio
async def test_agent_lifecycle_preserves_shared_pending_attention_until_runtime_discard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.post_turn_understanding as postprocess_module

    analyzed_turn_ids: list[str] = []

    async def _fake_analyze(batch, **_kwargs):  # type: ignore[no-untyped-def]
        analyzed_turn_ids.extend(turn.turn_id for turn in batch)
        return BatchInteractionAnalysis(
            turn_analyses={turn.turn_id: DEFAULT_ANALYSIS for turn in batch},
            attention_actions=(),
        )

    monkeypatch.setattr(postprocess_module, "analyze_interaction_batch", _fake_analyze)

    def _service_with_pending_turn(
        turn_id: str,
    ) -> tuple[
        ChatPostProcessService,
        PostTurnUnderstandingService,
        AcceptedConversationOutcome,
    ]:
        unified = _FakeUnifiedMemory(
            l0=_RecordingAttentionL0(),
            epoch=2,
            attention_turn_threshold=20,
        )
        understanding = PostTurnUnderstandingService(
            unified_memory=unified,
            self_memory=None,
        )
        service = ChatPostProcessService(
            agent_id="session-1",
            context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
            get_event_emitter=lambda: _FakeEventEmitter(),
            get_task_agent_manager=lambda: None,
            get_sensor_hub=lambda: None,
            unified_memory=unified,
            post_turn_understanding_service=understanding,
        )
        return service, understanding, AcceptedConversationOutcome(
            outcome_id=f"chat-turn:{turn_id}:accepted",
            source_turn_id=turn_id,
            user_id="local_user",
            session_id="session-1",
            user_message="ordinary message",
            assistant_response="ordinary response",
            epoch=2,
            accepted_at=time.time(),
        )

    normal_service, normal_understanding, normal_turn = _service_with_pending_turn(
        "turn-normal-stop"
    )
    assert await normal_understanding.admit(normal_turn) is True
    assert normal_understanding.has_pending_work("session-1") is True
    await normal_service.shutdown_background_tasks()
    assert analyzed_turn_ids == []
    assert normal_understanding.has_pending_work("session-1") is True
    assert await normal_understanding.shutdown(flush=True) is True
    assert analyzed_turn_ids == ["chat-turn:turn-normal-stop:accepted"]
    assert normal_understanding.has_pending_work() is False

    (
        destructive_service,
        destructive_understanding,
        destructive_turn,
    ) = _service_with_pending_turn("turn-destructive-clear")
    assert await destructive_understanding.admit(destructive_turn) is True
    assert destructive_understanding.has_pending_work("session-1") is True
    await destructive_service.cancel_background_tasks()
    assert analyzed_turn_ids == ["chat-turn:turn-normal-stop:accepted"]
    assert destructive_understanding.has_pending_work("session-1") is True
    await destructive_understanding.discard_session("session-1")
    assert destructive_understanding.has_pending_work("session-1") is False
    await destructive_understanding.shutdown(flush=False)


@pytest.mark.asyncio
async def test_outcome_writer_persists_interim_then_final_messages(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
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

    messages = await chat_store.list_messages(session_id="session-1")
    assert [message.message_kind for message in messages] == [
        "user_text",
        "assistant_interim",
        "assistant_final",
    ]
    assert messages[-1].replaces_message_id == messages[-2].message_id
    projection = await chat_store.get_assistant_memory_projection(
        messages[-1].message_id
    )
    assert projection is not None
    assert projection.content == "final answer"


@pytest.mark.asyncio
async def test_outcome_writer_bumps_history_version_for_assistant_final(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
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
async def test_outcome_writer_does_not_complete_turn_before_final_is_saved(
    chat_store: ChatStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-write-order",
        message_text="hello",
        created_at_ms=1710000000000,
    )

    async def _fail_final_write(**_kwargs) -> None:
        raise RuntimeError("simulated message write failure")

    monkeypatch.setattr(
        chat_store,
        "commit_unmanaged_assistant_outcome",
        _fail_final_write,
    )
    with pytest.raises(RuntimeError, match="simulated message write failure"):
        await writer.persist_final_chat_outcome(
            turn_id="turn-write-order",
            orchestration_id=None,
            execution_mode="direct_llm",
            ux_plan={"assistant_surface_mode": "final_only"},
            response_text="final answer",
            started_at_ms=1710000000000,
            completed_at_ms=1710000000200,
        )

    turn = await chat_store.get_turn("turn-write-order")
    assert turn is not None
    assert turn.status != "completed"
    assert (
        await chat_store.get_latest_message_for_turn(
            "turn-write-order",
            message_kind="assistant_final",
        )
        is None
    )


@pytest.mark.asyncio
async def test_outcome_writer_persists_assistant_attachments(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-attachments",
        message_text="show me photos",
        created_at_ms=1710000000000,
    )
    attachment = await _managed_test_attachment(
        chat_store,
        session_id="session-1",
        turn_id="turn-attachments",
        attachment_id="att-1",
        original_name="photo.jpg",
        content=b"photo",
    )

    await writer.persist_final_chat_outcome(
        turn_id="turn-attachments",
        orchestration_id=None,
        execution_mode="function_calling",
        ux_plan={"assistant_surface_mode": "final_only"},
        response_text="Here are the photos.",
        attachments=[attachment],
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
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-asset-refs",
        message_text="show me the candidate assets",
        created_at_ms=1710000000000,
    )
    attachment = await _managed_test_attachment(
        chat_store,
        session_id="session-1",
        turn_id="turn-asset-refs",
        attachment_id="att-1",
        original_name="photo.jpg",
        content=b"photo",
    )

    await writer.persist_final_chat_outcome(
        turn_id="turn-asset-refs",
        orchestration_id=None,
        execution_mode="function_calling",
        ux_plan={"assistant_surface_mode": "final_only"},
        response_text="Here are the candidate assets.",
        attachments=[attachment],
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
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-rhythm",
        message_text="explain rhythm",
        created_at_ms=1710000000000,
    )
    attachment = await _managed_test_attachment(
        chat_store,
        session_id="session-1",
        turn_id="turn-rhythm",
        attachment_id="att-1",
        original_name="generated.png",
        content=b"0123456789",
        include_mime_and_size=True,
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
        attachments=[attachment],
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
            "code_agent_delegations": [
                {
                    "delegation_id": "0123456789abcdef0123456789abcdef",
                    "turn_id": "turn-rhythm",
                    "workspace_path": "/workspace-at-execution",
                }
            ],
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
    assert "code_agent_delegations" not in first_payload
    assert second_payload["recalled_memories"][0]["topic"] == "example.com"
    assert second_payload["recalled_memory_summary"]["total_count"] == 12
    assert second_payload["code_agent_delegations"] == [
        {
            "delegation_id": "0123456789abcdef0123456789abcdef",
            "turn_id": "turn-rhythm",
            "workspace_path": "/workspace-at-execution",
        }
    ]
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
async def test_outcome_writer_replaces_partial_rhythm_before_completion(
    chat_store: ChatStore,
) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-partial-rhythm",
        message_text="explain rhythm",
        created_at_ms=1710000000000,
    )
    await chat_store.append_message(
        ChatMessageRecord(
            message_id="partial-rhythm-0",
            session_id="session-1",
            turn_id="turn-partial-rhythm",
            user_id="local_user",
            role="assistant",
            message_kind="assistant_rhythm_segment",
            content_text="旧的第一段",
            payload_json=json.dumps(
                {
                    "rhythm": {
                        "segment_index": 0,
                        "segment_count": 2,
                    }
                }
            ),
            is_final=True,
            is_visible=True,
            created_at_ms=1710000000100,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    plan = AssistantResponsePlan(
        mode="multi_message",
        aggregate_text="新的完整回答",
        segments=[
            AssistantResponseSegment(
                content="新的第一段",
                delay_ms=0,
                segment_index=0,
                source_unit_ids=["u1"],
            ),
            AssistantResponseSegment(
                content="新的第二段",
                delay_ms=500,
                segment_index=1,
                source_unit_ids=["u2"],
            ),
        ],
    )

    records = await writer.persist_segmented_chat_outcome(
        turn_id="turn-partial-rhythm",
        orchestration_id=None,
        execution_mode="direct_llm",
        ux_plan={"assistant_surface_mode": "final_only"},
        response_plan=plan,
        started_at_ms=1710000000000,
        completed_at_ms=1710000000200,
    )

    visible_segments = [
        message
        for message in await chat_store.list_messages(session_id="session-1")
        if message.turn_id == "turn-partial-rhythm"
        and message.message_kind == "assistant_rhythm_segment"
        and message.is_visible
    ]
    old_partial = await chat_store.get_message("partial-rhythm-0")
    turn = await chat_store.get_turn("turn-partial-rhythm")
    assert old_partial is not None
    assert old_partial.is_visible is False
    assert [record.content_text for record in records] == [
        "新的第一段",
        "新的第二段",
    ]
    assert [message.message_id for message in visible_segments] == [
        record.message_id for record in records
    ]
    assert turn is not None
    assert turn.status == "completed"


@pytest.mark.parametrize(
    ("segment_indexes", "error_text"),
    [
        (
            list(range(MAX_RHYTHM_SEGMENT_COUNT + 1)),
            "Conversation rhythm segment count is out of range",
        ),
        ([0, 0], "Conversation rhythm segment indexes are invalid"),
        ([1, 0], "Conversation rhythm segment indexes are invalid"),
        ([False, 1], "Conversation rhythm segment indexes are invalid"),
    ],
)
@pytest.mark.asyncio
async def test_outcome_writer_rejects_invalid_rhythm_plan(
    chat_store: ChatStore,
    segment_indexes: list[int],
    error_text: str,
) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    turn_id = "turn-excessive-rhythm"
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id=turn_id,
        message_text="explain rhythm",
        created_at_ms=1710000000000,
    )
    plan = AssistantResponsePlan(
        mode="multi_message",
        aggregate_text="too many parts",
        segments=[
            AssistantResponseSegment(
                content=f"part {position}",
                delay_ms=0,
                segment_index=segment_index,
                source_unit_ids=[f"u{position}"],
            )
            for position, segment_index in enumerate(segment_indexes)
        ],
    )

    with pytest.raises(ValueError, match=error_text):
        await writer.persist_segmented_chat_outcome(
            turn_id=turn_id,
            orchestration_id=None,
            execution_mode="direct_llm",
            ux_plan={"assistant_surface_mode": "final_only"},
            response_plan=plan,
            started_at_ms=1710000000000,
            completed_at_ms=1710000000200,
        )

    messages = await chat_store.list_messages(session_id="session-1")
    assert all(
        message.message_kind != "assistant_rhythm_segment"
        for message in messages
    )


@pytest.mark.asyncio
async def test_outcome_writer_uses_cumulative_segment_timestamps(chat_store: ChatStore) -> None:
    writer = ChatOutcomeWriter(
        chat_store=chat_store,
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
async def test_duplicate_worker_result_for_one_turn_is_not_delivered_or_reanalyzed(
    chat_store: ChatStore,
) -> None:
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-worker-once",
        message_text="Please audit the release checklist.",
        created_at_ms=1710000000000,
    )
    delivered: list[str] = []

    async def _deliver(_context, *, content):  # type: ignore[no-untyped-def]
        delivered.append(content.text)
        return DeliveryFanoutResult()

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        deliver_final_response=_deliver,
        max_fact_memory=10,
    )
    scheduled: list[dict[str, object]] = []
    service._schedule_background_memory_updates = (  # type: ignore[method-assign]
        lambda **kwargs: scheduled.append(dict(kwargs)) or True
    )
    worker_fact = FactRecord(
        agent_id="chat:local_user",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": "turn-worker-once",
            "worker_id": "worker-1",
            "orchestration_id": "orch-1",
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000002.0,
        correlation_id="worker-corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=worker_fact,
        recent_facts=[worker_fact],
        batch_facts=[worker_fact],
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
            turn_id="turn-worker-once",
        ),
    )
    first_result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        response_text="First accepted audit.",
        root_user_message="Please audit the release checklist.",
        correlation_id="worker-corr-1",
        orchestration_id="orch-1",
        turn_id="turn-worker-once",
    )
    duplicate_result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        response_text="Duplicate audit that must be rejected.",
        root_user_message="Please audit the release checklist.",
        correlation_id="worker-corr-duplicate",
        orchestration_id="orch-1",
        turn_id="turn-worker-once",
    )

    first = await service.handle(context, first_result)
    duplicate = await service.handle(context, duplicate_result)

    visible_assistant = [
        message
        for message in await chat_store.list_messages(session_id="session-1")
        if message.role == "assistant" and message.is_visible
    ]
    assert first.emitted is True
    assert first.memory_updated is True
    assert duplicate.emitted is False
    assert duplicate.memory_updated is False
    assert delivered == ["First accepted audit."]
    assert [message.content_text for message in visible_assistant] == [
        "First accepted audit."
    ]
    assert len({message.message_id for message in visible_assistant}) == 1
    assert len(scheduled) == 1
    assert scheduled[0]["turn_id"] == "turn-worker-once"


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
async def test_record_tool_interaction_does_not_write_runtime_tactics_into_l0(
    tmp_path,
) -> None:
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

    assert workbench["attention_items"] == []


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
async def test_record_tool_loop_fact_does_not_write_runtime_tactics_into_l0(
    tmp_path,
) -> None:
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

    assert workbench["attention_items"] == []


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
    decision.execution_mode = None

    await service.record_tool_selection(first_context, decision, ToolSelection())
    await service.persist_turn_supersessions(
        superseded_turns=[
            TurnSupersession(turn_id="turn-1", anchor_turn_id="turn-2", reason="interrupt"),
        ],
        updated_at_ms=1710000001000,
    )
    await service.record_tool_selection(second_context, decision, ToolSelection())
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
        mode=None,
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
        mode=None,
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
        mode=None,
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
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
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
        mode=None,
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
    projection = await chat_store.get_assistant_memory_projection(
        messages[-1].message_id
    )
    assert projection is not None
    assert projection.content == "final answer"
    payload = json.loads(notifications[0].payload_json)
    assert payload["message_id"] == messages[-1].message_id
    assert payload["message_kind"] == "assistant_final"
    assert payload["persona_id"] == "persona-seven"


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_commit_fails", [False, True])
async def test_atomic_segment_commit_failure_falls_back_without_partial_transcript(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
    fallback_commit_fails: bool,
) -> None:
    class _AtomicOutcomeFails:
        def __init__(self, delegate: ChatStore, *, fail_fallback: bool) -> None:
            self._delegate = delegate
            self.fail_fallback = fail_fallback
            self.commit_attempts: list[tuple[str, ...]] = []

        def __getattr__(self, name: str) -> Any:
            return getattr(self._delegate, name)

        async def commit_unmanaged_assistant_outcome(self, **kwargs):  # type: ignore[no-untyped-def]
            message_kinds = tuple(
                message.message_kind for message in kwargs["messages"]
            )
            self.commit_attempts.append(message_kinds)
            if message_kinds and all(
                kind == "assistant_rhythm_segment" for kind in message_kinds
            ):
                raise RuntimeError("atomic segment commit failed")
            if self.fail_fallback:
                raise RuntimeError("final fallback commit failed")
            return await self._delegate.commit_unmanaged_assistant_outcome(
                **kwargs
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
    flaky_store = _AtomicOutcomeFails(
        chat_store,
        fail_fallback=fallback_commit_fails,
    )
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
        mode=None,
        response_text="first part second part",
        correlation_id="corr-1",
        turn_id="turn-fallback",
        ux_plan={"assistant_surface_mode": "final_only"},
    )

    if fallback_commit_fails:
        with pytest.raises(
            RuntimeError,
            match="final fallback commit failed",
        ):
            await service.handle(context, result)
    else:
        await service.handle(context, result)

    messages = await chat_store.list_messages(session_id="session-1")
    visible_messages = [message for message in messages if message.is_visible]
    assert flaky_store.commit_attempts == [
        ("assistant_rhythm_segment", "assistant_rhythm_segment"),
        ("assistant_final",),
    ]
    assert all(
        message.message_kind != "assistant_rhythm_segment"
        for message in messages
    )
    if fallback_commit_fails:
        assert [message.message_kind for message in visible_messages] == ["user_text"]
        turn = await chat_store.get_turn("turn-fallback")
        assert turn is not None
        assert turn.status != "completed"
        assert await chat_store.count_assistant_memory_projections() == 0
        return
    assert [message.message_kind for message in visible_messages] == [
        "user_text",
        "assistant_final",
    ]
    assert visible_messages[-1].content_text == "first part second part"
    projection = await chat_store.get_assistant_memory_projection(
        visible_messages[-1].message_id
    )
    assert projection is not None
    assert projection.content == "first part second part"


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
        mode=None,
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
@pytest.mark.parametrize(
    ("response_text", "skip_emit"),
    [
        ("this should be suppressed", False),
        ("", True),
    ],
)
async def test_handle_suppresses_final_response_when_session_run_is_cancelling(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
    response_text: str,
    skip_emit: bool,
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
        mode=None,
        response_text=response_text,
        skip_emit=skip_emit,
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

    delivery = await chat_store.get_user_turn_delivery(
        turn_id="turn-cancelled",
    )
    messages = await chat_store.list_messages(session_id="session-1")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert outcome.emitted is False
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert [message.message_kind for message in messages] == ["user_text"]
    assert event_emitter.chat_response_events == []
    assert [notification.channel for notification in notifications] == [
        "execution_control"
    ]
    assert json.loads(notifications[0].payload_json)["state"] == "cancelled"
    assert completed_runs == [("session-1", "run-cancelled", 0)]


@pytest.mark.asyncio
async def test_handle_maps_reaction_only_turn_to_user_label(
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
    reaction_decision.execution_mode = None
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
    result = ExecutionResult(
        mode=None,
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
    delivery = await chat_store.get_user_turn_delivery(
        turn_id="turn-react-final",
    )
    messages = await chat_store.list_messages(session_id="session-1")
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert turn.status == "completed"
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert [message.message_kind for message in messages] == ["user_text"]
    assert messages[-1].label is not None
    assert messages[-1].label.to_dict() == {
        "kind": "emoji",
        "text": "👌",
        "applied_by": "assistant",
        "source": "reaction_only",
        "created_at_ms": 1710000000000,
    }
    assert await chat_store.count_assistant_memory_projections() == 0
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
        delivery_attempt_no=0,
        runtime_command_id=101,
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
    await _create_admitted_user_turn(
        chat_store,
        turn_id="turn-none",
        message_text="嗯",
    )

    result = ExecutionResult(
        mode=None,
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
    notifications = await runtime_trace_store.list_notifications(after_id=0)

    assert turn is not None
    assert turn.status == "completed"
    assert [message.message_kind for message in messages] == ["user_text"]
    controls = [item for item in notifications if item.channel == "execution_control"]
    assert len(controls) == 1
    control_payload = json.loads(controls[0].payload_json)
    assert control_payload["state"] == "completed"
    assert control_payload["turn_id"] == "turn-none"
    assert control_payload["session_id"] == "session-1"
    assert control_payload["can_cancel"] is False
    delivery = await chat_store.get_user_turn_delivery(turn_id="turn-none")
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL


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
    reaction_decision.execution_mode = None
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
    result = ExecutionResult(
        mode=None,
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
    controls = [item for item in notifications if item.channel == "execution_control"]
    assert len(controls) == 1
    assert json.loads(controls[0].payload_json)["state"] == "completed"
    assert json.loads(controls[0].payload_json)["turn_id"] == "turn-react-empty"


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
        mode=None,
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
        mode=None,
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
async def test_release_deferred_turns_callback_invoked_after_completion() -> None:
    calls: list[tuple[str, list[object]]] = []
    deferred_turn = object()

    async def _release(session_id: str, deferred_turns: list[object]) -> None:
        calls.append((session_id, deferred_turns))

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
        release_deferred_turns=_release,
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

    await service._release_deferred_user_turns(
        session_id=context.session_id,
        deferred_turns=[deferred_turn],
    )

    assert calls == [("session-1", [deferred_turn])]


@pytest.mark.asyncio
async def test_release_deferred_turns_callback_absent_is_noop() -> None:
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
    await service._release_deferred_user_turns(
        session_id=context.session_id,
        deferred_turns=[object()],
    )


@pytest.mark.asyncio
async def test_release_deferred_turns_swallows_callback_exception() -> None:
    def _raising(session_id: str, deferred_turns: list[object]) -> None:
        _ = (session_id, deferred_turns)
        raise RuntimeError("boom")

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
        release_deferred_turns=_raising,
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
    await service._release_deferred_user_turns(
        session_id=context.session_id,
        deferred_turns=[object()],
    )


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
        mode=None,
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
async def test_run_completion_failure_stops_delivery_after_durable_reply(
    chat_store: ChatStore,
) -> None:
    seam_calls: list[str] = []

    async def _fake_seam(context, *, content):  # type: ignore[no-untyped-def]
        _ = context
        seam_calls.append(content.text)
        return DeliveryFanoutResult()

    def _fail_completion(
        session_id: str,
        run_id: str,
        revision: int,
    ) -> tuple[bool, list[Any]]:
        assert (session_id, run_id, revision) == ("session-1", "run-1", 0)
        raise OSError("session completion unavailable")

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        complete_session_run=_fail_completion,
        resolve_session_run_status=lambda _session_id, _run_id, _revision: "running",
        deliver_final_response=_fake_seam,
        max_fact_memory=10,
    )
    turn_id = "turn-completion-failure"
    context, result = _plain_non_streamed_context_and_result(turn_id=turn_id)
    assert isinstance(context.latest_fact, FactRecord)
    context.latest_fact.delivery_attempt_no = 0
    context.latest_fact.runtime_command_id = 101
    await _create_admitted_user_turn(chat_store, turn_id=turn_id)

    with pytest.raises(OSError, match="session completion unavailable"):
        await service.handle(context, result)

    delivery = await chat_store.get_user_turn_delivery(turn_id=turn_id)
    final = await chat_store.get_latest_message_for_turn(
        turn_id,
        message_kind="assistant_final",
    )
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert final is not None
    assert final.content_text == "final answer"
    assert seam_calls == []


@pytest.mark.asyncio
async def test_async_run_status_resolver_does_not_skip_completion() -> None:
    completion_calls: list[tuple[str, str, int]] = []

    async def _resolve_status(
        session_id: str,
        run_id: str,
        revision: int,
    ) -> str:
        assert (session_id, run_id, revision) == ("session-1", "run-1", 0)
        return "running"

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        complete_session_run=lambda session_id, run_id, revision: completion_calls.append(
            (session_id, run_id, revision)
        ),
        resolve_session_run_status=_resolve_status,
        max_fact_memory=10,
    )
    context, _result = _plain_non_streamed_context_and_result()

    await service._finalize_session_run(context)

    assert completion_calls == [("session-1", "run-1", 0)]


@pytest.mark.asyncio
async def test_final_surface_marks_exact_delivery_attempt_terminal(
    chat_store: ChatStore,
) -> None:
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        max_fact_memory=10,
    )
    context, result = _plain_non_streamed_context_and_result(
        turn_id="turn-terminal-exact"
    )
    assert isinstance(context.latest_fact, FactRecord)
    context.latest_fact.delivery_attempt_no = 0
    context.latest_fact.runtime_command_id = 101
    await _create_admitted_user_turn(
        chat_store,
        turn_id="turn-terminal-exact",
    )

    await service.handle(context, result)

    delivery = await chat_store.get_user_turn_delivery(
        turn_id="turn-terminal-exact"
    )
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert await service.mark_user_turn_delivery_terminal_if_persisted(
        turn_id="turn-terminal-exact",
        source_fact=context.latest_fact,
        required_message_kind="assistant_final",
        expected_message_count=1,
    )


@pytest.mark.asyncio
async def test_final_surface_without_command_identity_recovers_current_attempt(
    chat_store: ChatStore,
) -> None:
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        max_fact_memory=10,
    )
    context, result = _plain_non_streamed_context_and_result(
        turn_id="turn-terminal-recovered"
    )
    await _create_admitted_user_turn(
        chat_store,
        turn_id="turn-terminal-recovered",
    )

    await service.handle(context, result)

    delivery = await chat_store.get_user_turn_delivery(
        turn_id="turn-terminal-recovered"
    )
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL


@pytest.mark.asyncio
async def test_old_attempt_cannot_close_newer_delivery_after_final_surface(
    chat_store: ChatStore,
) -> None:
    seam_calls: list[str] = []

    async def _fake_seam(context, *, content):  # type: ignore[no-untyped-def]
        _ = context
        seam_calls.append(content.text)
        return DeliveryFanoutResult()

    assembler = _FakeContextAssembler()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=assembler,  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        deliver_final_response=_fake_seam,
        max_fact_memory=10,
    )
    scheduled_memory_updates: list[dict[str, Any]] = []
    service._schedule_background_memory_updates = (  # type: ignore[method-assign]
        lambda **kwargs: scheduled_memory_updates.append(dict(kwargs))
    )
    turn_id = "turn-terminal-old-attempt"
    context, result = _plain_non_streamed_context_and_result(turn_id=turn_id)
    assert isinstance(context.latest_fact, FactRecord)
    context.latest_fact.delivery_attempt_no = 0
    context.latest_fact.runtime_command_id = 101
    await _create_admitted_user_turn(chat_store, turn_id=turn_id)
    prepared = await chat_store.prepare_user_turn_delivery_attempt(
        turn_id=turn_id,
        expected_attempt_no=0,
        updated_at_ms=1710000000003,
    )
    assert prepared is not None
    assert prepared.delivery_attempt_no == 1
    assert await chat_store.mark_user_turn_delivery_queued(
        turn_id=turn_id,
        delivery_attempt_no=1,
        command_id=202,
        updated_at_ms=1710000000004,
    )
    assert await chat_store.mark_user_turn_delivery_admitted(
        turn_id=turn_id,
        delivery_attempt_no=1,
        command_id=202,
        updated_at_ms=1710000000005,
    )

    outcome = await service.handle(context, result)

    delivery = await chat_store.get_user_turn_delivery(turn_id=turn_id)
    visible_messages = [
        message
        for message in await chat_store.list_messages(session_id="session-1")
        if message.is_visible
    ]
    assert outcome.emitted is False
    assert delivery is not None
    assert delivery.delivery_attempt_no == 1
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_ADMITTED
    assert delivery.current_command_id == 202
    assert [message.message_kind for message in visible_messages] == ["user_text"]
    assert seam_calls == []
    assert assembler.history == []
    assert scheduled_memory_updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("segmented", [False, True])
@pytest.mark.parametrize("source_has_delivery_identity", [False, True])
async def test_durable_cancel_wins_after_postprocess_preflight(
    chat_store: ChatStore,
    segmented: bool,
    source_has_delivery_identity: bool,
) -> None:
    class _StaticRhythmPlanner:
        async def plan(self, **_kwargs):  # type: ignore[no-untyped-def]
            if not segmented:
                return None
            return AssistantResponsePlan(
                mode="multi_message",
                aggregate_text="first part second part",
                segments=[
                    AssistantResponseSegment(
                        content="first part",
                        delay_ms=0,
                        segment_index=0,
                        source_unit_ids=["u1"],
                    ),
                    AssistantResponseSegment(
                        content="second part",
                        delay_ms=0,
                        segment_index=1,
                        source_unit_ids=["u2"],
                    ),
                ],
            )

    turn_id = f"turn-cancel-race-{'rhythm' if segmented else 'final'}"
    await _create_admitted_user_turn(chat_store, turn_id=turn_id)
    context, result = _plain_non_streamed_context_and_result(turn_id=turn_id)
    assert isinstance(context.latest_fact, FactRecord)
    if source_has_delivery_identity:
        context.latest_fact.delivery_attempt_no = 0
        context.latest_fact.runtime_command_id = 101
    event_emitter = _FakeEventEmitter()
    assembler = _FakeContextAssembler()
    seam_calls: list[str] = []
    scheduled_memory_updates: list[dict[str, Any]] = []

    async def _fake_seam(context, *, content):  # type: ignore[no-untyped-def]
        _ = context
        seam_calls.append(content.text)
        return DeliveryFanoutResult()

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=assembler,  # type: ignore[arg-type]
        get_event_emitter=lambda: event_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        response_rhythm_planner=_StaticRhythmPlanner(),
        deliver_final_response=_fake_seam,
        max_fact_memory=10,
    )
    service._schedule_background_memory_updates = (  # type: ignore[method-assign]
        lambda **kwargs: scheduled_memory_updates.append(dict(kwargs))
    )
    original_observability = service._emit_chat_response_observability

    async def _cancel_after_preflight(
        current_context,
        current_result,
        prepared,
    ):
        await original_observability(
            current_context,
            current_result,
            prepared,
        )
        assert await chat_store.cancel_user_turn_delivery_if_active(
            turn_id=turn_id,
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            reason="user_cancel",
            updated_at_ms=1710000000500,
        )

    service._emit_chat_response_observability = (  # type: ignore[method-assign]
        _cancel_after_preflight
    )

    outcome = await service.handle(context, result)

    turn = await chat_store.get_turn(turn_id)
    delivery = await chat_store.get_user_turn_delivery(turn_id=turn_id)
    visible_messages = [
        message
        for message in await chat_store.list_messages(session_id="session-1")
        if message.is_visible
    ]
    assert outcome.emitted is False
    assert turn is not None
    assert turn.status == "cancelled"
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert [message.message_kind for message in visible_messages] == ["user_text"]
    assert seam_calls == []
    assert event_emitter.chat_response_events == []
    assert assembler.history == []
    assert scheduled_memory_updates == []


@pytest.mark.asyncio
async def test_durable_outcome_wins_before_late_cancel(
    chat_store: ChatStore,
) -> None:
    turn_id = "turn-outcome-wins-race"
    await _create_admitted_user_turn(chat_store, turn_id=turn_id)
    context, result = _plain_non_streamed_context_and_result(turn_id=turn_id)
    assert isinstance(context.latest_fact, FactRecord)
    context.latest_fact.delivery_attempt_no = 0
    context.latest_fact.runtime_command_id = 101
    seam_calls: list[str] = []

    async def _fake_seam(context, *, content):  # type: ignore[no-untyped-def]
        _ = context
        seam_calls.append(content.text)
        return DeliveryFanoutResult()

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        deliver_final_response=_fake_seam,
        max_fact_memory=10,
    )
    original_persist = service._persist_chat_response_outcome

    async def _cancel_after_outcome_commit(
        current_context,
        current_result,
        prepared,
    ):
        accepted = await original_persist(
            current_context,
            current_result,
            prepared,
        )
        assert accepted
        assert not await chat_store.cancel_user_turn_delivery_if_active(
            turn_id=turn_id,
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            reason="user_cancel",
            updated_at_ms=1710000000600,
        )
        return accepted

    service._persist_chat_response_outcome = (  # type: ignore[method-assign]
        _cancel_after_outcome_commit
    )

    outcome = await service.handle(context, result)

    turn = await chat_store.get_turn(turn_id)
    delivery = await chat_store.get_user_turn_delivery(turn_id=turn_id)
    final = await chat_store.get_latest_message_for_turn(
        turn_id,
        message_kind="assistant_final",
    )
    assert outcome.emitted is True
    assert turn is not None
    assert turn.status == "completed"
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
    assert final is not None
    assert final.content_text == "final answer"
    assert seam_calls == ["final answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response_mode", ["none", "reaction_only"])
async def test_durable_cancel_blocks_no_message_completion(
    chat_store: ChatStore,
    response_mode: str,
) -> None:
    turn_id = f"turn-cancel-no-message-{response_mode}"
    await _create_admitted_user_turn(chat_store, turn_id=turn_id)
    assert await chat_store.cancel_user_turn_delivery_if_active(
        turn_id=turn_id,
        run_id="run-1",
        run_revision=0,
        reason="user_cancel",
        updated_at_ms=1710000000500,
    )
    context, result = _plain_non_streamed_context_and_result(turn_id=turn_id)
    result.response_text = ""
    result.skip_emit = True
    result.ux_plan = {"assistant_surface_mode": response_mode}
    completed_runs: list[tuple[str, str, int]] = []
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        complete_session_run=lambda session_id, run_id, revision: (
            completed_runs.append((session_id, run_id, revision))
        ),
        resolve_session_run_status=lambda _session_id, _run_id, _revision: "running",
        max_fact_memory=10,
    )

    outcome = await service.handle(context, result)

    turn = await chat_store.get_turn(turn_id)
    assert outcome.emitted is False
    assert turn is not None
    assert turn.status == "cancelled"
    assert completed_runs == []


@pytest.mark.asyncio
async def test_cancelled_outcome_does_not_leak_response_trace(
    chat_store: ChatStore,
    runtime_trace_store: RuntimeTraceStore,
    trace_event_bus,
) -> None:
    class _StaticRhythmPlanner:
        async def plan(self, **_kwargs):  # type: ignore[no-untyped-def]
            return AssistantResponsePlan(
                mode="multi_message",
                aggregate_text="private rejected answer",
                segments=[
                    AssistantResponseSegment(
                        content="private rejected",
                        delay_ms=0,
                        segment_index=0,
                        source_unit_ids=["u1"],
                    ),
                    AssistantResponseSegment(
                        content="answer",
                        delay_ms=0,
                        segment_index=1,
                        source_unit_ids=["u2"],
                    ),
                ],
            )

    turn_id = "turn-cancel-trace-race"
    await _create_admitted_user_turn(chat_store, turn_id=turn_id)
    context, result = _plain_non_streamed_context_and_result(turn_id=turn_id)
    result.response_text = "private rejected answer"
    result.llm_trace = {
        "provider": "openai",
        "model": "gpt-test",
        "input_tokens": 10,
        "output_tokens": 5,
    }
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        response_rhythm_planner=_StaticRhythmPlanner(),
        event_bus=trace_event_bus,
        max_fact_memory=10,
    )
    original_observability = service._emit_chat_response_observability

    async def _cancel_after_llm_observability(
        current_context,
        current_result,
        prepared,
    ):
        await original_observability(
            current_context,
            current_result,
            prepared,
        )
        assert await chat_store.cancel_user_turn_delivery_if_active(
            turn_id=turn_id,
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            reason="user_cancel",
            updated_at_ms=1710000000500,
        )
        await service.emit_cancelled_turn_trace(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            started_at_ms=1710000000000,
            cancelled_at_ms=1710000000500,
            user_message=context.latest_user_message,
            mode="direct_llm",
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            error_summary="user_cancel",
        )

    service._emit_chat_response_observability = (  # type: ignore[method-assign]
        _cancel_after_llm_observability
    )

    outcome = await service.handle(context, result)
    await trace_event_bus.drain()

    trace_turn = await runtime_trace_store.get_turn(turn_id)
    root_span = await runtime_trace_store.get_span(f"{turn_id}:turn")
    response_span = await runtime_trace_store.get_span(
        f"{turn_id}:response_emit"
    )
    rhythm_span = await runtime_trace_store.get_span(
        f"{turn_id}:rhythm_processing"
    )
    assert outcome.emitted is False
    assert trace_turn is not None
    assert trace_turn.status == "cancelled"
    assert trace_turn.response_preview is None
    assert root_span is not None
    assert root_span.status == "cancelled"
    assert response_span is None
    assert rhythm_span is None


@pytest.mark.parametrize("disposition", ["augment", "defer", "steer"])
@pytest.mark.asyncio
async def test_pending_fact_only_turn_stays_open_on_active_run(
    chat_store: ChatStore,
    disposition: str,
) -> None:
    coordinator = SessionRunCoordinator()
    coordinator._run_store.create_active_run(
        session_id="session-1",
        run_id="run-pending",
        root_turn_id="turn-root",
        root_user_message="Finish the original task",
    )
    coordinator._run_store.append_pending_turn(
        session_id="session-1",
        turn_id=f"turn-{disposition}",
        content="One more thing",
        disposition=disposition,
    )
    completion_calls: list[tuple[str, str, int]] = []
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        chat_store=chat_store,
        complete_session_run=lambda session_id, run_id, revision: completion_calls.append(
            (session_id, run_id, revision)
        ),
        resolve_session_run_status=lambda session_id, run_id, revision: coordinator.get_run_status(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        max_fact_memory=10,
    )
    turn_id = f"turn-{disposition}"
    latest_fact = FactRecord(
        agent_id="chat:local_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "One more thing",
            "user_id": "local_user",
            "session_id": "session-1",
            "turn_id": turn_id,
        },
        agent_type="chat",
        agent_instance_id="local_user",
        timestamp=1710000000.0,
        correlation_id=f"corr-{disposition}",
        delivery_attempt_no=0,
        runtime_command_id=101,
    )
    active_run = coordinator.get_active_run("session-1")
    assert active_run is not None
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
        session_run_id=active_run.run_id,
        session_run_revision=active_run.revision,
        session_run_disposition=disposition,
        active_run=active_run,
        latest_user_message="One more thing",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="One more thing",
            turn_id=turn_id,
        ),
    )
    await _create_admitted_user_turn(
        chat_store,
        turn_id=turn_id,
        message_text="One more thing",
        run_disposition=disposition,
    )
    result = ExecutionResult(
        mode=ExecutionMode.FACT_ONLY,
        response_text="",
        skip_emit=True,
        correlation_id=f"corr-{disposition}",
        turn_id=turn_id,
        ux_plan={"assistant_surface_mode": "none"},
    )

    await service.handle(context, result)

    turn = await chat_store.get_turn(turn_id)
    delivery = await chat_store.get_user_turn_delivery(turn_id=turn_id)
    still_active = coordinator.get_active_run("session-1")
    assert turn is not None
    assert turn.status != "completed"
    assert delivery is not None
    assert delivery.delivery_state == CHAT_DELIVERY_STATE_ADMITTED
    assert still_active is not None
    assert [item.turn_id for item in still_active.pending_turns] == [turn_id]
    assert completion_calls == []


@pytest.mark.asyncio
async def test_deferred_turn_is_released_after_old_run_completion() -> None:
    coordinator = SessionRunCoordinator()
    coordinator._run_store.create_active_run(
        session_id="session-1",
        run_id="run-root",
        root_turn_id="turn-root",
        root_user_message="Finish the original task",
    )
    coordinator._run_store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-deferred",
        content="Start this after the first task",
        disposition="defer",
    )
    active_run = coordinator.get_active_run("session-1")
    assert active_run is not None
    order: list[str] = []

    def _complete(
        session_id: str,
        run_id: str,
        revision: int,
    ):
        order.append("complete")
        return coordinator.complete_run_with_deferred(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        )

    async def _release(session_id: str, deferred_turns: list[Any]) -> None:
        order.append("release")
        assert coordinator.get_active_run(session_id) is None
        assert [turn.turn_id for turn in deferred_turns] == ["turn-deferred"]
        decision = coordinator.handle_user_turn(
            UserMessagePayload(
                user_id="local_user",
                session_id=session_id,
                content="Start this after the first task",
                turn_id="turn-deferred",
            )
        )
        assert decision.run_disposition == "root"

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        complete_session_run=_complete,
        resolve_session_run_status=lambda session_id, run_id, revision: coordinator.get_run_status(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        release_deferred_turns=_release,
        max_fact_memory=10,
    )
    context = SimpleNamespace(
        session_id="session-1",
        session_run_id=active_run.run_id,
        session_run_revision=active_run.revision,
        active_run=active_run,
        user_id="local_user",
        latest_payload=None,
        latest_fact=None,
        active_orchestrations=[],
    )

    await service._finalize_session_run(context)

    assert order == ["complete", "release"]
    next_run = coordinator.get_active_run("session-1")
    assert next_run is not None
    assert next_run.root_turn_id == "turn-deferred"


@pytest.mark.asyncio
async def test_deferred_turn_retries_failed_release_and_releases_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.chat.task_agent.postprocess.session as session_module

    monkeypatch.setattr(
        session_module,
        "_DEFERRED_RELEASE_RETRY_INITIAL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        session_module,
        "_DEFERRED_RELEASE_RETRY_MAX_SECONDS",
        0.01,
    )
    coordinator = SessionRunCoordinator()
    coordinator._run_store.create_active_run(
        session_id="session-retry",
        run_id="run-retry",
        root_turn_id="turn-root",
        root_user_message="Finish the original task",
    )
    coordinator._run_store.append_pending_turn(
        session_id="session-retry",
        turn_id="turn-deferred",
        content="Start this after the first task",
        disposition="defer",
    )
    active_run = coordinator.get_active_run("session-retry")
    assert active_run is not None

    release_calls: list[list[str]] = []
    release_attempts = 0
    released = asyncio.Event()

    async def _release(session_id: str, deferred_turns: list[Any]) -> None:
        nonlocal release_attempts
        assert session_id == "session-retry"
        release_attempts += 1
        if release_attempts == 1:
            raise RuntimeError("temporary ledger release failure")
        release_calls.append([turn.turn_id for turn in deferred_turns])
        released.set()

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        complete_session_run=lambda session_id, run_id, revision: coordinator.complete_run_with_deferred(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        resolve_session_run_status=lambda session_id, run_id, revision: coordinator.get_run_status(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        ),
        release_deferred_turns=_release,
        max_fact_memory=10,
    )
    context = SimpleNamespace(
        session_id="session-retry",
        session_run_id=active_run.run_id,
        session_run_revision=active_run.revision,
        active_run=active_run,
        user_id="local_user",
        latest_payload=None,
        latest_fact=None,
        active_orchestrations=[],
    )

    try:
        await service._finalize_session_run(context)
        # A duplicate finalization signal must not create a second retry batch.
        await service._finalize_session_run(context)
        assert release_calls == []
        await asyncio.wait_for(released.wait(), timeout=1.0)
        await asyncio.sleep(0.02)

        assert release_attempts == 2
        assert release_calls == [["turn-deferred"]]
        assert service._deferred_release_retry_keys == set()
    finally:
        await service.cancel_background_tasks()


@pytest.mark.asyncio
async def test_completed_run_without_deferred_turns_finishes_immediately() -> None:
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )

    try:
        completed = await service.release_deferred_after_run_completion(
            session_id="session-no-defer",
            run_id="run-no-defer",
            revision=0,
            deferred_turns=[],
        )

        assert completed is True
        assert service.has_pending_background_work() is False
    finally:
        await service.cancel_background_tasks()


@pytest.mark.asyncio
async def test_noncritical_background_work_does_not_pin_chat_session() -> None:
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    service._background_tasks.add(task)

    try:
        assert service.has_pending_background_work() is False
        service._deferred_release_retry_keys.add(("session-1", "run-1", 0))
        assert service.has_pending_background_work() is True
        service._deferred_release_retry_keys.clear()
        assert service.has_pending_background_work() is False
    finally:
        release.set()
        await service.cancel_background_tasks()


@pytest.mark.parametrize(
    ("segment_metadata", "expected_count", "is_complete"),
    [
        ([(0, 2), (1, 2)], 2, True),
        ([(1, 2), (0, 2)], 2, True),
        ([(0, 2)], 2, False),
        ([(0, 2), (0, 2)], 2, False),
        ([(0, 2), (1, 2), (2, 2)], 2, False),
        ([(0, 2), (2, 2)], 2, False),
        ([(0, 2), (1, 3)], None, False),
        ([(0, MAX_RHYTHM_SEGMENT_COUNT + 1)], None, False),
    ],
)
def test_complete_visible_rhythm_requires_exact_bounded_index_set(
    segment_metadata: list[tuple[int, int]],
    expected_count: int | None,
    is_complete: bool,
) -> None:
    messages = [
        ChatMessageRecord(
            message_id=f"segment-{position}",
            session_id="session-rhythm-validation",
            turn_id="turn-rhythm-validation",
            user_id="local_user",
            role="assistant",
            message_kind="assistant_rhythm_segment",
            content_text=f"part {segment_index}",
            payload_json=json.dumps(
                {
                    "rhythm": {
                        "segment_index": segment_index,
                        "segment_count": segment_count,
                    }
                }
            ),
            is_final=True,
            is_visible=True,
            created_at_ms=1710000000000 + position,
            sequence_no=position + 1,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        for position, (segment_index, segment_count) in enumerate(
            segment_metadata
        )
    ]

    complete = complete_visible_rhythm_segments(
        messages,
        turn_id="turn-rhythm-validation",
        expected_count=expected_count,
    )

    assert (complete is not None) is is_complete
    if complete is not None:
        assert [
            json.loads(message.payload_json or "{}")["rhythm"][
                "segment_index"
            ]
            for message in complete
        ] == list(range(len(complete)))


@pytest.mark.asyncio
async def test_first_context_story_stores_chat_but_skips_relationship_memory_updates():
    assembler = _FakeContextAssembler()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=assembler,  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )
    context, result = _plain_non_streamed_context_and_result(
        turn_id="turn-first-context"
    )
    context.latest_user_message = "还行"
    context.latest_payload = UserMessagePayload(
        user_id="local_user",
        session_id="session-1",
        content="还行",
        turn_id="turn-first-context",
        interaction_kind="first_context_story",
        first_context={
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    )
    result.root_user_message = "还行"
    scheduled: list[dict[str, object]] = []
    service._schedule_background_memory_updates = (  # type: ignore[method-assign]
        lambda **kwargs: scheduled.append(dict(kwargs))
    )
    prepared = SimpleNamespace(
        latest_fact=context.latest_fact,
        response_text="听起来今天比较平静。",
        history_stored=False,
        user_message=None,
        memory_updated=False,
    )

    await service._record_chat_history_and_memory(context, result, prepared)

    assert [item["role"] for item in assembler.history] == ["user", "assistant"]
    assert scheduled == []
    assert prepared.history_stored is True
    assert prepared.memory_updated is False


@pytest.mark.asyncio
async def test_committed_response_time_is_used_for_delayed_memory_enqueue():
    assembler = _FakeContextAssembler()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=assembler,  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        max_fact_memory=10,
    )
    context, result = _plain_non_streamed_context_and_result(
        turn_id="turn-delayed-memory-enqueue"
    )
    scheduled: list[dict[str, object]] = []
    service._schedule_background_memory_updates = (  # type: ignore[method-assign]
        lambda **kwargs: scheduled.append(dict(kwargs)) or True
    )
    committed_at_ms = 1710000000123
    prepared = SimpleNamespace(
        latest_fact=context.latest_fact,
        response_text="This response is already durable.",
        history_stored=False,
        user_message=None,
        memory_updated=False,
        segmented_messages=[
            SimpleNamespace(message_id="assistant-durable-1"),
        ],
        turn_id="turn-delayed-memory-enqueue",
        ux_plan={},
        now_ms=committed_at_ms,
    )

    await service._record_chat_history_and_memory(context, result, prepared)

    assert len(scheduled) == 1
    assert scheduled[0]["accepted_at"] == committed_at_ms / 1000.0


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
        return DeliveryFanoutResult()

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
async def test_handle_does_not_deliver_when_final_persistence_fails(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    """A channel must never receive a final answer without a local record."""

    seam_calls: list[dict[str, Any]] = []

    async def _fake_seam(context, *, content):
        seam_calls.append({"context": context, "content": content})
        return DeliveryFanoutResult()

    assembler = _FakeContextAssembler()
    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=assembler,  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
        deliver_final_response=_fake_seam,
    )
    context, result = _plain_non_streamed_context_and_result(
        turn_id="turn-persistence-failure"
    )

    async def _fail_persistence(*_args, **_kwargs):
        raise RuntimeError("simulated persistence failure")

    scheduled_memory_updates: list[dict[str, Any]] = []
    service._schedule_background_memory_updates = (  # type: ignore[method-assign]
        lambda **kwargs: scheduled_memory_updates.append(dict(kwargs))
    )
    service._persist_final_chat_outcome = _fail_persistence  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        await service.handle(context, result)

    assert seam_calls == []
    assert assembler.history == []
    assert scheduled_memory_updates == []


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
async def test_handle_streamed_delivers_final_to_external_channels_only(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
) -> None:
    """Streamed turns keep SSE chunks but send one durable final externally."""
    seam_calls: list[dict] = []

    async def _fake_seam(context, *, content, exclude_chat_sse=False):
        seam_calls.append(
            {
                "context": context,
                "content": content,
                "exclude_chat_sse": exclude_chat_sse,
            }
        )
        return DeliveryFanoutResult()

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

    assert len(seam_calls) == 1
    assert seam_calls[0]["content"].text == "Why did the chicken cross the road?"
    assert seam_calls[0]["exclude_chat_sse"] is True
    notifications = await runtime_trace_store.list_notifications(after_id=0)
    channels = [n.channel for n in notifications]
    assert "agent_response" not in channels, channels
    assert "execution_control" in channels, channels


@pytest.mark.asyncio
async def test_segmented_agent_response_routes_each_segment_through_seam(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    """Each rhythm segment uses the delivery seam with its own identity."""
    from types import SimpleNamespace

    seam_calls: list[Any] = []

    async def _fake_seam(context, *, content):
        seam_calls.append(content)
        return DeliveryFanoutResult()

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
        mode=None,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["reported", "raised"])
async def test_segmented_notification_failure_keeps_rhythm_without_duplicate_final(
    runtime_trace_store: RuntimeTraceStore,
    chat_store: ChatStore,
    failure_mode: str,
) -> None:
    from magi.delivery.contracts import (
        DeliveryFailure,
        DeliveryFanoutResult,
    )
    from magi_plugin_sdk.channels import ChannelTarget
    from magi_plugin_sdk.delivery import DeliveryReceipt

    class _StaticRhythmPlanner:
        async def plan(self, **_kwargs):  # type: ignore[no-untyped-def]
            return AssistantResponsePlan(
                mode="multi_message",
                aggregate_text="first part second part",
                segments=[
                    AssistantResponseSegment(
                        content="first part",
                        delay_ms=0,
                        segment_index=0,
                        source_unit_ids=["u1"],
                    ),
                    AssistantResponseSegment(
                        content="second part",
                        delay_ms=0,
                        segment_index=1,
                        source_unit_ids=["u2"],
                    ),
                ],
            )

    telegram_target = ChannelTarget(
        channel_type="telegram",
        external_chat_id="",
        magi_session_id="session-1",
        magi_user_id="local_user",
    )
    seam_calls: list[dict[str, Any]] = []

    async def _partially_failing_seam(
        context,
        *,
        content,
        exclude_channel_types=(),
    ):
        seam_calls.append(
            {
                "content": content,
                "excluded": tuple(exclude_channel_types),
            }
        )
        receipt = DeliveryReceipt(
            channel_id="chat_sse",
            external_message_id=None,
            delivered_at_ms=100 + len(seam_calls),
            magi_session_id=context.session_id,
        )
        if failure_mode == "reported" and len(seam_calls) == 1:
            return DeliveryFanoutResult(
                receipts=(receipt,),
                failures=(
                        DeliveryFailure(
                            target=telegram_target,
                            error=RuntimeError("telegram unavailable"),
                            delivery_attempted=True,
                        ),
                    ),
            )
        if failure_mode == "raised" and len(seam_calls) == 2:
            raise RuntimeError("delivery failed after the first segment")
        return DeliveryFanoutResult(receipts=(receipt,))

    service = ChatPostProcessService(
        agent_id="chat:local_user",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: _FakeEventEmitter(),
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        chat_store=chat_store,
        max_fact_memory=10,
        response_rhythm_planner=_StaticRhythmPlanner(),
        deliver_final_response=_partially_failing_seam,
    )
    await chat_store.create_user_turn(
        session_id="session-1",
        user_id="local_user",
        turn_id="turn-partial-channel",
        message_text="explain rhythm",
        created_at_ms=1710000000000,
    )
    context, result = _plain_non_streamed_context_and_result(
        turn_id="turn-partial-channel"
    )
    result.response_text = "first part second part"

    await service.handle(context, result)

    visible_messages = [
        message
        for message in await chat_store.list_messages(session_id="session-1")
        if message.is_visible
    ]
    assert [message.message_kind for message in visible_messages] == [
        "user_text",
        "assistant_rhythm_segment",
        "assistant_rhythm_segment",
    ]
    assert [
        call["content"].message_kind for call in seam_calls
    ] == [
        "assistant_rhythm_segment",
        "assistant_rhythm_segment",
    ]
    assert seam_calls[0]["excluded"] == ()
    assert seam_calls[1]["excluded"] == (
        ("telegram",) if failure_mode == "reported" else ()
    )
    notifications = await runtime_trace_store.list_notifications(after_id=0)
    controls = [item for item in notifications if item.channel == "execution_control"]
    assert len(controls) == 1
    assert json.loads(controls[0].payload_json)["state"] == "completed"
    assert json.loads(controls[0].payload_json)["turn_id"] == "turn-partial-channel"
