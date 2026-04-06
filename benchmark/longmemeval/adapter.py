"""Adapter from LongMemEval dataset rows into Magi eval-support contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from magi.memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord


@dataclass(slots=True)
class AdaptedLongMemEvalEntry:
    """LongMemEval entry adapted to replay records plus final query."""

    question_id: str
    question_type: str
    expected_answer: str
    answer_session_ids: list[str]
    replay_records: list[EvalMemoryWriteRecord]
    query: EvalMemoryQuery
    metadata: dict[str, Any] = field(default_factory=dict)


def adapt_longmemeval_entry(entry: dict[str, Any], *, namespace: str) -> AdaptedLongMemEvalEntry:
    replay_records: list[EvalMemoryWriteRecord] = []
    haystack_session_ids = list(entry.get("haystack_session_ids") or [])
    haystack_dates = list(entry.get("haystack_dates") or [])
    haystack_sessions = list(entry.get("haystack_sessions") or [])

    synthetic_timestamp_counter = 0.0
    for session_index, turns in enumerate(haystack_sessions):
        session_id = str(
            haystack_session_ids[session_index]
            if session_index < len(haystack_session_ids)
            else f"session-{session_index + 1}"
        )
        session_date = (
            str(haystack_dates[session_index])
            if session_index < len(haystack_dates)
            else None
        )
        session_base_timestamp = _parse_longmemeval_timestamp(session_date)
        if session_base_timestamp is None:
            synthetic_timestamp_counter += 60.0
            session_base_timestamp = synthetic_timestamp_counter
        for turn_index, turn in enumerate(turns or []):
            turn_timestamp = session_base_timestamp + (session_index * 0.0001) + (turn_index * 0.001)
            replay_records.append(
                EvalMemoryWriteRecord(
                    namespace=namespace,
                    session_id=session_id,
                    turn_id=f"{session_id}:turn-{turn_index + 1}",
                    timestamp=turn_timestamp,
                    role=str(turn.get("role") or "user"),
                    content=str(turn.get("content") or ""),
                    metadata={
                        "source_dataset": "longmemeval",
                        "session_date": session_date,
                        "has_answer": bool(turn.get("has_answer", False)),
                    },
                )
            )

    metadata = {
        "question_date": entry.get("question_date"),
        "question_type": str(entry.get("question_type") or ""),
        "is_abstention": _is_abstention_entry(entry),
    }
    question_date_ts = _parse_longmemeval_timestamp(entry.get("question_date"))
    if question_date_ts is None:
        question_date_ts = max((record.timestamp for record in replay_records), default=0.0) + 1.0
    query = EvalMemoryQuery(
        namespace=namespace,
        query=str(entry.get("question") or ""),
        query_timestamp=question_date_ts,
    )
    return AdaptedLongMemEvalEntry(
        question_id=str(entry.get("question_id") or ""),
        question_type=str(entry.get("question_type") or ""),
        expected_answer=str(entry.get("answer") or ""),
        answer_session_ids=[str(item) for item in entry.get("answer_session_ids") or []],
        replay_records=replay_records,
        query=query,
        metadata=metadata,
    )


def _is_abstention_entry(entry: dict[str, Any]) -> bool:
    answer = str(entry.get("answer") or "").strip().lower()
    question_id = str(entry.get("question_id") or "").strip().lower()
    return answer in {"unknown", "cannot be determined", "cannot determine"} or question_id.endswith("_abs")


def _parse_longmemeval_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y/%m/%d (%a) %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None
