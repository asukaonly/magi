"""Lightweight LLM resolver for onboarding persona-generation intent."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ...config.models import LLMScenario, LLMSettings
from ...llm import LLMProviderBridge, create_llm_adapter
from ...llm.draft import resolve_adapter_for_scenario
from ..routers.personality_config_schemas import (
    PersonaIntentResolutionModel,
    PersonaReferenceCandidateModel,
)

PERSONA_INTENT_RESOLUTION_SYSTEM_PROMPT = """You resolve a short user description into persona-creation intent.

This is classification and extraction only. Do not design the persona, write dialogue, or invent backstory.
Return ONLY one valid JSON object with this shape:
{
  "status": "original" | "resolved" | "ambiguous" | "unknown",
  "confidence": 0.0,
  "candidates": [
    {
      "source_kind": "fictional_reference" | "public_person_reference" | "private_person_reference",
      "name": "",
      "work_title": null,
      "version": null,
      "context": null,
      "confidence": 0.0
    }
  ],
  "explicit_constraints": []
}

Rules:
1. Use "original" when the user only describes traits, behavior, profession, mood, or an original identity without referring to a specific existing person or character.
2. Use "resolved" only when one reference is clearly identified by the user's wording.
3. Use "ambiguous" when the same name plausibly points to multiple well-known characters, works, versions, or people. Return up to four useful candidates instead of guessing. A bare name such as "孙悟空" must preserve materially different candidates such as Journey to the West and Dragon Ball when applicable.
4. Use "unknown" when the user appears to reference someone but there is not enough information to identify whether they are fictional, a public person, or a private acquaintance.
5. A phrase such as "my friend", "my colleague", or "someone I know" is a private-person reference. Never infer private facts.
6. Preserve the user's explicit negative and positive constraints, such as "do not use the catchphrase often", in explicit_constraints.
7. Do not fabricate a work title, version, occupation, relationship, or private detail. Null is valid.
8. Candidate confidence describes identification confidence, not persona quality.
9. This step does not verify canon or public facts and must not claim that it did.
10. Keep names and work titles recognizable. Write context and constraints in the requested target language.
"""


def _extract_json_object(response_text: str) -> dict[str, Any]:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Persona intent resolver returned a non-object JSON value")
    return payload


def _optional_text(value: Any, *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_length] or None


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def normalize_persona_intent_resolution(payload: dict[str, Any]) -> PersonaIntentResolutionModel:
    """Normalize an LLM intent payload and derive confirmation behavior."""
    raw_candidates = payload.get("candidates")
    candidates: list[PersonaReferenceCandidateModel] = []
    seen: set[tuple[str, str, str, str]] = set()
    if isinstance(raw_candidates, list):
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue
            source_kind = str(raw.get("source_kind") or "").strip()
            if source_kind not in {
                "fictional_reference",
                "public_person_reference",
                "private_person_reference",
            }:
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            work_title = _optional_text(raw.get("work_title"), max_length=240)
            version = _optional_text(raw.get("version"), max_length=240)
            context = _optional_text(raw.get("context"), max_length=500)
            key = (
                source_kind.casefold(),
                name.casefold(),
                (work_title or "").casefold(),
                (version or "").casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                PersonaReferenceCandidateModel(
                    candidate_id=f"candidate-{len(candidates) + 1}",
                    source_kind=source_kind,
                    name=name[:160],
                    work_title=work_title,
                    version=version,
                    context=context,
                    confidence=_confidence(raw.get("confidence")),
                )
            )
            if len(candidates) >= 4:
                break

    raw_status = str(payload.get("status") or "").strip().lower()
    if raw_status == "original" and not candidates:
        status = "original"
    elif len(candidates) > 1 or raw_status == "ambiguous":
        status = "ambiguous"
    elif len(candidates) == 1:
        status = "resolved"
    else:
        status = "unknown"

    raw_constraints = payload.get("explicit_constraints")
    constraints: list[str] = []
    if isinstance(raw_constraints, list):
        for value in raw_constraints:
            text = str(value).strip()
            if text and text not in constraints:
                constraints.append(text[:500])
    confidence = _confidence(payload.get("confidence"))
    selected_candidate_id = candidates[0].candidate_id if status == "resolved" else None
    return PersonaIntentResolutionModel(
        status=status,
        candidates=candidates,
        selected_candidate_id=selected_candidate_id,
        confidence=confidence,
        requires_confirmation=status != "original",
        explicit_constraints=constraints,
    )


async def resolve_persona_generation_intent(
    description: str,
    *,
    target_language: str = "English",
    llm_override: Optional[LLMSettings] = None,
    adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
    adapter_factory: Callable[..., Any] = create_llm_adapter,
) -> PersonaIntentResolutionModel:
    """Resolve whether a persona description references an existing prototype."""
    adapter = adapter_resolver(
        LLMScenario.CORE,
        llm_settings=llm_override,
        adapter_factory=adapter_factory,
    )
    bridge = LLMProviderBridge(adapter)
    prompt = json.dumps(
        {
            "target_language": target_language,
            "user_description": description,
        },
        ensure_ascii=False,
        indent=2,
    )
    response = await bridge.chat(
        system_prompt=PERSONA_INTENT_RESOLUTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
        temperature=0.1,
        json_mode=True,
        disable_thinking=True,
        event_context={
            "request_kind": "personality:intent_resolution",
            "agent_id": "personality_generation",
        },
    )
    return normalize_persona_intent_resolution(_extract_json_object(response))


__all__ = [
    "PERSONA_INTENT_RESOLUTION_SYSTEM_PROMPT",
    "normalize_persona_intent_resolution",
    "resolve_persona_generation_intent",
]
