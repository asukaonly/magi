"""Shared batched understanding for L0 attention and interaction outcomes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any

from magi.core.logger import get_logger
from magi.memory.l0.attention import AttentionActionType, AttentionUpdateAction
from magi.memory.l0.attention_update_scheduler import (
    AttentionBatch,
)

from .interaction_analyzer import (
    DEFAULT_ANALYSIS,
    InteractionAnalysis,
    InteractionObservation,
    _compact_observation_args,
    _resolve_analysis_bridge,
    _with_memory_observations,
    parse_analysis,
)

logger = get_logger(__name__)

_ALLOWED_OBSERVATION_KINDS = {
    "profile_signal",
    "task_preference",
    "persona_relationship_signal",
}
_TURN_INPUT_BUDGET_CHARS = 18_000
_MAX_USER_MESSAGE_CHARS = 1_600
_MAX_ASSISTANT_RESPONSE_CHARS = 2_000

_SYSTEM_PROMPT = """\
You update a personal desktop agent's short-term attention after accepted chat turns.
Return one JSON object only.

The result has:
- "turns": one analysis row for every supplied turn_id, preserving the input order.
- "attention_actions": a patch against the supplied current attention frame.

Each turn analysis row contains:
turn_id, sentiment (-1..1), engagement (none|low|medium|high|very_high),
complexity (0..1), outcome (success|partial|failure),
satisfaction (very_low|low|neutral|high|very_high),
optional trigger_type, milestone_keys, and memory_observations.

Memory observations are optional explicit durable evidence from the user's own words:
- profile_signal arguments: trait_family, trait_name, trait_value, evidence_text, confidence
- task_preference arguments: task_category, preference, polarity, evidence_text, confidence
- persona_relationship_signal arguments: signal_type, optional milestone_key or trust_delta,
  evidence_text, confidence
Do not infer durable preferences from one-off wording. Emit at most three observations total.

Attention is not a transcript summary or a task list. It is the minimum state needed to
understand and naturally continue the next few turns. Supported kinds:
focus, situation, open_loop, active_object, constraint, consensus.

Supported attention actions:
- add: requires kind, a short neutral summary, and source_turn_ids.
- reinforce: targets an existing item_id; may refine its summary.
- resolve: targets an existing item_id that the exchange closed.
- supersede: targets an existing item_id and requires the replacement kind and summary.
- background: targets an existing item_id after a real topic shift.

Each action also carries salience (0..1), confidence (0..1), evidence_mode
(direct|inferred), source_turn_ids, optional entity_id, and optional task_id.

Rules:
- Do not copy a user's sentence verbatim into attention.
- Prefer direct evidence. Mark cautious interpretations as inferred.
- A task is only one possible open_loop.
- Tool execution details are not attention.
- Do not add durable facts merely because the assistant said them.
- A correction supersedes old attention; a resolved question is resolved.
- Do not background an item merely because one adjacent sentence is casual.
- Emit no action when the frame is already correct.
- Emit at most twelve attention actions.
"""


@dataclass(frozen=True, slots=True)
class BatchInteractionAnalysis:
    """Validated output of one shared batch-understanding call."""

    turn_analyses: dict[str, InteractionAnalysis]
    attention_actions: tuple[AttentionUpdateAction, ...]


async def analyze_interaction_batch(
    batch: AttentionBatch,
    *,
    current_attention: list[dict[str, Any]],
    stp_rules: list[dict[str, str]] | None = None,
    milestone_conditions: dict[str, str] | None = None,
) -> BatchInteractionAnalysis | None:
    """Analyze accepted turns and one attention delta with a single LLM call."""

    if not batch:
        return None
    bridge = _resolve_analysis_bridge()
    if bridge is None:
        return BatchInteractionAnalysis(
            turn_analyses={turn.turn_id: DEFAULT_ANALYSIS for turn in batch},
            attention_actions=(),
        )

    prompt = _build_batch_prompt(
        batch,
        current_attention=current_attention,
        stp_rules=stp_rules,
        milestone_conditions=milestone_conditions,
    )
    started_at = time.monotonic()
    try:
        raw = await bridge.chat(
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2200,
            temperature=0.1,
            json_mode=True,
            disable_thinking=True,
            event_context={
                "request_kind": "memory:shared_post_turn_understanding",
                "agent_id": "memory:l0_attention_updater",
            },
        )
        parsed = parse_interaction_batch(
            raw,
            batch=batch,
            current_attention=current_attention,
            stp_rules=stp_rules,
        )
    except Exception:
        logger.warning(
            "Shared post-turn understanding failed",
            elapsed_ms=(time.monotonic() - started_at) * 1000,
            exc_info=True,
        )
        return None
    if parsed is None:
        logger.warning(
            "Shared post-turn understanding returned an invalid payload",
            elapsed_ms=(time.monotonic() - started_at) * 1000,
        )
        return None
    logger.info(
        "Shared post-turn understanding completed",
        elapsed_ms=(time.monotonic() - started_at) * 1000,
        turn_count=len(batch),
        attention_action_count=len(parsed.attention_actions),
    )
    return parsed


def parse_interaction_batch(
    raw: str,
    *,
    batch: AttentionBatch,
    current_attention: list[dict[str, Any]],
    stp_rules: list[dict[str, str]] | None = None,
) -> BatchInteractionAnalysis | None:
    """Parse and constrain one untrusted shared-understanding response."""

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("turns"), list):
        return None

    allowed_turn_ids = tuple(turn.turn_id for turn in batch)
    allowed_turn_set = set(allowed_turn_ids)
    analyses: dict[str, InteractionAnalysis] = {}
    total_observations = 0
    for row in payload["turns"]:
        if not isinstance(row, dict):
            continue
        turn_id = str(row.get("turn_id") or "").strip()
        if turn_id not in allowed_turn_set or turn_id in analyses:
            continue
        analysis = parse_analysis(json.dumps(row), stp_rules=stp_rules)
        observations: list[InteractionObservation] = []
        raw_observations = row.get("memory_observations")
        if not isinstance(raw_observations, list):
            raw_observations = []
        for observation in raw_observations:
            if total_observations >= 3 or not isinstance(observation, dict):
                break
            kind = str(observation.get("kind") or "").strip()
            arguments = observation.get("arguments")
            if kind not in _ALLOWED_OBSERVATION_KINDS or not isinstance(arguments, dict):
                continue
            observations.append(
                InteractionObservation(
                    kind=kind,
                    arguments=_compact_observation_args(arguments),
                )
            )
            total_observations += 1
        analyses[turn_id] = _with_memory_observations(analysis, observations)

    for turn_id in allowed_turn_ids:
        analyses.setdefault(turn_id, DEFAULT_ANALYSIS)

    existing_ids = {
        str(item.get("item_id") or "").strip()
        for item in current_attention
        if str(item.get("item_id") or "").strip()
    }
    actions: list[AttentionUpdateAction] = []
    raw_actions = payload.get("attention_actions", [])
    if isinstance(raw_actions, list):
        for raw_action in raw_actions[:12]:
            if not isinstance(raw_action, dict):
                continue
            action = AttentionUpdateAction.from_payload(
                raw_action,
                allowed_turn_ids=allowed_turn_ids,
            )
            if action is None:
                continue
            if (
                action.action is not AttentionActionType.ADD
                and str(action.target_item_id or "") not in existing_ids
            ):
                continue
            if not action.source_turn_ids:
                continue
            actions.append(action)

    return BatchInteractionAnalysis(
        turn_analyses=analyses,
        attention_actions=tuple(actions),
    )


def _build_batch_prompt(
    batch: AttentionBatch,
    *,
    current_attention: list[dict[str, Any]],
    stp_rules: list[dict[str, str]] | None,
    milestone_conditions: dict[str, str] | None,
) -> str:
    per_turn_budget = max(
        400,
        min(
            _MAX_USER_MESSAGE_CHARS + _MAX_ASSISTANT_RESPONSE_CHARS,
            _TURN_INPUT_BUDGET_CHARS // max(1, len(batch)),
        ),
    )
    user_budget = min(
        _MAX_USER_MESSAGE_CHARS,
        max(160, int(per_turn_budget * 0.45)),
    )
    response_budget = min(
        _MAX_ASSISTANT_RESPONSE_CHARS,
        max(200, per_turn_budget - user_budget),
    )
    payload = {
        "current_attention": [
            {
                "item_id": item.get("item_id"),
                "kind": item.get("kind"),
                "summary": item.get("summary"),
                "status": item.get("status"),
                "salience": item.get("salience"),
                "confidence": item.get("confidence"),
                "evidence_mode": item.get("evidence_mode"),
                "entity_id": item.get("entity_id"),
                "task_id": item.get("task_id"),
            }
            for item in current_attention[:24]
        ],
        "turns": [
            {
                "turn_id": turn.turn_id,
                "user_message": _truncate_for_batch(
                    turn.user_message,
                    user_budget,
                ),
                "assistant_response": _truncate_for_batch(
                    turn.assistant_response,
                    response_budget,
                ),
            }
            for turn in batch
        ],
        "persona_trigger_rules": list(stp_rules or []),
        "milestone_conditions": dict(milestone_conditions or {}),
    }
    return json.dumps(payload, ensure_ascii=False)


def _truncate_for_batch(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    marker = "\n...[middle omitted]...\n"
    available = max(0, limit - len(marker))
    head = available // 2
    tail = available - head
    return f"{text[:head]}{marker}{text[-tail:] if tail else ''}"


__all__ = [
    "BatchInteractionAnalysis",
    "analyze_interaction_batch",
    "parse_interaction_batch",
]
