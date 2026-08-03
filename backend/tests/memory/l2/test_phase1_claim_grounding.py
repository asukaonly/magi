"""Tests for deterministic Phase 1 claim evidence grounding."""

import pytest

from magi.memory.l2.models import (
    L2BatchEvent,
    L2ClaimEvidenceMode,
    L2EventWindow,
    L2Phase1FactClaim,
    L2Phase1Result,
)
from magi.memory.l2.pipeline.claim_grounding import (
    ground_phase1_fact_claims,
    normalize_phase1_claim_contract,
)
from magi.memory.l2.pipeline.claim_persistence import _evidence_locator


def _window(*events: tuple[str, str]) -> L2EventWindow:
    return L2EventWindow(
        events=[
            L2BatchEvent(event_id=event_id, content=content)
            for event_id, content in events
        ]
    )


def _claim(**overrides: object) -> L2Phase1FactClaim:
    payload: dict[str, object] = {
        "subject_ref": "user:self",
        "predicate": "LIKES",
        "object_ref": "DIIV",
        "object_type": "group",
        "evidence_text": "我很喜欢 DIIV",
        "supporting_event_ids": [],
    }
    payload.update(overrides)
    return L2Phase1FactClaim.from_dict(payload)


def _history_window(
    content: str,
    *,
    event_type: str = "history_import.document",
) -> L2EventWindow:
    return L2EventWindow(
        events=[
            L2BatchEvent(
                event_id="evt-history",
                content=content,
                source="history_import_markdown",
                event_type=event_type,
                author_type="user",
            )
        ]
    )


def test_ground_phase1_claim_binds_quote_to_exact_event() -> None:
    result = L2Phase1Result(
        fact_claims=[_claim(supporting_event_ids=["evt-wrong", "evt-outside"])]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(
            ("evt-a", "昨晚去看了 DIIV 演出，我很喜欢 DIIV。"),
            ("evt-b", "今天修复了项目里的测试。"),
        ),
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 1}
    assert result.fact_claims[0].supporting_event_ids == ["evt-a"]
    assert result.fact_claims[0].claim_id.startswith("claim:")


def test_ground_phase1_claim_uses_frozen_window_text() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="I have been really stressed about work lately.",
            )
        ]
    )
    window = L2EventWindow(
        events=[L2BatchEvent(event_id="evt-a", content="")],
        texts=["I have been really stressed about work lately."],
    )

    stats = ground_phase1_fact_claims(result, window)

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-a"]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            "> 我很喜欢 DIIV。\n",
            id="blockquote",
        ),
        pytest.param(
            "- > 我很喜欢 DIIV。\n",
            id="list_nested_blockquote",
        ),
        pytest.param(
            "```text\n我很喜欢 DIIV。\n```\n",
            id="backtick_fence",
        ),
        pytest.param(
            "- Notes\n    ```text\n    我很喜欢 DIIV。\n    ```\n",
            id="list_indented_fence",
        ),
        pytest.param(
            "~~~text\n我很喜欢 DIIV。\n~~~\n",
            id="tilde_fence",
        ),
        pytest.param(
            "```text\n我很喜欢 DIIV。\n仍然没有闭合 fence。",
            id="unclosed_fence",
        ),
    ],
)
def test_history_document_rejects_non_author_markdown_occurrences(
    content: str,
) -> None:
    result = L2Phase1Result(
        fact_claims=[_claim(evidence_text="我很喜欢 DIIV。")]
    )

    stats = ground_phase1_fact_claims(result, _history_window(content))

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []


def test_history_document_contract_normalizer_rejects_quoted_evidence() -> None:
    payload: dict[str, object] = {
        "fact_claims": [
            {
                "subject_ref": "user:self",
                "predicate": "LIKES",
                "object_ref": "DIIV",
                "object_type": "group",
                "evidence_text": "I really like DIIV.",
                "supporting_event_ids": ["evt-history"],
            }
        ]
    }

    normalizations = normalize_phase1_claim_contract(
        payload,
        _history_window("> I really like DIIV.\n"),
    )

    assert payload["fact_claims"] == []
    assert payload["diagnostics"] == {"rejected_fact_claim_count": 1}
    assert any("missing exact current evidence" in item for item in normalizations)


def test_history_document_allows_normal_occurrence_when_quote_matches_too() -> None:
    evidence = "I really like DIIV."
    normal_occurrence = "I   REALLY like DIIV."
    content = f"> {evidence}\n\n## Recent listening\n{normal_occurrence}\n"
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=evidence)])

    stats = ground_phase1_fact_claims(result, _history_window(content))
    locator = _evidence_locator(
        content,
        evidence,
        event_type="history_import.document",
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]
    assert locator["start"] == content.index(normal_occurrence)
    assert locator["end"] == content.index(normal_occurrence) + len(normal_occurrence)


def test_history_document_keeps_frontmatter_and_heading_occurrences() -> None:
    content = (
        "---\n"
        "title: Personal Notes\n"
        "preference: concise answers\n"
        "---\n"
        "# I prefer concise answers\n"
        "Ordinary author prose follows.\n"
    )
    result = L2Phase1Result(
        fact_claims=[
            _claim(evidence_text="preference: concise answers"),
            _claim(evidence_text="# I prefer concise answers"),
        ]
    )

    stats = ground_phase1_fact_claims(result, _history_window(content))

    assert stats == {"kept": 2, "rejected": 0, "rebound": 0}
    assert [claim.supporting_event_ids for claim in result.fact_claims] == [
        ["evt-history"],
        ["evt-history"],
    ]


def test_history_document_keeps_ordinary_list_prose() -> None:
    result = L2Phase1Result(
        fact_claims=[_claim(evidence_text="I prefer concise answers.")]
    )

    stats = ground_phase1_fact_claims(
        result,
        _history_window("- I prefer concise answers.\n"),
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]


def test_non_document_event_keeps_existing_markdown_grounding_behavior() -> None:
    result = L2Phase1Result(
        fact_claims=[_claim(evidence_text="我很喜欢 DIIV。")]
    )

    stats = ground_phase1_fact_claims(
        result,
        _history_window(
            "```text\n我很喜欢 DIIV。\n```\n",
            event_type="history_import.chat",
        ),
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]


def test_ground_phase1_claim_rejects_ungrounded_multi_event_claim() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="",
                supporting_event_ids=["evt-a", "evt-outside"],
            )
        ]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(
            ("evt-a", "昨晚去看了 DIIV 演出。"),
            ("evt-b", "今天修复了项目里的测试。"),
        ),
    )

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []


def test_ground_phase1_claim_rejects_single_event_without_quote() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="",
                supporting_event_ids=["evt-only"],
            )
        ]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(("evt-only", "昨晚去看了 DIIV 演出。")),
    )

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []


def test_ground_phase1_claim_ids_are_deterministic_and_claim_specific() -> None:
    first = _claim()
    second = _claim(predicate="ATTENDED", evidence_text="去看了 DIIV 演出")
    window = _window(("evt-a", "我很喜欢 DIIV，昨晚去看了 DIIV 演出。"))

    first_result = L2Phase1Result(fact_claims=[first, second])
    ground_phase1_fact_claims(first_result, window)
    first_ids = [claim.claim_id for claim in first_result.fact_claims]

    replay_result = L2Phase1Result(fact_claims=[_claim(), _claim(
        predicate="ATTENDED",
        evidence_text="去看了 DIIV 演出",
    )])
    ground_phase1_fact_claims(replay_result, window)

    assert first_ids == [claim.claim_id for claim in replay_result.fact_claims]
    assert len(set(first_ids)) == 2


def test_ground_phase1_clarification_uses_only_immediate_context() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                object_ref="DIIV 新专",
                object_type="media",
                evidence_text="是新专",
                evidence_mode="clarification",
                antecedent_event_ids=["evt-user-prior", "evt-assistant-prior"],
            )
        ]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(("evt-current", "是新专")),
        context_messages=[
            {
                "event_id": "evt-user-prior",
                "session_seq": 2,
                "role": "user",
                "content": "我最近在听 DIIV 的专辑",
            },
            {
                "event_id": "evt-assistant-prior",
                "session_seq": 3,
                "role": "assistant",
                "content": "是 Oshin 还是新专？",
            },
        ],
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].evidence_mode is L2ClaimEvidenceMode.CLARIFICATION
    assert result.fact_claims[0].supporting_event_ids == ["evt-current"]
    assert result.fact_claims[0].antecedent_event_ids == [
        "evt-user-prior",
        "evt-assistant-prior",
    ]


def test_ground_phase1_clarification_rejects_non_immediate_history() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="是新专",
                evidence_mode="clarification",
                antecedent_event_ids=["evt-old-user"],
            )
        ]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(("evt-current", "是新专")),
        context_messages=[
            {
                "event_id": "evt-old-user",
                "session_seq": 1,
                "role": "user",
                "content": "我最近在听 DIIV 的专辑",
            },
            {
                "event_id": "evt-other-user",
                "session_seq": 2,
                "role": "user",
                "content": "顺便帮我看看天气",
            },
            {
                "event_id": "evt-assistant-prior",
                "session_seq": 3,
                "role": "assistant",
                "content": "是 Oshin 还是新专？",
            },
        ],
    )

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []


def test_ground_phase1_confirmation_rejects_weak_acknowledgement() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="可能吧",
                evidence_mode="confirmation",
                antecedent_event_ids=["evt-assistant-prior"],
            )
        ]
    )

    stats = ground_phase1_fact_claims(
        result,
        _window(("evt-current", "可能吧")),
        context_messages=[
            {
                "event_id": "evt-assistant-prior",
                "session_seq": 3,
                "role": "assistant",
                "content": "所以你喜欢 DIIV，对吗？",
            }
        ],
    )

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []
