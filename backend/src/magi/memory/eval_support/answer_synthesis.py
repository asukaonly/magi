"""LLM-backed answer synthesis for memory evaluation queries."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from magi.config.models import LLMScenario, ThinkingDepth
from magi.core.logger import get_logger
from magi.llm import LLMProviderBridge
from magi.memory.answering import build_answer_prompt_payload
from magi.utils.diagnostic_logging import full_content_logging_enabled

from .answer_normalization import normalize_eval_answer

logger = get_logger(__name__)

EVAL_ANSWER_TIMEOUT = 300


def format_l2_context(
    *,
    entity_cards: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    assertions: list[dict[str, Any]] | None = None,
) -> str:
    """Format L2 knowledge graph data as LLM-readable context."""
    blocks: list[str] = []
    for rel in relationships or []:
        summary = str(rel.get("natural_summary") or rel.get("evidence_text") or "").strip()
        if not summary:
            subj = str(rel.get("subject_id") or "")
            pred = str(rel.get("predicate") or "")
            obj = str(rel.get("object_id") or "")
            summary = f"{subj} {pred} {obj}"
        blocks.append(f"- [relationship] {summary}")
    for card in entity_cards or []:
        entity_id = str(card.get("entity_id") or "")
        summary = str(card.get("summary") or card.get("snapshot") or "").strip()
        if summary:
            blocks.append(f"- [entity] {entity_id}: {summary}")
    for assertion in assertions or []:
        text = str(assertion.get("assertion_text") or assertion.get("value") or "").strip()
        if text:
            blocks.append(f"- [assertion] {text}")
    return "\n".join(blocks) if blocks else "(no knowledge graph context)"


def is_counting_or_aggregation_question(question: str) -> bool:
    """Detect questions that require multi-step counting, aggregation, or temporal math."""
    lowered = str(question or "").lower()
    return bool(
        re.search(
            r"\bhow many\b|\btotal\b|\bcombined\b|\ball together\b|\bsum\b|\baverage\b|\bhow old\b|\bhow long\b|\bhow much faster\b|\bhow much older\b",
            lowered,
        )
    )


def is_temporal_reasoning_question(question: str) -> bool:
    """Detect questions that benefit from step-by-step temporal reasoning."""
    lowered = str(question or "").lower()
    return bool(
        re.search(
            r"\bhow many days\b|\bhow many weeks\b|\bhow many months\b|\bhow long ago\b|"
            r"\bdays? ago\b|\bweeks? ago\b|\bmonths? ago\b|\byears? ago\b|"
            r"\bmost recent\b|\bhappened first\b|\bwhich came first\b|"
            r"\bwhat day\b|\bwhat date\b|\bbefore or after\b|"
            r"\bfirst\b.{1,30}\bor\b.{1,30}\b(?:last|later|second)\b|"
            r"\blast\b.{1,30}\btime\b.{1,30}\b(?:did|was|were)\b",
            lowered,
        )
    )


async def synthesize_eval_answer(
    *,
    question: str,
    hits: list[dict[str, Any]],
    evidence_bundles: list[dict[str, Any]] | None = None,
    timeline_summary: list[dict[str, Any]] | None = None,
    l2_entity_cards: list[dict[str, Any]] | None = None,
    l2_relationships: list[dict[str, Any]] | None = None,
    l2_assertions: list[dict[str, Any]] | None = None,
    l2_episodes: list[dict[str, Any]] | None = None,
    l2_experiences: list[dict[str, Any]] | None = None,
    query_timestamp: float | None = None,
    show_prompt: bool = False,
    llm_pool: Any,
    log: Any | None = None,
) -> tuple[str, dict[str, Any]]:
    _ = l2_experiences
    active_logger = log if log is not None else logger
    adapter = llm_pool.get(LLMScenario.CORE)
    bridge = LLMProviderBridge(adapter)
    prompt_payload = build_answer_prompt_payload(
        question=question,
        hits=hits,
        evidence_bundles=evidence_bundles,
        timeline_summary=timeline_summary,
        l2_episodes=l2_episodes,
    )
    system_prompt = _build_eval_answer_system_prompt()
    l2_context_text = format_l2_context(
        entity_cards=l2_entity_cards,
        relationships=l2_relationships,
        assertions=l2_assertions,
    )
    user_prompt = _build_eval_answer_user_prompt(
        question=question,
        prompt_payload=prompt_payload,
        l2_context_text=l2_context_text,
        question_date_line=_build_question_date_line(query_timestamp),
    )
    _log_answer_synthesis_started(
        active_logger,
        question=question,
        hits=hits,
        evidence_bundles=evidence_bundles,
        prompt_payload=prompt_payload,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    raw_answer = await _chat_eval_answer(
        bridge, system_prompt=system_prompt, user_prompt=user_prompt
    )
    normalized_answer = normalize_eval_answer(raw_answer)
    _log_answer_synthesis_completed(
        active_logger,
        question=question,
        hits=hits,
        raw_answer=raw_answer,
        normalized_answer=normalized_answer,
    )
    return normalized_answer, _build_answer_trace(
        hits=hits,
        evidence_bundles=evidence_bundles,
        timeline_summary=timeline_summary,
        l2_entity_cards=l2_entity_cards,
        l2_relationships=l2_relationships,
        l2_assertions=l2_assertions,
        show_prompt=show_prompt,
        user_prompt=user_prompt,
    )


def _build_eval_answer_system_prompt() -> str:
    return (
        "You are answering a question using retrieved memory evidence only.\n"
        "Return a concise final answer to the question.\n"
        "Return only the final answer span with no explanation.\n"
        "Prefer a short phrase copied or closely paraphrased from the evidence.\n"
        "When asked about order, count, duration, or time difference, reason over timestamps and content to derive the answer.\n"
        "For recency or ordering questions, rely on the Timeline Summary chronological order — "
        "do NOT judge recency by how much a topic is discussed in the evidence bundles.\n"
        "When asked 'how many' or 'total', enumerate EVERY relevant item from ALL bundles, timeline entries, and evidence, then sum to get the final count. "
        "Only count items that EXACTLY match the question criteria; do NOT count similar but different items. "
        "Ignore items mentioned in unrelated topics or different contexts. If an item is mentioned multiple times across bundles, count it only ONCE.\n"
        "When asked about 'X ago' or relative dates ('last Tuesday'), compute the delta between the event timestamp and the question date.\n"
        "IMPORTANT: If the question specifies a different reference point (e.g. 'when I did Y', 'at the time of Y', 'since I started X'), "
        "compute the delta relative to THAT event's date, NOT the question date. "
        "Example: 'How many days ago did I launch my website when I signed a contract?' — find the website-launch date and "
        "the contract-signing date, then compute (contract date minus launch date).\n"
        "When evidence spans multiple bundles, cross-reference and aggregate information across all of them.\n"
        "Look for answers in BOTH user messages AND assistant responses within the evidence.\n"
        "If the question asks about a specific detail (name, place, date, amount), check assistant replies — they often restate or confirm the user's information.\n"
        "\n"
        "ENTITY VERIFICATION:\n"
        "If the question asks about a SPECIFIC named entity and NO evidence mentions that entity "
        "or a clearly equivalent variant, answer 'unknown'. "
        "Do NOT substitute a genuinely DIFFERENT entity (e.g. do not answer about 'Dr. Smith' when asked about 'Dr. Johnson'). "
        "However, treat minor wording differences as matches (e.g. 'University of Melbourne' matches 'University of Melbourne in Australia'; "
        "'Spotify' matches 'a Spotify subscription').\n"
        "\n"
        "DIALOGUE OWNERSHIP:\n"
        "If the question asks about a named person, first-person dialogue evidence from another speaker belongs to that other speaker. "
        "do not use it to answer about the named person unless the evidence explicitly says it is about that named person. "
        "If all available evidence with matching topic belongs to a different person, answer 'unknown'.\n"
        "\n"
        "CURRENT STATE (knowledge-update) questions:\n"
        "When the question asks about a current/present state ('where do I currently keep', 'how long have I been', "
        "'how many do I have now', 'what is my current'), use the value from the MOST RECENT evidence only. "
        "Do NOT sum or accumulate values across multiple time periods. "
        "If something was updated or changed over time, report only the latest value.\n"
        "\n"
        "Attempt an answer whenever correctly-owned evidence provides relevant clues, even if incomplete or indirect.\n"
        "Scan ALL evidence sections thoroughly — answers may appear in any bundle, timeline entry, or assistant reply.\n"
        "For recommendation or suggestion questions, ANY correctly-owned evidence about the user's interests, tools, past choices, "
        "or stated preferences is sufficient to generate a personalized answer. "
        "Do NOT answer 'unknown' for recommendation questions when you have any user context.\n"
        "BEFORE answering 'unknown', re-read EVERY bundle and timeline entry once more. "
        "Check if any correctly-owned user message or assistant reply contains words related to the question topic. "
        "If you find ANY correctly-owned mention — even indirect — attempt an answer based on that evidence.\n"
        "Answer exactly 'unknown' only as a last resort when no correctly-owned piece of evidence mentions anything related to the question topic."
    )


def _build_question_date_line(query_timestamp: float | None) -> str:
    if query_timestamp is None:
        return ""
    qdt = datetime.fromtimestamp(query_timestamp, tz=timezone.utc)
    return (
        f"Question date: {qdt.strftime('%Y-%m-%d (%a) %H:%M')} UTC (timestamp={query_timestamp})\n"
    )


def _relative_time_instruction() -> str:
    return (
        "Use relative time expressions in the evidence when comparing event order.\n"
        "Do not rely only on replay timestamps if the content itself gives a clearer time relation.\n"
        "When the evidence provides a dated reference, convert relative time answers "
        "like 'last year', 'next month', 'last week', or 'yesterday' into the most specific "
        "absolute date, month, year, or anchored range supported by the evidence. "
        "Prefer the absolute form over repeating the relative phrase.\n\n"
    )


def _episode_section(prompt_payload: Any) -> str:
    if not prompt_payload.episode_text:
        return ""
    return f"\nEpisode Summaries:\n{prompt_payload.episode_text}\n"


def _build_eval_answer_user_prompt(
    *,
    question: str,
    prompt_payload: Any,
    l2_context_text: str,
    question_date_line: str,
) -> str:
    prefix = (
        _relative_time_instruction()
        + f"{prompt_payload.timeline_instruction}"
        + f"{prompt_payload.preference_instruction}"
        + f"{question_date_line}"
        + f"Question:\n{question}\n\n"
    )
    if prompt_payload.prioritize_timeline:
        return (
            prefix
            + f"Session Evidence Bundles:\n{prompt_payload.bundle_text}\n\n"
            + f"Retrieved Evidence:\n{prompt_payload.evidence_text}\n\n"
            + f"Knowledge Graph Context:\n{l2_context_text}\n"
            + f"{_episode_section(prompt_payload)}\n"
            + f"Timeline Summary (use this for temporal/ordering questions):\n{prompt_payload.timeline_text}\n"
        )
    return (
        prefix
        + f"Timeline Summary:\n{prompt_payload.timeline_text}\n\n"
        + f"Session Evidence Bundles:\n{prompt_payload.bundle_text}\n\n"
        + f"Retrieved Evidence:\n{prompt_payload.evidence_text}\n\n"
        + f"Knowledge Graph Context:\n{l2_context_text}\n"
        + f"{_episode_section(prompt_payload)}"
    )


def _log_answer_synthesis_started(
    log: Any,
    *,
    question: str,
    hits: list[dict[str, Any]],
    evidence_bundles: list[dict[str, Any]] | None,
    prompt_payload: Any,
    system_prompt: str,
    user_prompt: str,
) -> None:
    if not full_content_logging_enabled():
        log.info(
            "Eval query answer synthesis started",
            question_chars=len(question),
            evidence_hit_count=len(hits),
            evidence_bundle_count=len(evidence_bundles or []),
            evidence_chars=len(prompt_payload.evidence_text),
            system_prompt_chars=len(system_prompt),
            user_prompt_chars=len(user_prompt),
        )
        return
    log.info(
        "Eval query answer synthesis started",
        question=question,
        evidence_hit_count=len(hits),
        evidence_bundle_count=len(evidence_bundles or []),
        evidence_preview=prompt_payload.evidence_text[:800],
        llm_messages=(
            "==== SYSTEM MESSAGE ====\n"
            f"{system_prompt}\n"
            "==== USER MESSAGE ====\n"
            f"{user_prompt}\n"
            "==== END ANSWER LLM INPUT ===="
        ),
    )


async def _chat_eval_answer(
    bridge: LLMProviderBridge,
    *,
    system_prompt: str,
    user_prompt: str,
) -> str:
    raw_answer = await bridge.chat(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=4096,
        temperature=0.0,
        thinking_depth=ThinkingDepth.MEDIUM,
        timeout_seconds=EVAL_ANSWER_TIMEOUT,
        event_context={
            "request_kind": "eval:memory_answering",
            "agent_id": "memory_eval",
        },
    )
    return str(raw_answer or "")


def _log_answer_synthesis_completed(
    log: Any,
    *,
    question: str,
    hits: list[dict[str, Any]],
    raw_answer: str,
    normalized_answer: str,
) -> None:
    if not full_content_logging_enabled():
        log.info(
            "Eval query answer synthesis completed",
            question_chars=len(question),
            evidence_hit_count=len(hits),
            raw_answer_chars=len(raw_answer),
            answer_chars=len(normalized_answer),
        )
        return
    log.info(
        "Eval query answer synthesis completed",
        question=question,
        evidence_hit_count=len(hits),
        raw_answer=raw_answer,
        answer=normalized_answer,
    )


def _build_answer_trace(
    *,
    hits: list[dict[str, Any]],
    evidence_bundles: list[dict[str, Any]] | None,
    timeline_summary: list[dict[str, Any]] | None,
    l2_entity_cards: list[dict[str, Any]] | None,
    l2_relationships: list[dict[str, Any]] | None,
    l2_assertions: list[dict[str, Any]] | None,
    show_prompt: bool,
    user_prompt: str,
) -> dict[str, Any]:
    l2_count = len(l2_entity_cards or []) + len(l2_relationships or []) + len(l2_assertions or [])
    answer_trace = {
        "answer_source": "llm",
        "llm_scenario": LLMScenario.CORE.value,
        "evidence_hit_count": len(hits) + l2_count,
        "evidence_bundle_count": len(evidence_bundles or []),
        "evidence_timeline_count": len(timeline_summary or []),
    }
    if show_prompt:
        answer_trace["prompt"] = user_prompt
    return answer_trace
