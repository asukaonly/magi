"""Batch LLM classifier for system suggestions.

Given recent conversation text + candidate capabilities, asks the core model
which capabilities are genuinely relevant.
Thinking is off; output is structured JSON. Used off the user-latency path
(fires after a turn); the engine degrades to keyword scoring on any failure.
"""
from __future__ import annotations

import json
import re

from magi.core.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You decide which of the user's available local data capabilities are "
    "relevant to what they just discussed. You are given the recent "
    "conversation and a list of candidate capabilities (category + rationale + "
    "example keywords). For each candidate, output a confidence 0.0-1.0 that "
    "connecting it would help answer the user's needs right now. Only score "
    "high when the conversation clearly implies that capability's data would "
    "help. Respond with JSON only: "
    '{"results":[{"category":"<category>","confidence":<0..1>}]}'
)


def build_user_prompt(recent_text: str, candidates: list[dict], locale: str) -> str:
    lines = [f"Recent conversation:\n{recent_text}\n", "Candidates:"]
    for c in candidates:
        kws = ", ".join(c.get("keywords", []))
        lines.append(f"- category={c['category']}; rationale={c.get('rationale','')}; keywords={kws}")
    lines.append('\nReturn JSON: {"results":[{"category":..., "confidence":...}]}')
    return "\n".join(lines)


def parse_classify_response(raw: str) -> dict[str, float]:
    """Parse the model's JSON into {category: confidence}, tolerant of fences."""
    if not raw:
        return {}
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}
    out: dict[str, float] = {}
    for item in (data or {}).get("results", []):
        cat = item.get("category")
        if not cat:
            continue
        try:
            conf = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        out[str(cat)] = min(1.0, max(0.0, conf))
    return out


async def classify_with_core_model(recent_text: str, candidates: list[dict], locale: str) -> dict[str, float]:
    """Classify suggestions off the interactive user-latency path."""
    from magi.config.models import LLMScenario
    from magi.llm.provider import get_scenario_llm_pool

    adapter = get_scenario_llm_pool().get(LLMScenario.CORE)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(recent_text, candidates, locale)},
    ]
    content = await adapter.chat(messages, max_tokens=300, temperature=0.0)
    return parse_classify_response(content)
