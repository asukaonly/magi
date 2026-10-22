"""Tests for deterministic Phase 1 claim evidence grounding."""

import hashlib
import json
from pathlib import Path
from typing import Any

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
        events=[L2BatchEvent(event_id=event_id, content=content) for event_id, content in events]
    )


def _claim(**overrides: object) -> L2Phase1FactClaim:
    payload: dict[str, object] = {
        "assertion_mode": "asserted",
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
    source: str = "history_import",
) -> L2EventWindow:
    return L2EventWindow(
        events=[
            L2BatchEvent(
                event_id="evt-history",
                content=content,
                source=source,
                event_type=event_type,
                author_type="user",
            )
        ]
    )


def test_grounded_claims_bind_exact_events_and_have_unique_batch_ids():
    result = L2Phase1Result(
        fact_claims=[
            _claim(supporting_event_ids=["evt-wrong", "evt-outside"]),
            _claim(predicate="ATTENDED", evidence_text="去看了 DIIV 演出"),
        ]
    )
    stats = ground_phase1_fact_claims(
        result,
        _window(
            ("evt-a", "我很喜欢 DIIV。"),
            ("evt-b", "昨晚去看了 DIIV 演出。"),
            ("evt-control", "今天修复了项目里的测试。"),
        ),
    )
    assert stats == {"kept": 2, "rejected": 0, "rebound": 1}
    assert [(c.predicate, c.supporting_event_ids) for c in result.fact_claims] == [
        ("LIKES", ["evt-a"]),
        ("ATTENDED", ["evt-b"]),
    ]
    ids = [c.claim_id for c in result.fact_claims]
    assert all(ids) and len(set(ids)) == 2
    assert [claim.subject_ref for claim in result.fact_claims] == ["user:self", "user:self"]


def test_ground_phase1_claim_uses_frozen_window_text() -> None:
    result = L2Phase1Result(
        fact_claims=[
            _claim(
                evidence_text="I have been really stressed about work lately.",
            )
        ]
    )
    window = L2EventWindow(
        events=[L2BatchEvent(
            event_id="evt-a", content="I have been really stressed about work lately.",
            content_source="pinned_payload",
        )],
    )

    stats = ground_phase1_fact_claims(result, window)

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-a"]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("> 我很喜欢 DIIV。\n", id="blockquote"),
        pytest.param("- > 我很喜欢 DIIV。\n", id="list_nested_blockquote"),
        pytest.param("```text\n我很喜欢 DIIV。\n```\n", id="backtick_fence"),
        pytest.param(
            "- Notes\n    ```text\n    我很喜欢 DIIV。\n    ```\n", id="list_indented_fence"
        ),
        pytest.param("~~~text\n我很喜欢 DIIV。\n~~~\n", id="tilde_fence"),
        pytest.param("```text\n我很喜欢 DIIV。\n仍然没有闭合 fence。", id="unclosed_fence"),
        pytest.param("    我很喜欢 DIIV。\n", id="indented_code"),
        pytest.param("\t我很喜欢 DIIV。\n", id="tab_indented_code"),
        pytest.param("- Notes\n    我很喜欢 DIIV。\n", id="list_indented_code"),
        pytest.param("An example uses `我很喜欢 DIIV。` here.\n", id="inline_code"),
        pytest.param(
            "---------- Forwarded message ---------\nFrom: Alice <alice@example.com>\nSubject: Notes\n\n我很喜欢 DIIV。\n",
            id="forwarded_email",
        ),
        pytest.param(
            "From: Alice <alice@example.com>\nTo: Asuka <asuka@example.com>\nSubject: Preferences\n\n我很喜欢 DIIV。\n",
            id="email_header_block",
        ),
        pytest.param("---\npreference: 我很喜欢 DIIV。\n---\n", id="frontmatter"),
        pytest.param("---\npreferences:\n  - 我很喜欢 DIIV。\n---\n", id="nested_frontmatter"),
        pytest.param("<blockquote>我很喜欢 DIIV。</blockquote>\n", id="html_blockquote"),
        pytest.param("<pre><code>我很喜欢 DIIV。</code></pre>\n", id="html_code"),
        pytest.param("<!-- 我很喜欢 DIIV。 -->\n", id="html_comment"),
        "user: 我很喜欢 DIIV。",
        "assistant: 我很喜欢 DIIV。",
        "**用户：** 我很喜欢 DIIV。",
        "[10:42] assistant: 我很喜欢 DIIV。",
        "user (10:42): 我很喜欢 DIIV。",
    ],
)
@pytest.mark.parametrize(
    "source,event_type",
    [
        ("history_import", "history_import.document"),
        ("local_documents", "SOURCE_EVENT"),
        ("obsidian_vault", "SOURCE_EVENT"),
        ("manual_entry", "manual_entry.note"),
    ],
)
def test_document_rejects_non_author_structures_even_when_model_says_asserted(
    content, source, event_type
):
    result = L2Phase1Result(
        fact_claims=[_claim(evidence_text="我很喜欢 DIIV。", assertion_mode="asserted")]
    )
    assert ground_phase1_fact_claims(
        result, _history_window(content, source=source, event_type=event_type)
    ) == {
        "kept": 0,
        "rejected": 1,
        "rebound": 0,
    }
    assert result.fact_claims == []


def test_history_document_contract_normalizer_rejects_quoted_evidence() -> None:
    payload: dict[str, object] = {
        "fact_claims": [
            {
                "assertion_mode": "asserted",
                "subject_ref": "user:self",
                "predicate": "LIKES",
                "object_ref": "DIIV",
                "object_type": "group",
                "evidence_text": "I really like DIIV.",
                "temporal_cue": "unspecified",
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


@pytest.mark.parametrize(
    "source,event_type",
    [
        ("history_import", "history_import.document"),
        ("local_documents", "SOURCE_EVENT"),
        ("obsidian_vault", "SOURCE_EVENT"),
        ("manual_entry", "manual_entry.note"),
    ],
)
def test_document_allows_normal_occurrence_when_quote_matches_too(source, event_type) -> None:
    evidence = "I really like DIIV."
    normal_occurrence = "I   REALLY like DIIV."
    content = f"> {evidence}\n\n## Recent listening\n{normal_occurrence}\n"
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=evidence)])

    stats = ground_phase1_fact_claims(
        result, _history_window(content, source=source, event_type=event_type)
    )
    locator = _evidence_locator(
        content,
        evidence,
        event_type=event_type,
        source=source,
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]
    assert locator["start"] == content.index(normal_occurrence)
    assert locator["end"] == content.index(normal_occurrence) + len(normal_occurrence)
    assert locator["attribution"] == "author_prose"


def test_history_document_uses_normal_prose_after_inline_exclusions() -> None:
    evidence = "I prefer concise answers."
    normal_occurrence = "I   PREFER concise answers."
    content = (
        f"An example uses `{evidence}` in code.\n"
        f"<blockquote>{evidence}</blockquote>\n\n"
        f"{normal_occurrence}\n"
    )
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=evidence)])

    stats = ground_phase1_fact_claims(result, _history_window(content))
    locator = _evidence_locator(
        content,
        evidence,
        event_type="history_import.document",
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert locator["start"] == content.index(normal_occurrence)
    assert locator["end"] == content.index(normal_occurrence) + len(normal_occurrence)
    assert locator["attribution"] == "author_prose"


def test_history_document_keeps_heading_author_prose() -> None:
    content = (
        "---\n"
        "title: Personal Notes\n"
        "preference: concise answers\n"
        "---\n"
        "# I prefer concise answers\n"
        "Ordinary author prose follows.\n"
    )
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="# I prefer concise answers")])

    stats = ground_phase1_fact_claims(result, _history_window(content))

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]


def test_history_document_keeps_ordinary_list_prose() -> None:
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="I prefer concise answers.")])

    stats = ground_phase1_fact_claims(
        result,
        _history_window("- I prefer concise answers.\n"),
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]


@pytest.mark.parametrize(
    "content,evidence",
    [
        ("Note: I prefer concise answers.\n", "I prefer concise answers."),
        ("Preference: concise answers\n", "Preference: concise answers"),
        ("My view: I disagree with that plan.\n", "I disagree with that plan."),
        ('I prefer the nickname "Asuka".\n', 'I prefer the nickname "Asuka".'),
        ("我喜欢「Magi」。\n", "我喜欢「Magi」。"),
        ('I said, "I prefer concise answers."\n', "I prefer concise answers."),
        ('I wrote:\n"I prefer concise answers."\n', "I prefer concise answers."),
        ("我说：\n我喜欢简洁的回答。\n", "我喜欢简洁的回答。"),
        ("I use <code>Python</code> for scripts.\n", "I use"),
        ("I like jazz <!-- private note --> and ambient music.\n", "I like jazz"),
        ("Subject: I prefer concise answers.\n", "I prefer concise answers."),
        ("Decision: I prefer concise answers.\n", "I prefer concise answers."),
        ("Python: I use it daily.\n", "I use it daily."),
        ("工作：我喜欢解决困难的问题。\n", "我喜欢解决困难的问题。"),
        (
            'The phrase "Alice said" is odd. I prefer concise answers.\n',
            "I prefer concise answers.",
        ),
        ("---\n# Notes\nI prefer concise answers.\n", "I prefer concise answers."),
        ("Alice: copied text\nI prefer concise answers.\n", "I prefer concise answers."),
        ("**爱好**：我很喜欢 DIIV。", "我很喜欢 DIIV。"),
        ("**音乐口味：**：我很喜欢 DIIV。", "我很喜欢 DIIV。"),
        ("Someone named Alice：我很喜欢 DIIV。", "我很喜欢 DIIV。"),
    ],
)
def test_history_document_preserves_author_prose_across_markup_and_labels(content, evidence):
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=evidence)])
    assert ground_phase1_fact_claims(result, _history_window(content)) == {
        "kept": 1,
        "rejected": 0,
        "rebound": 0,
    }
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]


def test_non_document_quote_cannot_be_promoted_as_self_report() -> None:
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="我很喜欢 DIIV。")])

    stats = ground_phase1_fact_claims(
        result,
        _history_window(
            "```text\n我很喜欢 DIIV。\n```\n",
            event_type="history_import.chat",
        ),
    )

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []


@pytest.mark.parametrize(
    "events,support",
    [
        ([("evt-only", "昨晚去看了 DIIV 演出。")], ["evt-only"]),
        (
            [("evt-a", "昨晚去看了 DIIV 演出。"), ("evt-b", "今天修复了项目里的测试。")],
            ["evt-a", "evt-outside"],
        ),
    ],
)
def test_current_event_ids_cannot_replace_missing_exact_evidence(events, support):
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="", supporting_event_ids=support)])
    assert ground_phase1_fact_claims(result, _window(*events)) == {
        "kept": 0,
        "rejected": 1,
        "rebound": 0,
    }
    assert result.fact_claims == []


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


@pytest.mark.parametrize(
    "scope,text",
    [
        ("one_off", "午饭吃了螺蛳粉，比上次好吃"),
        ("recent", "最近我喜欢螺蛳粉"),
        ("recurring", "我每周都会吃螺蛳粉"),
        ("stable", "我一直喜欢螺蛳粉"),
        ("unspecified", "我喜欢螺蛳粉"),
    ],
)
def test_grounding_preserves_explicit_temporal_scope_and_fact_kind(scope, text):
    kind = "explicit_fact" if scope == "one_off" else "stable_preference"
    payload = {
        "fact_claims": [
            {
                "assertion_mode": "asserted",
                "subject_ref": "user:self",
                "predicate": "LIKES",
                "object_ref": "螺蛳粉",
                "object_type": "food",
                "fact_kind": kind,
                "temporal_cue": scope,
                "evidence_text": text,
                "supporting_event_ids": ["evt-scope"],
            }
        ]
    }
    window = _window(("evt-scope", text))
    normalize_phase1_claim_contract(payload, window)
    result = L2Phase1Result.from_dict(payload)
    assert ground_phase1_fact_claims(result, window) == {"kept": 1, "rejected": 0, "rebound": 0}
    claim = result.fact_claims[0]
    assert (claim.temporal_cue, claim.fact_kind, claim.object_ref, claim.supporting_event_ids) == (
        scope,
        kind,
        "螺蛳粉",
        ["evt-scope"],
    )


@pytest.mark.parametrize(
    "mode", ["asserted", "question", "conditional", "hypothetical", "quoted", "uncertain"]
)
@pytest.mark.parametrize("event_type", ["UserMessage", "history_import.document"])
def test_grounding_obeys_typed_assertion_mode_without_guessing_from_prose(mode, event_type):
    text = "我喜欢 DIIV"
    window = L2EventWindow(
        events=[
            L2BatchEvent(
                event_id="evt-mode", content=text, author_type="user", event_type=event_type
            )
        ]
    )
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=text, assertion_mode=mode)])
    kept = int(mode == "asserted")
    assert ground_phase1_fact_claims(result, window) == {
        "kept": kept,
        "rejected": 1 - kept,
        "rebound": 0,
    }
    assert [c.supporting_event_ids for c in result.fact_claims] == ([["evt-mode"]] if kept else [])


def test_missing_assertion_mode_cannot_default_to_a_self_report():
    payload = {"fact_claims": [{
        "subject_ref": "user:self", "predicate": "LIKES", "object_ref": "DIIV",
        "object_type": "group", "temporal_cue": "unspecified", "evidence_text": "我喜欢 DIIV",
    }]}
    normalizations = normalize_phase1_claim_contract(payload, _window(("evt-1", "我喜欢 DIIV")))
    assert payload["fact_claims"] == []
    assert any("non_asserted_proposition:unknown" in value for value in normalizations)


def test_title_with_first_person_word_is_valid_claim_evidence():
    text = "我喜欢《我的世界》"
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=text, object_ref="我的世界")])
    assert ground_phase1_fact_claims(result, _window(("evt-title", text)))["kept"] == 1


def test_confirmation_semantics_do_not_depend_on_a_fixed_reply_vocabulary():
    claim = _claim(evidence_text="说的就是我的意思", evidence_mode="confirmation", antecedent_event_ids=["evt-a"])
    result = L2Phase1Result(fact_claims=[claim])
    stats = ground_phase1_fact_claims(result, _window(("evt-u", claim.evidence_text)), context_messages=[{
        "event_id": "evt-a", "role": "assistant", "content": "你喜欢 DIIV，对吗？",
    }])
    assert stats["kept"] == 1
    assert result.fact_claims[0].confidence <= 0.75


@pytest.mark.parametrize(("predicate", "value", "evidence", "kept"), [
    ("REAL_NAME", "王小明", "我喜欢苹果", 0),
    ("PREFERRED_FORM_OF_ADDRESS", "小明或者小王", "叫我小明", 0),
    ("PLANS_TO", "删除公司的全部文件", "我计划去海边", 0),
    ("REAL_NAME", "王小明", "我叫王小明", 1),
    ("PREFERRED_FORM_OF_ADDRESS", "user:self", "请叫我user:self", 1),
    ("BIRTH_DATE", "1992-09-08", "我出生于1992年9月8日", 1),
    ("BIRTH_DATE", "1992-09-08", "我出生于1993年9月8日", 0),
    ("BIRTH_DATE", "09-08", "我的生日是9月8日", 1),
    ("BIRTH_DATE", "02-29", "生日是2月29日", 1),
    ("BIRTH_DATE", "1993-02-29", "生日是1993年2月29日", 0),
    ("STATED_AGE", "30", "我今年130岁", 0),
    ("STATED_AGE", "30", "我今年30岁", 1),
])
def test_literal_claim_value_requires_complete_authorized_source(predicate, value, evidence, kept):
    claim = _claim(predicate=predicate, object_ref=value, object_type="concept", evidence_text=evidence)
    result = L2Phase1Result(fact_claims=[claim])
    stats = ground_phase1_fact_claims(result, _window(("evt-current", evidence)))
    assert stats["kept"] == kept


@pytest.mark.parametrize("mode", ["confirmation", "clarification"])
def test_literal_claim_can_use_validated_immediate_context(mode):
    context = [
        {"event_id": "evt-user", "role": "user", "content": "我叫王小明"},
        {"event_id": "evt-assistant", "role": "assistant", "content": "你的真实姓名是王小明，对吗？"},
    ]
    antecedents = ["evt-assistant"] if mode == "confirmation" else ["evt-user", "evt-assistant"]
    claim = _claim(predicate="REAL_NAME", object_ref="王小明", object_type="concept", evidence_text="对的", evidence_mode=mode, antecedent_event_ids=antecedents)
    result = L2Phase1Result(fact_claims=[claim])
    stats = ground_phase1_fact_claims(result, _window(("evt-current", "对的")), context_messages=context)
    assert stats["kept"] == 1
    assert claim.confidence <= 0.75


def test_literal_claim_cannot_borrow_an_uncited_context_value():
    claim = _claim(predicate="REAL_NAME", object_ref="王小明", object_type="concept", evidence_text="我喜欢苹果")
    result = L2Phase1Result(fact_claims=[claim])
    stats = ground_phase1_fact_claims(result, _window(("evt-current", "我喜欢苹果")), context_messages=[{"event_id":"evt-old", "role":"user", "content":"我的同事叫王小明"}])
    assert stats["kept"] == 0


@pytest.mark.parametrize("case", json.loads((Path(__file__).parent / "fixtures/claim_assertion_rearchitecture.json").read_text()), ids=lambda case: str(case["name"]))
def test_fresh_input_claims_have_exact_stable_grounding(case: dict[str, Any]) -> None:
    event = L2BatchEvent.from_dict(case["event"])
    result = L2Phase1Result.from_dict(case["phase1"])

    stats = ground_phase1_fact_claims(result, L2EventWindow(events=[event]))

    assert stats == {
        "kept": 1,
        "rejected": 0,
        "rebound": int(bool(case["phase1"]["fact_claims"][0]["supporting_event_ids"])),
    }
    assert len(result.fact_claims) == 1
    claim = result.fact_claims[0]
    expected = case["expected"]
    assert claim.claim_id == "claim:1"
    assert claim.predicate == expected["predicate"]
    assert claim.object_ref == expected["object_ref"]
    assert claim.object_type == expected["object_type"]
    assert claim.fact_kind.value == expected["fact_kind"]
    assert claim.evidence_text == expected["evidence_text"]
    assert claim.supporting_event_ids == expected["supporting_event_ids"]

    locator = _evidence_locator(
        event.content,
        claim.evidence_text,
        event_type=event.event_type,
    )
    start = event.content.index(claim.evidence_text)
    assert locator["start"] == start
    assert locator["end"] == start + len(claim.evidence_text)
    assert locator["quote_hash"] == hashlib.sha256(
        claim.evidence_text.encode("utf-8")
    ).hexdigest()
    assert locator.get("attribution") == expected["attribution"]
