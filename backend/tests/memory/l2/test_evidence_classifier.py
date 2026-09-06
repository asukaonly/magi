from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
    normalize_runtime_event,
)


def _build_user_message(*, message: str = "I like sushi.", metadata: dict | None = None):
    return Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "user_id": "u1",
            "session_id": "s1",
            "content": message,
            "author_type": "user",
            "content_type": "text",
        },
        source="chat",
        level=EventLevel.INFO,
        correlation_id="evt-user-1",
        metadata={"user_id": "u1", **(metadata or {})},
        timestamp=1710000000.0,
    )


def _build_ai_response(*, text: str = "You like sushi.", metadata: dict | None = None):
    return Event(
        type=EventTypes.AI_RESPONSE,
        data={
            "user_id": "u1",
            "session_id": "s1",
            "content": text,
            "author_type": "assistant",
            "content_type": "text",
        },
        source="assistant",
        level=EventLevel.INFO,
        correlation_id="evt-ai-1",
        metadata={"user_id": "u1", **(metadata or {})},
        timestamp=1710000001.0,
    )


def _build_external_observation(*, summary: str = "Calendar shows a meeting tomorrow."):
    return MemoryEvent(
        event_id="evt-timeline-1",
        correlation_id="evt-timeline-1",
        timestamp=1710000002.0,
        created_at=1710000002.0,
        event_type="SOURCE_EVENT",
        source="calendar",
        source_item_id="calendar:item-1",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id="u1",
        task_id=None,
        content=summary,
        author_type="external",
        content_type="observation",
        importance_score=0.75,
        level=EventLevel.INFO.value,
    )


def _build_history_document(
    *,
    content: str,
    event_type: str = "history_import.document",
    source: str = "history_import",
    historical: bool = True,
) -> MemoryEvent:
    return MemoryEvent(
        event_id="evt-history-document-1",
        correlation_id="history-import:job-1",
        timestamp=1710000002.0,
        created_at=1710000002.0,
        event_type=event_type,
        source=source,
        source_item_id="record-1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id="history-session-1",
        turn_id=None,
        user_id="u1",
        task_id=None,
        content=content,
        author_type="user",
        content_type="text",
        importance_score=0.72,
        level=EventLevel.INFO.value,
        metadata_json={"history_import": {"historical": historical}},
    )


def _build_runtime_event():
    return Event(
        type=EventTypes.TASK_COMPLETED,
        data={"task_id": "task-1"},
        source="system",
        level=EventLevel.INFO,
        correlation_id="evt-runtime-1",
        metadata={"memory_domain": "runtime_telemetry"},
        timestamp=1710000003.0,
    )


def test_normalized_event_defaults_user_evidence_metadata():
    memory_event = normalize_runtime_event(_build_user_message())

    assert memory_event.author_type == "user"
    assert memory_event.content_type == "text"


def test_normalized_event_defaults_assistant_evidence_metadata():
    memory_event = normalize_runtime_event(_build_ai_response())

    assert memory_event.author_type == "assistant"
    assert memory_event.content_type == "text"


def test_normalized_event_defaults_external_observation_metadata():
    memory_event = _build_external_observation()

    assert memory_event.author_type == "external"
    assert memory_event.content_type == "observation"


def test_normalized_event_defaults_runtime_metadata():
    memory_event = normalize_runtime_event(_build_runtime_event())

    assert memory_event.author_type == "system"
    assert memory_event.content_type == "text"


def test_classifier_maps_user_self_report():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_user_message()))

    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "user_default"


def test_classifier_maps_user_question_english_wh_word():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message="What time is the meeting?"))
    )

    assert classification.evidence_class == "user_question"
    assert classification.reason_code == "user_question_lead_or_mark"


def test_classifier_maps_user_question_trailing_mark_only():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message="I have a doubt."))
    )

    assert classification.evidence_class == "user_self_report"

    classification_with_mark = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message="I have a doubt?"))
    )

    assert classification_with_mark.evidence_class == "user_question"


def test_classifier_maps_user_question_chinese_yes_no_particle():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message="今天会下雨吗"))
    )

    assert classification.evidence_class == "user_question"


def test_classifier_maps_user_request_chinese_imperative_lead():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message="请帮我把这段翻译成英文。"))
    )

    assert classification.evidence_class == "user_request"
    assert classification.reason_code == "user_request_imperative_lead"


def test_classifier_maps_user_request_english_please_lead():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message="Please summarize the meeting notes."))
    )

    assert classification.evidence_class == "user_request"


@pytest.mark.parametrize(
    "content",
    [
        "How did pottery change me?",
        "Please remember that I practiced pottery every Sunday.",
    ],
)
def test_classifier_prioritizes_exact_history_document_contract(content):
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(_build_history_document(content=content))

    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "user_authored_history_archive"


@pytest.mark.parametrize(
    "event",
    [
        _build_history_document(
            content="How did pottery change me?",
            source="chat",
        ),
        _build_history_document(
            content="How did pottery change me?",
            historical=False,
        ),
    ],
)
def test_classifier_does_not_apply_document_rule_to_near_misses(event):
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(event)

    assert classification.evidence_class == "user_question"
    assert classification.reason_code == "user_question_lead_or_mark"


def test_classifier_treats_archived_user_chat_question_as_self_report() -> None:
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        _build_history_document(
            content="How did pottery change me?",
            event_type="history_import.chat",
        )
    )

    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "user_authored_history_archive"


def test_user_question_policy_blocks_l2_writes():
    from magi.memory.evidence import (
        EvidenceClass,
        EvidenceClassification,
        resolve_l2_policy,
    )

    decision = resolve_l2_policy(
        EvidenceClassification(
            evidence_class=EvidenceClass.USER_QUESTION.label,
            reason_code="user_question_lead_or_mark",
        )
    )

    assert decision.allow_graph_write is False
    assert decision.allow_assertion_write is False
    assert decision.allow_entity_extraction is False
    assert decision.count_as_new_evidence is False
    assert decision.l1_retrieval_scope == "conversation_only"
    assert decision.skip_reason == "user_question"


def test_user_request_policy_blocks_l2_writes():
    from magi.memory.evidence import (
        EvidenceClass,
        EvidenceClassification,
        resolve_l2_policy,
    )

    decision = resolve_l2_policy(
        EvidenceClassification(
            evidence_class=EvidenceClass.USER_REQUEST.label,
            reason_code="user_request_imperative_lead",
        )
    )

    assert decision.allow_graph_write is False
    assert decision.allow_assertion_write is False
    assert decision.allow_entity_extraction is False
    assert decision.count_as_new_evidence is False
    assert decision.l1_retrieval_scope == "conversation_only"
    assert decision.skip_reason == "user_request"


def test_classifier_maps_assistant_tool_grounded():
    from magi.memory.evidence import classify_event_evidence

    event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "Weather says rain tomorrow.",
                "author_type": "assistant",
                "content_type": "tool_result",
            },
            source="assistant",
            level=EventLevel.INFO,
            correlation_id="evt-ai-tool-1",
            metadata={"user_id": "u1"},
            timestamp=1710000001.0,
        )
    )

    classification = classify_event_evidence(event)

    assert classification.evidence_class == "assistant_tool_grounded"
    assert classification.reason_code == "assistant_content_type"


def test_classifier_maps_assistant_freeform():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_ai_response()))

    assert classification.evidence_class == "assistant_freeform"
    assert classification.reason_code == "assistant_default"


def test_classifier_maps_external_observation():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(_build_external_observation())

    assert classification.evidence_class == "external_observation"
    assert classification.reason_code == "external_source"


def test_classifier_maps_system_runtime():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_runtime_event()))

    assert classification.evidence_class == "system_runtime"
    assert classification.reason_code == "runtime_domain"


def _build_chat_response_action_event():
    return Event(
        type="ActionExecuted",
        data={
            "content": "懂你，这种天气确实烦。",
            "author_type": "tool",
            "content_type": "tool_result",
            "action_type": "ChatResponseAction",
            "user_id": "local_user",
            "session_id": "s1",
            "turn_id": "turn-1",
            "success": True,
        },
        source="runtime_event_emitter",
        level=EventLevel.INFO,
        correlation_id="evt-runtime-chat-1",
        timestamp=1710000004.0,
    )


def test_classifier_maps_assistant_runtime_derivation():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_chat_response_action_event())
    )

    assert classification.evidence_class == "assistant_runtime_derivation"
    assert classification.reason_code == "runtime_chat_response_action"


def test_normalize_promotes_chat_response_action_to_assistant_runtime_derivation():
    """ChatResponseAction normalize override sets the runtime_derivation shape.

    The evidence governance contract treats a runtime-emitted ChatResponseAction
    as assistant speech (``conversation_only`` retrieval scope) rather than as
    a tool result. Normalize must materialize that shape directly so the
    classifier and downstream consumers do not have to re-detect it from
    ``event_type`` / ``source`` / ``source_item_id``.
    """
    memory_event = normalize_runtime_event(_build_chat_response_action_event())

    assert memory_event.author_type == "assistant"
    assert memory_event.content_type == "runtime_derivation"


def test_classifier_external_plugin_source_classifies_as_external_observation():
    """Plugin-supplied sources land in external_observation via author_type.

    The classifier no longer carries a hand-maintained source-name allowlist;
    the only signal it consults for external/source events is ``author_type``,
    which ``normalize_runtime_event`` already sets correctly for plugin
    emitters regardless of the exact source label.
    """
    from magi.events.events import Event, EventLevel
    from magi.memory.evidence import classify_event_evidence

    event = Event(
        type="SOURCE_EVENT",
        data={"user_id": "u1", "summary": "Chrome visit"},
        source="chrome_history",
        level=EventLevel.INFO,
        correlation_id="evt-plugin-chrome-1",
        timestamp=1710000050.0,
    )
    classification = classify_event_evidence(normalize_runtime_event(event))

    assert classification.evidence_class == "external_observation"
    assert classification.reason_code == "external_source"


def test_classifier_evidence_rule_version_is_six():
    """Bumping EVIDENCE_RULE_VERSION triggers stale-row backfill.

    The version is part of the L1 backfill contract: any rule semantics
    change must bump this constant so existing rows are re-classified.
    """
    from magi.memory.evidence import EVIDENCE_RULE_VERSION

    assert EVIDENCE_RULE_VERSION == 6


@pytest.mark.parametrize(
    "message",
    [
        "杭州天气怎么样",  # interrogative at clause end, no mark
        "我要怎么配",  # "怎么" mid-sentence
        "我chrome最近在看什么呀",  # "什么" + trailing mood particle
        "这个多少钱",  # "多少" anywhere
        "你在哪",  # "哪" at end
        "为什么会这样",  # "为什么" lead (already covered, keep as guard)
    ],
)
def test_classifier_maps_chinese_spoken_questions(message):
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message=message))
    )
    assert classification.evidence_class == "user_question", message


@pytest.mark.parametrize(
    "message",
    [
        "我有一只猫",  # plain statement, no interrogative
        "没什么特别的",  # "什么" inside a non-question idiom
        "我知道为什么了",  # "为什么" inside "知道为什么"
        "什么都行",  # "什么" inside "什么都"
        "我喜欢喝咖啡",  # plain preference statement
        "不知道怎么办",  # "怎么" inside "不知道怎么"
        "哪里哪里，您过奖了",  # modesty reply, "哪里" inside "哪里哪里" blacklist
    ],
)
def test_classifier_keeps_chinese_statements_as_self_report(message):
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message=message))
    )
    assert classification.evidence_class == "user_self_report", message


# ---------------------------------------------------------------------------
# Speech-act boundary regression net (characterizes current correct behavior)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "message,expected",
    [
        # --- Chinese questions (must be user_question) ---
        ("你最近在忙什么", "user_question"),
        ("这个多少钱啊", "user_question"),
        ("会议改到几点", "user_question"),
        ("为什么会这样", "user_question"),
        ("你在哪", "user_question"),
        ("今天会下雨吗", "user_question"),
        # --- Chinese requests (must be user_request) ---
        ("帮我订个会议室", "user_request"),
        ("请把报告发我", "user_request"),
        ("告诉我结果", "user_request"),
        # --- Chinese statements (must stay user_self_report) ---
        ("我今天有点累", "user_self_report"),
        ("反正没什么大事", "user_self_report"),
        ("我不知道为什么", "user_self_report"),
        ("我喜欢喝咖啡", "user_self_report"),
        ("我们怎么都行", "user_self_report"),
        # --- English questions ---
        ("which one is better", "user_question"),
        ("how do I reset it", "user_question"),
        ("is it ready?", "user_question"),
        # --- English requests ---
        ("please summarize this", "user_request"),
        ("can you help me", "user_request"),
        # --- English statements ---
        ("I have two cats", "user_self_report"),
        ("I really like sushi", "user_self_report"),
    ],
)
def test_classifier_speech_act_boundaries(message, expected):
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(
        normalize_runtime_event(_build_user_message(message=message))
    )
    assert (
        classification.evidence_class == expected
    ), f"{message!r} -> {classification.evidence_class}"


def _classify_first_context(message: str):
    from magi.memory.evidence import classify_event_evidence

    event = normalize_runtime_event(_build_user_message(message=message))
    event.metadata_json = {
        "interaction_kind": "first_context_story",
        "first_context": {
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    }
    return classify_event_evidence(event)


def test_first_context_mixed_self_report_and_question_keeps_self_report_evidence():
    classification = _classify_first_context("我最近失恋了，你能陪我聊聊吗？")

    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "first_context_story_with_self_report"


@pytest.mark.parametrize(
    "message",
    [
        "最近总在听周杰伦，你喜欢吗？",
        "还行，你呢？",
    ],
)
def test_first_context_answer_clause_wins_over_trailing_question(message):
    classification = _classify_first_context(message)

    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "first_context_story_with_self_report"


def test_first_context_pure_question_stays_conversation_only():
    from magi.memory.evidence import resolve_l2_policy

    classification = _classify_first_context("你能陪我聊聊吗？")
    policy = resolve_l2_policy(classification)

    assert classification.evidence_class == "user_question"
    assert policy.allow_graph_write is False
    assert policy.allow_assertion_write is False


def test_first_context_identity_question_stays_conversation_only():
    from magi.memory.evidence import resolve_l2_policy

    classification = _classify_first_context("你是谁？")
    policy = resolve_l2_policy(classification)

    assert classification.evidence_class == "user_question"
    assert policy.allow_graph_write is False
    assert policy.allow_assertion_write is False


@pytest.mark.parametrize("message", ["123", "asdf", "qwerty", "随便"])
def test_first_context_low_signal_input_cannot_write_l2(message):
    from magi.memory.evidence import resolve_l2_policy

    classification = _classify_first_context(message)
    policy = resolve_l2_policy(classification)

    assert classification.evidence_class == "user_request"
    assert classification.reason_code == "first_context_story_low_signal"
    assert policy.l1_retrieval_scope == "conversation_only"
    assert policy.allow_entity_extraction is False
    assert policy.allow_graph_write is False
    assert policy.allow_assertion_write is False


@pytest.mark.parametrize("text,expected", [
    ("我喜欢爵士乐，你推荐什么？", "user_self_report"),
    ("我住在杭州。你推荐什么？", "user_self_report"),
    ("我喜欢爵士乐吗？", "user_question"),
    ("如果我喜欢爵士乐，你推荐什么？", "user_question"),
    ('他说“我喜欢爵士乐”，你推荐什么？', "user_question"),
])
def test_mixed_message_preserves_only_asserted_self_report(text, expected):
    from magi.memory.evidence import classify_event_evidence
    event = normalize_runtime_event(_build_user_message(message=text))
    assert classify_event_evidence(event).evidence_class == expected
