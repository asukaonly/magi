"""Render raw L2/L3/L4 snippets into persona-voiced observations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from ...utils.diagnostic_logging import full_content_logging_enabled
from .contracts import ChatPortraitObservation, RawMemorySnippet


logger = logging.getLogger(__name__)


_VALID_KINDS = {"reflection", "assertion", "relationship", "procedure"}


_SYSTEM_PROMPT_TEMPLATE = (
    "You are {name}. Your identity: {identity}.\n"
    "{values_block}"
    "{biases_block}"
    "Speak in this style: {style}. "
    "Vocabulary you use: {vocab_avail}. Vocabulary you avoid: {vocab_avoid}."
    "{quirks_block}\n\n"
    "Below are memories you have recorded about the user over time. Each is "
    "labeled with a short token (M1, M2, M3, ...). "
    "The user is currently talking about: '{topic}'.\n\n"
    "Write 3-5 short observations IN YOUR VOICE about the user's patterns, "
    "character, or preferences as they relate to this topic. Each observation "
    "MUST:\n"
    "  (a) be in second person, addressing the user as '你'.\n"
    "  (b) cite at least one memory by its token (e.g. M1) — but ONLY inside "
    "the 'basis_refs' array. The tokens MUST NEVER appear in the 'text' "
    "field. The text reads like natural speech, with no IDs of any kind.\n"
    "  (c) reflect your personality and idiolect.\n"
    "  (d) STRICT LENGTH BUDGET: each 'text' is one or two short sentences, "
    "between 20 and 50 Chinese characters total. NEVER pile on more clauses, "
    "NEVER chain 3+ sentences. Short, pointed, breathable. If you have more "
    "to say, split into another observation instead of stuffing one card.\n\n"
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
    ) -> list[ChatPortraitObservation]:
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
            if full_content_logging_enabled():
                logger.warning(
                    "portrait lens render timed out after %.0fs "
                    "(snippets=%d topic=%r)",
                    self._timeout,
                    len(snippets),
                    topic,
                )
            else:
                logger.warning(
                    "portrait lens render timed out after %.0fs "
                    "(snippets=%d topic_chars=%d)",
                    self._timeout,
                    len(snippets),
                    len(topic),
                )
            return []
        except Exception as exc:
            if full_content_logging_enabled():
                logger.warning("portrait lens render failed: %s", exc, exc_info=True)
            else:
                logger.warning(
                    "portrait lens render failed: error_type=%s",
                    type(exc).__name__,
                )
            return []
        observations = self._parse(payload, token_to_id=token_to_id)
        if not observations:
            if full_content_logging_enabled():
                logger.warning(
                    "portrait lens render returned no usable observations "
                    "(raw=%r snippets=%d topic=%r)",
                    payload,
                    len(snippets),
                    topic,
                )
            else:
                logger.warning(
                    "portrait lens render returned no usable observations "
                    "(payload_type=%s snippets=%d topic_chars=%d)",
                    type(payload).__name__,
                    len(snippets),
                    len(topic),
                )
        return observations

    def _build_system_prompt(self, persona: dict[str, Any], topic: str) -> str:
        identity = persona.get("identity_core") or {}
        idiolect = persona.get("idiolect") or {}

        loved = [str(v) for v in (identity.get("values_loved") or []) if str(v).strip()]
        rejected = [str(v) for v in (identity.get("values_rejected") or []) if str(v).strip()]
        biases = [str(v) for v in (identity.get("attention_biases") or []) if str(v).strip()]
        quirks = [str(v) for v in (idiolect.get("structural_quirks") or []) if str(v).strip()]

        values_block = ""
        if loved or rejected:
            parts = []
            if loved:
                parts.append("You value: " + "; ".join(loved) + ".")
            if rejected:
                parts.append("You reject: " + "; ".join(rejected) + ".")
            values_block = " ".join(parts) + "\n"

        biases_block = ""
        if biases:
            biases_block = "You naturally pay attention to: " + "; ".join(biases) + ".\n"

        quirks_block = ""
        if quirks:
            quirks_block = " Structural quirks: " + "; ".join(quirks) + "."

        return _SYSTEM_PROMPT_TEMPLATE.format(
            name=persona.get("name") or "AI",
            identity=str(identity.get("identity_statement") or ""),
            values_block=values_block,
            biases_block=biases_block,
            style=str(idiolect.get("sentence_style") or ""),
            vocab_avail=", ".join(idiolect.get("vocab_available") or []) or "(none)",
            vocab_avoid=", ".join(idiolect.get("vocab_avoided") or []) or "(none)",
            quirks_block=quirks_block,
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
    ) -> list[ChatPortraitObservation]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("observations")
        if not isinstance(items, list):
            return []
        observations: list[ChatPortraitObservation] = []
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
            observations.append(ChatPortraitObservation(
                kind=kind,  # type: ignore[arg-type]
                text=text,
                basis_count=int(item.get("basis_count") or 0),
                basis_summary=str(item.get("basis_summary") or ""),
                basis_refs=basis_refs,
            ))
        return observations
