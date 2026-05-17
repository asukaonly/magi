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
    "Below are memories you have recorded about the user over time. Each is "
    "labeled with a short token (M1, M2, M3, ...). "
    "The user is currently talking about: '{topic}'.\n\n"
    "Write 1-5 short observations IN YOUR VOICE about the user's patterns, "
    "character, or preferences as they relate to this topic. Each observation "
    "MUST:\n"
    "  (a) be in second person, addressing the user as '你'.\n"
    "  (b) cite at least one memory by its token (e.g. M1) — but ONLY inside "
    "the 'basis_refs' array. The tokens MUST NEVER appear in the 'text' "
    "field. The text reads like natural speech, with no IDs of any kind.\n"
    "  (c) reflect your personality and idiolect.\n\n"
    "NEVER claim you don't know the user. If memories are sparse, write fewer "
    "but more cautious observations. Output strict JSON:\n"
    '{{"observations": [{{"kind": "reflection|assertion|relationship|procedure", '
    '"text": "你... (natural language, NO M-tokens here)", '
    '"basis_count": <int>, "basis_summary": "<short, no M-tokens>", '
    '"basis_refs": ["M1", "M2", ...]}}]}}'
)


class PersonaLensRenderer:
    """Render observations via an LLM call using the active persona's voice."""

    def __init__(
        self,
        *,
        bridge_factory: Callable[[], Any | None],
        timeout_seconds: float = 240.0,
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

        # Build M-token mapping so the LLM never sees raw UUIDs (which it tends
        # to copy into observation text). We map tokens back to real ids after
        # parsing the response.
        token_to_id: dict[str, str] = {}
        for idx, snippet in enumerate(snippets, start=1):
            token_to_id[f"M{idx}"] = snippet.id

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
        except asyncio.TimeoutError:
            logger.warning(
                "portrait lens render timed out after %.0fs (snippets=%d topic=%r)",
                self._timeout, len(snippets), topic,
            )
            return []
        except Exception as exc:
            logger.warning("portrait lens render failed: %s", exc, exc_info=True)
            return []
        observations = self._parse(payload, token_to_id=token_to_id)
        if not observations:
            logger.warning(
                "portrait lens render returned no usable observations "
                "(raw=%r snippets=%d topic=%r)",
                payload, len(snippets), topic,
            )
        return observations

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
        for idx, s in enumerate(snippets, start=1):
            confidence = f" ({s.confidence:.2f})" if s.confidence is not None else ""
            # Use a short M-token (M1, M2, ...) instead of the raw id so the
            # LLM doesn't copy long UUIDs into observation text.
            lines.append(f"- M{idx} [{s.kind}, {s.layer}{confidence}]: {s.statement}")
        if recent_message_excerpt.strip():
            lines.append("")
            lines.append(f"Recent user message excerpt: {recent_message_excerpt.strip()[:240]}")
        return "\n".join(lines)

    def _parse(
        self,
        payload: Any,
        *,
        token_to_id: dict[str, str] | None = None,
    ) -> list[PortraitObservation]:
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
            # Defense in depth: even if the LLM leaks tokens into the visible
            # text, strip them before they reach the UI.
            if token_to_id:
                for token in token_to_id:
                    text = text.replace(token, "").strip()
                text = " ".join(text.split())  # collapse repeated whitespace
                if not text:
                    continue
            basis_refs_raw = item.get("basis_refs") or []
            basis_refs: list[str] = []
            for ref in basis_refs_raw:
                ref_str = str(ref).strip()
                if not ref_str:
                    continue
                # Map M-tokens back to real ids when possible; otherwise drop.
                if token_to_id is not None:
                    if ref_str in token_to_id:
                        basis_refs.append(token_to_id[ref_str])
                else:
                    basis_refs.append(ref_str)
            observations.append(PortraitObservation(
                kind=kind,  # type: ignore[arg-type]
                text=text,
                basis_count=int(item.get("basis_count") or 0),
                basis_summary=str(item.get("basis_summary") or ""),
                basis_refs=basis_refs,
            ))
        return observations
