"""Rich-text evidence retains attribution while preserving the saved body."""

import pytest

from magi.memory.manual_entries.evidence import project_rich_text_evidence
from magi.memory.l2.pipeline.claim_evidence import find_claim_evidence_occurrence
from magi.memory.manual_entries.l1_projector import _build_memory_event
from memory.manual_entries.test_l1_projector import _entry


def _doc(text: str, *, kind: str = "paragraph", marks: list | None = None) -> dict:
    leaf = {"type": "text", "text": text, "marks": marks or []}
    paragraph = {"type": "paragraph", "content": [leaf]}
    node = paragraph if kind == "paragraph" else {"type": kind, "content": [paragraph]}
    return {"type": "doc", "content": [node]}


@pytest.mark.parametrize(
    "kind,marks",
    [
        ("blockquote", []),
        ("codeBlock", []),
        ("paragraph", [{"type": "code"}]),
    ],
)
def test_quotes_and_code_cannot_claim_a_later_authored_occurrence(kind, marks):
    text = "我一直喜欢 DIIV。"
    document = _doc(text, kind=kind, marks=marks)
    document["content"].extend(_doc(text)["content"])
    body = f"{text}\n\n{text}"
    event = _build_memory_event(_entry(body=body, body_doc=document), predecessor_event_id=None)
    assert event.content == body
    assert event.cognition_eligible is True
    evidence = event.pinned_payload
    assert evidence is not None
    start, end = find_claim_evidence_occurrence(
        evidence,
        text,
        source=event.source,
        event_type=event.event_type,
    )
    assert start == evidence.rindex(text)
    assert evidence[start:end] == text


def test_nested_lists_and_text_marks_preserve_authored_prose():
    document = _doc("我叫明日香", marks=[{"type": "bold"}, {"type": "link"}])
    document["content"] = [
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": document["content"]},
            ],
        }
    ]
    assert project_rich_text_evidence("\n我叫明日香\n", document) == "\n我叫明日香\n"


def test_literal_backticks_cannot_escape_a_rich_text_quote():
    text = "```\n我叫苏眠。\n````"
    evidence = project_rich_text_evidence(text, _doc(text, kind="blockquote"))
    assert (
        find_claim_evidence_occurrence(
            evidence,
            "我叫苏眠。",
            source="manual_entry",
            event_type="manual_entry.note",
        )
        is None
    )


@pytest.mark.parametrize(
    "document",
    [
        {"type": "doc", "content": []},
        _doc("a different body"),
        _doc("我叫明日香", kind="unknown"),
        _doc("我叫明日香", marks=[{"type": "unknown"}]),
        {"type": "doc", "content": "invalid"},
        {"type": "doc", "content": [{"type": "text", "text": 42}]},
        {"type": "doc", "content": [{"type": ["paragraph"]}]},
        _doc("我叫明日香", marks=[{"type": ["code"]}]),
    ],
)
def test_inconsistent_rich_text_is_saved_without_cognition(document):
    event = _build_memory_event(
        _entry(body="我叫明日香", body_doc=document),
        predecessor_event_id=None,
    )
    assert event.content == "我叫明日香"
    assert event.cognition_eligible is False
    assert event.metadata_json["manual_entry"]["evidence_projection_status"] == "invalid_rich_text"


def test_format_only_change_has_a_new_projection_identity():
    body = "我叫明日香"
    authored = _build_memory_event(
        _entry(body=body, body_doc=_doc(body)), predecessor_event_id=None
    )
    quoted = _build_memory_event(
        _entry(body=body, body_doc=_doc(body, kind="blockquote")),
        predecessor_event_id=None,
    )
    assert authored.content == quoted.content
    assert authored.event_id != quoted.event_id
    assert authored.pinned_payload != quoted.pinned_payload


def test_exclusion_from_cognition_is_preserved_with_valid_rich_text():
    event = _build_memory_event(
        _entry(body="我叫明日香", body_doc=_doc("我叫明日香"), exclude_from_llm=True),
        predecessor_event_id=None,
    )
    assert event.cognition_eligible is False


def test_markdown_in_other_prose_cannot_expose_a_rich_text_quote():
    text = "```\n我叫苏眠。"
    document = _doc("```")
    document["content"].extend(_doc(text, kind="blockquote")["content"])
    event = _build_memory_event(
        _entry(body=f"```\n\n{text}", body_doc=document),
        predecessor_event_id=None,
    )
    assert event.cognition_eligible is False
    assert event.metadata_json["manual_entry"]["evidence_projection_status"] == "invalid_rich_text"
