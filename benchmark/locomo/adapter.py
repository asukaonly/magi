"""Adapter from LoCoMo samples into Magi eval-support contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from magi.memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord


CATEGORY_LABELS: dict[int, str] = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}


@dataclass(slots=True)
class AdaptedLoCoMoQA:
    """One LoCoMo QA item adapted to a benchmark memory query."""

    question_id: str
    sample_id: str
    qa_index: int
    category: int
    category_label: str
    question: str
    expected_answer: str
    evidence: list[str]
    answer_session_ids: list[str]
    query: EvalMemoryQuery
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptedLoCoMoSample:
    """One LoCoMo conversation adapted to replay records and QA queries."""

    sample_id: str
    namespace: str
    speaker_a: str
    speaker_b: str
    replay_records: list[EvalMemoryWriteRecord]
    qa_entries: list[AdaptedLoCoMoQA]
    metadata: dict[str, Any] = field(default_factory=dict)


def adapt_locomo_sample(sample: dict[str, Any], *, namespace: str) -> AdaptedLoCoMoSample:
    """Convert one LoCoMo sample into shared replay records plus QA queries."""
    sample_id = str(sample.get("sample_id") or "unknown")
    conversation = dict(sample.get("conversation") or {})
    speaker_a = str(conversation.get("speaker_a") or "speaker_a")
    speaker_b = str(conversation.get("speaker_b") or "speaker_b")

    replay_records: list[EvalMemoryWriteRecord] = []
    synthetic_timestamp = 0.0
    for session_number in _session_numbers(conversation):
        session_key = f"session_{session_number}"
        session_id = session_key
        session_date = str(conversation.get(f"{session_key}_date_time") or "")
        session_timestamp = _parse_locomo_timestamp(session_date)
        if session_timestamp is None:
            synthetic_timestamp += 60.0
            session_timestamp = synthetic_timestamp

        for turn_index, turn in enumerate(conversation.get(session_key) or []):
            turn_payload = dict(turn or {})
            speaker = str(turn_payload.get("speaker") or "").strip() or "Unknown"
            dia_id = str(turn_payload.get("dia_id") or f"D{session_number}:{turn_index + 1}")
            role = "assistant" if speaker == speaker_b else "user"
            content = _format_turn_content(
                speaker=speaker,
                text=str(turn_payload.get("text") or ""),
                session_date=session_date,
                blip_caption=turn_payload.get("blip_caption"),
            )
            replay_records.append(
                EvalMemoryWriteRecord(
                    namespace=namespace,
                    session_id=session_id,
                    turn_id=dia_id,
                    timestamp=float(session_timestamp) + (turn_index * 0.001),
                    role=role,
                    content=content,
                    metadata={
                        "source_dataset": "locomo",
                        "sample_id": sample_id,
                        "speaker": speaker,
                        "dia_id": dia_id,
                        "session_number": session_number,
                        "session_date": session_date,
                        "has_image": bool(str(turn_payload.get("blip_caption") or "").strip()),
                    },
                )
            )

    query_timestamp = max((record.timestamp for record in replay_records), default=0.0) + 1.0
    qa_entries: list[AdaptedLoCoMoQA] = []
    for qa_index, raw_qa in enumerate(sample.get("qa") or []):
        qa = dict(raw_qa or {})
        category = _normalize_category(qa.get("category"))
        evidence = [str(item) for item in qa.get("evidence") or []]
        question_id = f"{sample_id}:qa-{qa_index + 1}"
        query = EvalMemoryQuery(
            namespace=namespace,
            query=str(qa.get("question") or ""),
            query_timestamp=query_timestamp,
        )
        qa_entries.append(
            AdaptedLoCoMoQA(
                question_id=question_id,
                sample_id=sample_id,
                qa_index=qa_index,
                category=category,
                category_label=CATEGORY_LABELS.get(category, f"category-{category}"),
                question=str(qa.get("question") or ""),
                expected_answer=str(qa.get("answer") or ""),
                evidence=evidence,
                answer_session_ids=_answer_session_ids_from_evidence(evidence),
                query=query,
                metadata={
                    "source_dataset": "locomo",
                    "sample_id": sample_id,
                    "qa_index": qa_index,
                    "category": category,
                    "category_label": CATEGORY_LABELS.get(category, f"category-{category}"),
                },
            )
        )

    return AdaptedLoCoMoSample(
        sample_id=sample_id,
        namespace=namespace,
        speaker_a=speaker_a,
        speaker_b=speaker_b,
        replay_records=replay_records,
        qa_entries=qa_entries,
        metadata={
            "source_dataset": "locomo",
            "sample_id": sample_id,
            "session_count": len(_session_numbers(conversation)),
            "qa_count": len(qa_entries),
        },
    )


def _format_turn_content(
    *,
    speaker: str,
    text: str,
    session_date: str,
    blip_caption: Any,
) -> str:
    content = f'DATE: {session_date}\n{speaker} said, "{text}"'
    caption = str(blip_caption or "").strip()
    if caption:
        content += f"\n{speaker} shared an image: {caption}."
    return content


def _session_numbers(conversation: dict[str, Any]) -> list[int]:
    numbers: list[int] = []
    for key, value in conversation.items():
        match = re.fullmatch(r"session_(\d+)", str(key))
        if match and isinstance(value, list):
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def _parse_locomo_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.upper()
    for fmt in ("%I:%M %p ON %d %B, %Y", "%I:%M %p ON %d %b, %Y"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _normalize_category(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _answer_session_ids_from_evidence(evidence: list[str]) -> list[str]:
    session_ids: list[str] = []
    for item in evidence:
        match = re.match(r"D(\d+):", str(item))
        if not match:
            continue
        session_id = f"session_{int(match.group(1))}"
        if session_id not in session_ids:
            session_ids.append(session_id)
    return session_ids


__all__ = [
    "AdaptedLoCoMoQA",
    "AdaptedLoCoMoSample",
    "CATEGORY_LABELS",
    "adapt_locomo_sample",
]
