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
) -> L2EventWindow:
    return L2EventWindow(
        events=[
            L2BatchEvent(
                event_id="evt-history",
                content=content,
                source="history_import",
                event_type=event_type,
                author_type="user",
            )
        ]
    )


def test_ground_phase1_claim_binds_quote_to_exact_event() -> None:
    result = L2Phase1Result(fact_claims=[_claim(supporting_event_ids=["evt-wrong", "evt-outside"])])

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
    ("content", "assertion_mode"),
    [
        pytest.param('> 我很喜欢 DIIV。\n', "asserted", id="blockquote"),
        pytest.param('- > 我很喜欢 DIIV。\n', "asserted", id="list_nested_blockquote"),
        pytest.param('```text\n我很喜欢 DIIV。\n```\n', "asserted", id="backtick_fence"),
        pytest.param('- Notes\n    ```text\n    我很喜欢 DIIV。\n    ```\n', "asserted", id="list_indented_fence"),
        pytest.param('~~~text\n我很喜欢 DIIV。\n~~~\n', "asserted", id="tilde_fence"),
        pytest.param('```text\n我很喜欢 DIIV。\n仍然没有闭合 fence。', "asserted", id="unclosed_fence"),
        pytest.param('    我很喜欢 DIIV。\n', "asserted", id="indented_code"),
        pytest.param('\t我很喜欢 DIIV。\n', "asserted", id="tab_indented_code"),
        pytest.param('- Notes\n    我很喜欢 DIIV。\n', "asserted", id="list_indented_code"),
        pytest.param('An example uses `我很喜欢 DIIV。` here.\n', "asserted", id="inline_code"),
        pytest.param('Alice: 我很喜欢 DIIV。\n', "quoted", id="speaker_turn"),
        pytest.param('alice: 我很喜欢 DIIV。\n', "quoted", id="lowercase_speaker_turn"),
        pytest.param('Dr. Alice: 我很喜欢 DIIV。\n', "quoted", id="honorific_speaker_turn"),
        pytest.param('alice_01: 我很喜欢 DIIV。\n', "quoted", id="underscore_chat_handle"),
        pytest.param('alice#1234: 我很喜欢 DIIV。\n', "quoted", id="numbered_chat_handle"),
        pytest.param('alice@example.com: 我很喜欢 DIIV。\n', "quoted", id="email_chat_handle"),
        pytest.param('👩 Alice: 我很喜欢 DIIV。\n', "quoted", id="emoji_chat_handle"),
        pytest.param('**Alice:** 我很喜欢 DIIV。\n', "quoted", id="bold_speaker_turn"),
        pytest.param('---------- Forwarded message ---------\nFrom: Alice <alice@example.com>\nSubject: Notes\n\n我很喜欢 DIIV。\n', "asserted", id="forwarded_email"),
        pytest.param('-----Original Message-----\nFrom: Alice\n\n我很喜欢 DIIV。\n', "quoted", id="original_message"),
        pytest.param('From: Alice <alice@example.com>\nTo: Asuka <asuka@example.com>\nSubject: Preferences\n\n我很喜欢 DIIV。\n', "asserted", id="email_header_block"),
        pytest.param('[10:42] Alice: 我很喜欢 DIIV。\n', "quoted", id="timestamped_speaker_turn"),
        pytest.param('Alice (10:42): 我很喜欢 DIIV。\n', "quoted", id="speaker_with_parenthesized_timestamp"),
        pytest.param('Alice [2026-08-03 10:42]: 我很喜欢 DIIV。\n', "quoted", id="speaker_with_trailing_timestamp"),
        pytest.param('A note copied from Alice:\n我很喜欢 DIIV。\n', "quoted", id="copied_note_attribution"),
        pytest.param('Quote from Alice:\n我很喜欢 DIIV。\n', "quoted", id="cross_line_quote_from_attribution"),
        pytest.param('以下内容复制自 Alice：\n我很喜欢 DIIV。\n', "quoted", id="chinese_copied_attribution"),
        pytest.param('Alice — 我很喜欢 DIIV。\n', "quoted", id="speaker_dash_turn"),
        pytest.param('Alice said, "我很喜欢 DIIV。"\n', "quoted", id="third_party_quote"),
        pytest.param('Alice says, "我很喜欢 DIIV。"\n', "quoted", id="third_party_present_quote"),
        pytest.param('Alice stated, "我很喜欢 DIIV。"\n', "quoted", id="third_party_stated_quote"),
        pytest.param('Alice claimed, "我很喜欢 DIIV。"\n', "quoted", id="third_party_claimed_quote"),
        pytest.param("Alice said, '我很喜欢 DIIV。'\n", "quoted", id="third_party_single_quote"),
        pytest.param('According to Alice, "我很喜欢 DIIV。"\n', "quoted", id="according_to_quote"),
        pytest.param('Quote from Alice: "我很喜欢 DIIV。"\n', "quoted", id="quote_from_attribution"),
        pytest.param('Excerpt from Alice: "我很喜欢 DIIV。"\n', "quoted", id="excerpt_from_attribution"),
        pytest.param('In Alice\'s words, "我很喜欢 DIIV。"\n', "quoted", id="in_someones_words"),
        pytest.param('"我很喜欢 DIIV。" — Alice\n', "quoted", id="post_attributed_quote"),
        pytest.param('“我很喜欢 DIIV。” (Alice)\n', "quoted", id="parenthetical_post_attribution"),
        pytest.param('“我很喜欢 DIIV。” —— Alice\n', "quoted", id="double_dash_post_attribution"),
        pytest.param('Alice 的原话是：「我很喜欢 DIIV。」\n', "quoted", id="chinese_attributed_quote"),
        pytest.param('Alice wrote:\n"我很喜欢 DIIV。"\n', "quoted", id="cross_line_attributed_quote"),
        pytest.param('Alice wrote:\n\n"我很喜欢 DIIV。"\n', "quoted", id="cross_blank_line_attributed_quote"),
        pytest.param('Alice wrote:\n- 我很喜欢 DIIV。\n', "quoted", id="attributed_list"),
        pytest.param('On Tue, Alice wrote:\n我很喜欢 DIIV。\n', "quoted", id="reply_header_attribution"),
        pytest.param('---\npreference: 我很喜欢 DIIV。\n---\n', "asserted", id="frontmatter"),
        pytest.param('---\npreferences:\n  - 我很喜欢 DIIV。\n---\n', "asserted", id="nested_frontmatter"),
        pytest.param('<blockquote>我很喜欢 DIIV。</blockquote>\n', "asserted", id="html_blockquote"),
        pytest.param('<pre><code>我很喜欢 DIIV。</code></pre>\n', "asserted", id="html_code"),
        pytest.param('<!-- 我很喜欢 DIIV。 -->\n', "asserted", id="html_comment"),
    ],
)
def test_history_document_applies_structural_and_semantic_evidence_boundaries(
    content: str, assertion_mode: str,
) -> None:
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="我很喜欢 DIIV。", assertion_mode=assertion_mode)])

    stats = ground_phase1_fact_claims(result, _history_window(content))

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
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


def test_history_document_rejects_frontmatter_as_author_evidence() -> None:
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="preference: concise answers")])

    stats = ground_phase1_fact_claims(
        result,
        _history_window("---\ntitle: Personal Notes\npreference: concise answers\n---\n"),
    )

    assert stats == {"kept": 0, "rejected": 1, "rebound": 0}
    assert result.fact_claims == []


def test_history_document_keeps_ordinary_list_prose() -> None:
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="I prefer concise answers.")])

    stats = ground_phase1_fact_claims(
        result,
        _history_window("- I prefer concise answers.\n"),
    )

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
    assert result.fact_claims[0].supporting_event_ids == ["evt-history"]


@pytest.mark.parametrize(
    ("content", "evidence"),
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
        ("Reason: I prefer concise answers.\n", "I prefer concise answers."),
        ("Status: I prefer concise answers.\n", "I prefer concise answers."),
        ("Music: I prefer ambient music.\n", "I prefer ambient music."),
        ("Current Status: I prefer concise answers.\n", "I prefer concise answers."),
        ("音乐：我喜欢氛围音乐。\n", "我喜欢氛围音乐。"),
        (
            'The phrase "Alice said" is odd. I prefer concise answers.\n',
            "I prefer concise answers.",
        ),
        ("---\n# Notes\nI prefer concise answers.\n", "I prefer concise answers."),
        (
            "Alice: copied text\nI prefer concise answers.\n",
            "I prefer concise answers.",
        ),
    ],
)
def test_history_document_keeps_unambiguous_author_prose(
    content: str,
    evidence: str,
) -> None:
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=evidence)])

    stats = ground_phase1_fact_claims(result, _history_window(content))

    assert stats == {"kept": 1, "rejected": 0, "rebound": 0}
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

    replay_result = L2Phase1Result(
        fact_claims=[
            _claim(),
            _claim(
                predicate="ATTENDED",
                evidence_text="去看了 DIIV 演出",
            ),
        ]
    )
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
                assertion_mode="uncertain",
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


@pytest.mark.parametrize("text,scope", [
    ("午饭吃了螺蛳粉，比上次好吃", "one_off"),
    ("这家螺蛳粉味道不错", "one_off"),
    ("今天想吃螺蛳粉", "one_off"),
    ("我喜欢螺蛳粉", "unspecified"),
    ("我好喜欢螺蛳粉", "unspecified"),
    ("我蛮喜欢苹果的", "unspecified"),
    ("我中意苹果", "unspecified"),
    ("我对苹果情有独钟", "unspecified"),
    ("我喜欢早餐吃螺蛳粉", "unspecified"),
    ("最近我喜欢螺蛳粉", "recent"),
])
def test_grounding_preserves_the_model_preference_scope(text, scope):
    payload = {"fact_claims": [{
        "assertion_mode": "asserted",
        "subject_ref": "user:self", "predicate": "LIKES", "object_ref": "螺蛳粉",
        "object_type": "food", "fact_kind": "explicit_fact" if scope == "one_off" else "stable_preference", "temporal_cue": scope,
        "evidence_text": text, "supporting_event_ids": ["evt-scope"],
    }]}
    window = _window(("evt-scope", text))
    normalize_phase1_claim_contract(payload, window)
    result = L2Phase1Result.from_dict(payload)
    assert ground_phase1_fact_claims(result, window)["kept"] == 1
    claim = result.fact_claims[0]
    assert claim.temporal_cue == scope
    if scope == "one_off":
        assert claim.fact_kind == "explicit_fact"


@pytest.mark.parametrize("text,mode,kept", [
    ("我喜欢 DIIV，你推荐什么？", "asserted", 1),
    ("我喜欢 DIIV 吗？", "question", 0),
    ("如果我喜欢 DIIV，你推荐什么？", "conditional", 0),
    ("假设可以自由选择，我喜欢 DIIV，你推荐什么？", "hypothetical", 0),
    ('他说“我喜欢 DIIV”，你推荐什么？', "quoted", 0),
])
def test_chat_grounding_requires_an_asserted_semantic_decision(text, mode, kept):
    window = L2EventWindow(events=[L2BatchEvent(
        event_id="evt-mixed", content=text, author_type="user", event_type="UserMessage",
    )])
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="我喜欢 DIIV", assertion_mode=mode)])
    assert ground_phase1_fact_claims(result, window)["kept"] == kept


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


@pytest.mark.parametrize("label", [
    "爱好", "兴趣", "音乐口味", "偏好", "生活中让我感到放松的事情", "Hobbies",
    "Personal taste in music", "**爱好**", "**音乐口味：**", "Someone named Alice",
])
def test_history_document_prose_labels_do_not_determine_authorship(label):
    evidence = "我很喜欢 DIIV。"
    content = f"{label}：{evidence}"
    result = L2Phase1Result(fact_claims=[_claim(evidence_text=evidence)])
    assert ground_phase1_fact_claims(result, _history_window(content))["kept"] == 1


@pytest.mark.parametrize("content", [
    "user: 我很喜欢 DIIV。", "assistant: 我很喜欢 DIIV。", "**用户：** 我很喜欢 DIIV。",
    "[10:42] assistant: 我很喜欢 DIIV。", "user (10:42): 我很喜欢 DIIV。",
])
def test_explicit_transcript_roles_never_inherit_document_authority(content):
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="我很喜欢 DIIV。")])
    assert ground_phase1_fact_claims(result, _history_window(content))["kept"] == 0


@pytest.mark.parametrize("content", [
    "Alice：我很喜欢 DIIV。", "她跟我分享了自己的偏好：我很喜欢 DIIV。",
    "在Alice的原话里，我很喜欢 DIIV。", 'Alice goes: "我很喜欢 DIIV。"',
])
def test_prose_attribution_is_decided_by_typed_assertion_mode(content):
    result = L2Phase1Result(fact_claims=[_claim(evidence_text="我很喜欢 DIIV。", assertion_mode="quoted")])
    assert ground_phase1_fact_claims(result, _history_window(content))["kept"] == 0
