"""Conversation recall must preserve proposals and their actual speakers."""

from dataclasses import asdict

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.recall_rendering import aggregate_by_statement
from magi.memory.retrieval_projection import project_historical_recall
from magi.memory.tool_context_historical import compact_historical_recall


def _event(event_id, content, author, evidence_class, timestamp):
    return {
        "event_id": event_id,
        "content": content,
        "author_type": author,
        "evidence_class": evidence_class,
        "source": "chat",
        "session_id": "previous-session",
        "timestamp": timestamp,
        "retrieval_score": 0.8,
    }


def _recall(events, mode):
    return project_historical_recall(
        payload=RetrievalPayload(l1_events=events),
        request=RetrievalQuery(
            query="接着聊家庭账单那个安排，恢复上次的三个步骤和第一周的安排",
            user_id="local_user",
            session_id=None,
            time_range={},
            query_mode=mode,
        ),
    )


@pytest.mark.parametrize("mode", ["episode_recall", "experience_recall", "event_stream"])
def test_resume_plan_preserves_assistant_proposal_and_user_acceptance(mode):
    proposal = "三步流程：1. 攒票；2. 归类；3. 看一眼。第一周只攒票，不用分类，不用算钱。"
    acceptance = "这个家庭账单流程可以，就采用你刚才那三个步骤和名字。第一周只做第一步，用手机备忘录。"
    recall = _recall([
        _event("proposal", proposal, "assistant", "assistant_freeform", 100),
        _event("acceptance", acceptance, "user", "user_self_report", 200),
    ], mode)

    assert {f["feedback_ref"] for f in recall.findings} == {"event:proposal", "event:acceptance"}
    by_id = {f["feedback_ref"]: f for f in recall.findings}
    assert by_id["event:proposal"]["author_type"] == "assistant"
    assert by_id["event:acceptance"]["author_type"] == "user"
    assert all(f["evidence_semantics"] == "historical_record" for f in recall.findings)
    rendered = compact_historical_recall(asdict(recall), max_items=10, max_text_chars=2000)
    assert proposal in rendered
    assert acceptance in rendered
    assert "speaker=assistant" in rendered
    assert "speaker=user" in rendered
    assert "not user decisions" in rendered


@pytest.mark.parametrize("mode", ["exact_fact", "current_state", "cross_session", "temporal_compare", "summary", "strategy"])
def test_fact_recall_still_excludes_conversation_artifacts(mode):
    events = [
        _event("proposal", "你可以每晚分类账单。", "assistant", "assistant_freeform", 100),
        _event("question", "每晚分类账单好吗？", "user", "user_question", 110),
        _event("request", "朋友说：每晚分类账单。帮我分析这句话。", "user", "user_request", 120),
        _event("decision", "我决定先只收集账单，用手机备忘录。", "user", "user_self_report", 200),
    ]
    recall = _recall(events, mode)
    assert [f["feedback_ref"] for f in recall.findings] == ["event:decision"]


def test_matching_words_do_not_merge_speakers_or_conversation_turns():
    statement = "每晚归类账单。"
    recall = _recall([
        _event("proposal", statement, "assistant", "assistant_freeform", 100),
        _event("user", statement, "user", "user_self_report", 200),
        _event("repeat", statement, "assistant", "assistant_freeform", 300),
    ], "episode_recall")
    aggregated = aggregate_by_statement(recall.findings)
    assert [(f["author_type"], f["occurred_at"]) for f in aggregated] == [
        ("assistant", 100), ("user", 200), ("assistant", 300),
    ]


def test_assistant_only_recall_is_not_summarized_as_a_user_decision():
    recall = _recall([
        _event("proposal", "每晚归类账单。", "assistant", "assistant_freeform", 100),
    ], "episode_recall")
    assert recall.summary == "当时助手说：每晚归类账单。"


def test_conversation_recall_preserves_quoted_request_without_promoting_it():
    quoted_request = "朋友说：每天花两小时分类账单。那是他的做法，帮我分析，不代表我采用。"
    recall = _recall([
        _event("quote", quoted_request, "user", "user_request", 100),
        _event("runtime", "Internal task status", "system", "system_runtime", 200),
    ], "episode_recall")
    assert [f["feedback_ref"] for f in recall.findings] == ["event:quote"]
    assert recall.findings[0]["evidence_semantics"] == "historical_record"
    rendered = compact_historical_recall(asdict(recall), max_items=10, max_text_chars=2000)
    assert quoted_request in rendered
    assert "evidence=user_request" in rendered
    assert "quoted third-party statements are not user self-reports" in rendered


def test_conversation_recall_does_not_use_current_question_as_evidence():
    question = "接着聊家庭账单那个安排，恢复上次的三个步骤和第一周的安排"
    recall = _recall([
        _event("current", question, "user", "user_question", 100),
    ], "episode_recall")
    assert recall.findings == []
    assert recall.status == "not_found"
