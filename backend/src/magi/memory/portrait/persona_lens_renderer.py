"""Render raw L2/L3/L4 snippets into persona-voiced observations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from .contracts import PortraitObservation, RawMemorySnippet


logger = logging.getLogger(__name__)


_VALID_KINDS = {"reflection", "assertion", "relationship", "procedure"}


_SYSTEM_PROMPT_TEMPLATE = (
    "You are {name}. Your identity: {identity}. "
    "Speak in this style: {style}. "
    "Vocabulary you use: {vocab_avail}. Vocabulary you avoid: {vocab_avoid}.\n\n"
    "Below are memories you have recorded about the user over time. "
    "The user is currently talking about: '{topic}'.\n\n"
    "Write 1-5 short observations IN YOUR VOICE about the user's patterns, "
    "character, or preferences as they relate to this topic. Each observation "
    "MUST: (a) be in second person, addressing the user as '你'; "
    "(b) reference at least one memory id from the list as its basis; "
    "(c) reflect your personality and idiolect.\n\n"
    "NEVER claim you don't know the user. If memories are sparse, write fewer "
    "but more cautious observations. Output strict JSON:\n"
    '{{"observations": [{{"kind": "reflection|assertion|relationship|procedure", '
    '"text": "你...", "basis_count": <int>, "basis_summary": "<short>", '
    '"basis_refs": ["mem_id", ...]}}]}}'
)


class PersonaLensRenderer:
    """Render observations via an LLM call using the active persona's voice."""

    def __init__(
        self,
        *,
        bridge_factory: Callable[[], Any | None],
        timeout_seconds: float = 120.0,
    ) -> None:
        self._bridge_factory = bridge_factory
        self._timeout = float(timeout_seconds)

    async def render(
        self,
        *,
        persona_config: dict[str, Any],
        snippets: list[RawMemorySnippet],
        recent_message_excerpt: str,
        topic: str,
    ) -> list[PortraitObservation]:
        if not snippets:
            return []
        bridge = self._bridge_factory()
        if bridge is None:
            return []
        system_prompt = self._build_system_prompt(persona_config, topic)
        user_prompt = self._build_user_prompt(snippets, recent_message_excerpt)
        try:
            payload = await asyncio.wait_for(
                bridge.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                ),
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.debug("portrait lens render failed: %s", exc)
            return []
        return self._parse(payload)

    def _build_system_prompt(self, persona: dict[str, Any], topic: str) -> str:
        identity = persona.get("identity_core") or {}
        idiolect = persona.get("idiolect") or {}
        return _SYSTEM_PROMPT_TEMPLATE.format(
            name=persona.get("name") or "AI",
            identity=str(identity.get("identity_statement") or ""),
            style=str(idiolect.get("sentence_style") or ""),
            vocab_avail=", ".join(idiolect.get("vocab_available") or []) or "(none)",
            vocab_avoid=", ".join(idiolect.get("vocab_avoided") or []) or "(none)",
            topic=topic or "(unspecified)",
        )

    def _build_user_prompt(
        self,
        snippets: list[RawMemorySnippet],
        recent_message_excerpt: str,
    ) -> str:
        lines = ["Memories about the user:"]
        for s in snippets:
            confidence = f" ({s.confidence:.2f})" if s.confidence is not None else ""
            lines.append(f"- {s.id} [{s.kind}, {s.layer}{confidence}]: {s.statement}")
        if recent_message_excerpt.strip():
            lines.append("")
            lines.append(f"Recent user message excerpt: {recent_message_excerpt.strip()[:240]}")
        return "\n".join(lines)

    def _parse(self, payload: Any) -> list[PortraitObservation]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("observations")
        if not isinstance(items, list):
            return []
        observations: list[PortraitObservation] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip()
            if kind not in _VALID_KINDS:
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            basis_refs_raw = item.get("basis_refs") or []
            basis_refs = [str(r) for r in basis_refs_raw if r]
            observations.append(PortraitObservation(
                kind=kind,  # type: ignore[arg-type]
                text=text,
                basis_count=int(item.get("basis_count") or 0),
                basis_summary=str(item.get("basis_summary") or ""),
                basis_refs=basis_refs,
            ))
        return observations
