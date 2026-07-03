"""LLM-backed selection for promoting experience seeds."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import logging
from typing import Any, Mapping

from ....i18n import llm_language_label
from ....llm import LLMProviderBridge, LLMRequestPriority, LLMScenario, ScenarioLLMPool
from .seed_selection import _default_selection

logger = logging.getLogger(__name__)

_MAX_PROMPT_EPISODES = 20


def build_experience_seed_selector(
    *,
    scenario_llm_pool: ScenarioLLMPool | None,
    enabled: bool,
    timeout_seconds: float,
) -> Any | None:
    """Build a SelectionProvider when LLM seed selection is enabled."""
    if not enabled or scenario_llm_pool is None:
        return None
    service = ExperienceSeedSelectionLLMService(
        enabled=enabled,
        llm_timeout_seconds=timeout_seconds,
        scenario_llm_pool=scenario_llm_pool,
    )
    return service.select


def scenario_llm_pool_from_unified_memory(unified_memory: Any) -> ScenarioLLMPool | None:
    """Read the explicitly stored scenario pool without triggering mock attrs."""
    try:
        value = vars(unified_memory).get("scenario_llm_pool")
    except TypeError:
        value = None
    return value if value is not None else None


class ExperienceSeedSelectionLLMService:
    """Select coherent experience evidence from a seed with deterministic fallback."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 30.0,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._llm_timeout_seconds = float(llm_timeout_seconds)
        self._scenario_llm_pool = scenario_llm_pool

    async def select(
        self,
        seed: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> Mapping[str, Any]:
        """Return a validated selector mapping, falling back on any unsafe output."""
        if not self._enabled or self._scenario_llm_pool is None:
            return self._default(seed, evidence_pack)
        try:
            payload = await asyncio.wait_for(
                self._call_selector_model(seed, evidence_pack),
                timeout=self._llm_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("L2 experience seed selection LLM failed", extra={"error": str(exc)})
            return self._default(seed, evidence_pack)
        return self._validated_payload(payload, seed=seed, evidence_pack=evidence_pack)

    async def _call_selector_model(
        self,
        seed: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> dict[str, Any] | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, bridge = llm_target
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        logger.info(
            "L2 experience seed selection LLM call started",
            extra={"provider": provider, "model": model, "seed_id": seed.get("seed_id")},
        )
        response = await bridge.chat_response(
            system_prompt=_system_prompt(),
            messages=[{"role": "user", "content": _render_user_prompt(seed, evidence_pack)}],
            json_mode=True,
            temperature=0.0,
            disable_thinking=True,
            cache_system=True,
            timeout_seconds=self._llm_timeout_seconds,
            event_context={
                "request_kind": "memory:l2_experience_seed_selection",
                "turn_id": str(seed.get("seed_id") or ""),
                "agent_id": "memory:l2",
            },
            priority=LLMRequestPriority.LOW,
        )
        raw = str(response.content or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("L2 experience seed selection LLM returned invalid JSON")
            return None
        return parsed if isinstance(parsed, dict) else None

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        for scenario in (LLMScenario.MEMORY_SUMMARIZER, LLMScenario.CORE):
            try:
                adapter = self._scenario_llm_pool.get(scenario)
                if adapter is not None:
                    return adapter
            except Exception as exc:
                logger.debug("Experience seed selector adapter unavailable for %s: %s", scenario, exc)
        return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _validated_payload(
        self,
        payload: Mapping[str, Any] | None,
        *,
        seed: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            return self._default(seed, evidence_pack)

        candidate_episodes = _candidate_episode_map(evidence_pack)
        if not bool(payload.get("is_experience")):
            return {
                "is_experience": False,
                "title": str(payload.get("title") or seed.get("title") or "").strip(),
                "one_sentence_review": "",
                "included_episode_ids": [],
                "included_event_ids": [],
                "excluded_refs": _valid_excluded_refs(payload, candidate_episodes),
                "time_start": None,
                "time_end": None,
                "confidence": float(payload.get("confidence") or 0.0),
                "reason": str(payload.get("reason") or "Selector rejected this seed.").strip(),
                "primary_entity_ids": [],
                "primary_place_ids": [],
                "primary_topic_keys": [],
            }

        included_ids = [
            episode_id
            for episode_id in _ordered_strings(payload.get("included_episode_ids") or [])
            if episode_id in candidate_episodes
        ]
        if not included_ids:
            return self._default(seed, evidence_pack)

        included_episodes = [candidate_episodes[episode_id] for episode_id in included_ids]
        title = str(payload.get("title") or "").strip()
        review = str(payload.get("one_sentence_review") or "").strip()
        if not title or not review:
            return self._default(seed, evidence_pack)
        return {
            "is_experience": True,
            "title": title,
            "one_sentence_review": review,
            "included_episode_ids": included_ids,
            "included_event_ids": [],
            "excluded_refs": _valid_excluded_refs(payload, candidate_episodes),
            "time_start": min(float(episode["time_start"]) for episode in included_episodes),
            "time_end": max(float(episode["time_end"]) for episode in included_episodes),
            "confidence": float(payload.get("confidence") or 0.0),
            "reason": str(payload.get("reason") or "").strip(),
            "primary_entity_ids": _validated_anchor_ids(
                payload.get("primary_entity_ids") or [],
                included_episodes,
                "primary_entity_ids",
            ),
            "primary_place_ids": _validated_anchor_ids(
                payload.get("primary_place_ids") or [],
                included_episodes,
                "primary_place_ids",
            ),
            "primary_topic_keys": _validated_anchor_ids(
                payload.get("primary_topic_keys") or [],
                included_episodes,
                "primary_topic_keys",
            ),
        }

    @staticmethod
    def _default(seed: dict[str, Any], evidence_pack: dict[str, Any]) -> dict[str, Any]:
        return asdict(_default_selection(seed, evidence_pack))


def _system_prompt() -> str:
    target = llm_language_label(default="en")
    return (
        "You select whether an experience seed should become one coherent user-facing memory.\n"
        f"Write title and one_sentence_review in {target}.\n"
        "Return JSON only. Do not invent facts outside the evidence.\n"
        "Reject low-information browsing or app streams with is_experience=false.\n"
        "Titles must be concrete, specific, and include names found in evidence."
    )


def _render_user_prompt(seed: dict[str, Any], evidence_pack: dict[str, Any]) -> str:
    candidate_episodes = list(evidence_pack.get("candidate_episodes") or [])[:_MAX_PROMPT_EPISODES]
    payload = {
        "seed": {
            "title": seed.get("title"),
            "description": seed.get("description"),
            "seed_type": seed.get("seed_type"),
            "anchor_entity_ids": seed.get("anchor_entity_ids") or [],
            "anchor_place_ids": seed.get("anchor_place_ids") or [],
            "anchor_topic_keys": seed.get("anchor_topic_keys") or [],
            "time_start": seed.get("time_start"),
            "time_end": seed.get("time_end"),
        },
        "trigger_episode_ids": evidence_pack.get("trigger_episode_ids") or [],
        "candidate_episodes": [
            {
                "episode_id": episode.get("episode_id"),
                "label": episode.get("label") or episode.get("user_label"),
                "summary": episode.get("summary"),
                "time_start": episode.get("time_start"),
                "time_end": episode.get("time_end"),
                "primary_entity_ids": episode.get("primary_entity_ids") or [],
                "primary_place_ids": episode.get("primary_place_ids") or [],
                "primary_topic_keys": episode.get("primary_topic_keys") or [],
            }
            for episode in candidate_episodes
        ],
        "output_schema": {
            "is_experience": True,
            "title": "short concrete title",
            "one_sentence_review": "one grounded sentence",
            "included_episode_ids": ["episode id"],
            "excluded_refs": [{"ref_type": "episode", "ref_id": "episode id", "reason": "why excluded"}],
            "time_start": 0,
            "time_end": 0,
            "confidence": 0.8,
            "reason": "selection rationale",
            "primary_entity_ids": [],
            "primary_place_ids": [],
            "primary_topic_keys": [],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _candidate_episode_map(evidence_pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(episode.get("episode_id") or ""): episode
        for episode in (evidence_pack.get("candidate_episodes") or [])
        if str(episode.get("episode_id") or "").strip()
    }


def _ordered_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in (values if isinstance(values, list) else []):
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _valid_excluded_refs(
    payload: Mapping[str, Any],
    candidate_episodes: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in payload.get("excluded_refs") or []:
        if not isinstance(item, Mapping):
            continue
        ref_type = str(item.get("ref_type") or "episode").strip()
        ref_id = str(item.get("ref_id") or "").strip()
        if ref_type != "episode" or ref_id not in candidate_episodes:
            continue
        result.append({
            "ref_type": ref_type,
            "ref_id": ref_id,
            "reason": str(item.get("reason") or "").strip(),
        })
    return result


def _validated_anchor_ids(
    values: Any,
    included_episodes: list[dict[str, Any]],
    key: str,
) -> list[str]:
    allowed = {
        str(value)
        for episode in included_episodes
        for value in (episode.get(key) or [])
        if str(value or "").strip()
    }
    return [value for value in _ordered_strings(values) if value in allowed]


__all__ = [
    "ExperienceSeedSelectionLLMService",
    "build_experience_seed_selector",
    "scenario_llm_pool_from_unified_memory",
]
