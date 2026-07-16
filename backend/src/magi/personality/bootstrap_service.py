"""Bootstrap dialogue service for first-contact persona conversations.

Bootstrap is a one-shot opening injection, not a separate post-opening chat flow.
The opening is generated via LLM and persisted as the first assistant message.
After that, all user messages stay on the normal ChatTaskAgent -> chat projector ->
UnifiedMemory -> L2 pipeline path. A short-lived queue hint may still request
faster L2 flushing right after the opening so profile facts become available to
subsequent turns quickly.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from ..config.models import LLMScenario
from ..core.logger import get_logger
from ..i18n import llm_language_label
from ..llm import LLMProviderBridge
from ..llm.provider import get_scenario_llm_pool
from ..utils.runtime import get_runtime_paths
from .active_persona import resolve_persona_config
from .growth_memory import GrowthMemoryEngine, MilestoneType
from .loader import BootstrapConfig, PersonalityConfig

logger = get_logger(__name__)

BOOTSTRAP_OPENING_LLM_TIMEOUT_SECONDS = 10.0
BOOTSTRAP_L2_PRIORITY_MAX_WAIT_SECONDS = 1.0
BOOTSTRAP_L2_PRIORITY_WINDOW_SECONDS = 15 * 60
BOOTSTRAP_IMPORT_SAMPLE_WINDOW_SECONDS = 7 * 24 * 60 * 60
BOOTSTRAP_IMPORT_SAMPLE_MAX_SOURCES = 4
BOOTSTRAP_IMPORT_SAMPLE_PER_SOURCE = 6
BOOTSTRAP_IMPORT_SAMPLE_QUERY_LIMIT = 24
BOOTSTRAP_IMPORT_SAMPLE_MAX_CHARS = 180
_URL_PATTERN = re.compile(r"https?://[^\s)>\]\"']+")
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LOW_SIGNAL_IMPORT_SAMPLE_TERMS = (
    "gmail",
    "inbox",
    "收件箱",
    "登录",
    "登陆",
    "注册",
    "sign in",
    "log in",
    "login",
    "register",
    "auth",
    "password",
    "密码",
    "验证码",
)

_growth_engine_instance: GrowthMemoryEngine | None = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_persona_list(items: Any, *, limit: Optional[int] = None) -> str:
    """Join a persona string list into a compact ``; ``-separated inline string."""
    cleaned = [str(item).strip() for item in (items or []) if str(item).strip()]
    if limit is not None:
        cleaned = cleaned[:limit]
    return "; ".join(cleaned)


def _chattiness_label(value: Any) -> str:
    """Map a 0..1 chattiness score to a coarse verbosity label for the prompt."""
    score = _safe_float(value, 0.5)
    if score <= 0.34:
        return "terse"
    if score >= 0.67:
        return "chatty"
    return "balanced"


def _select_voice_examples(
    config: PersonalityConfig,
    bootstrap: BootstrapConfig,
    *,
    limit: int = 2,
    max_chars: int = 220,
) -> List[str]:
    """Pick a few short voice-anchor examples for the opening prompt.

    Prefers author-curated ``bootstrap.opening_examples``; falls back to the
    persona's ``chat`` register examples. Each example is whitespace-collapsed
    and truncated so the opening prompt stays compact.
    """
    raw = list(getattr(bootstrap, "opening_examples", []) or [])
    if not raw:
        chat_register = (config.registers or {}).get("chat")
        if chat_register is not None:
            raw = list(getattr(chat_register, "examples", []) or [])

    examples: List[str] = []
    for item in raw:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = f"{text[: max_chars - 3].rstrip()}..."
        examples.append(text)
        if len(examples) >= limit:
            break
    return examples


def _strip_url_tracking(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "", "", ""))
    except Exception:
        return raw.split("?", 1)[0].split("#", 1)[0]


def _compact_import_sample_content(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    text = _URL_PATTERN.sub(_strip_url_tracking, text)
    text = _EMAIL_PATTERN.sub("[email]", text)
    if len(text) > BOOTSTRAP_IMPORT_SAMPLE_MAX_CHARS:
        text = f"{text[: BOOTSTRAP_IMPORT_SAMPLE_MAX_CHARS - 3].rstrip()}..."
    return text


def _is_low_signal_import_sample(value: str) -> bool:
    normalized = value.lower()
    return any(term in normalized for term in _LOW_SIGNAL_IMPORT_SAMPLE_TERMS)


def _event_timestamp(row: Any) -> float:
    if not isinstance(row, dict):
        return 0.0
    return _safe_float(row.get("timestamp"))


def _created_at_timestamp(row: Any) -> float:
    if not isinstance(row, dict):
        return 0.0
    return _safe_float(row.get("created_at"))


def _is_recent_event_sample(row: Any, cutoff: float) -> bool:
    event_ts = _event_timestamp(row)
    return event_ts > 0 and event_ts >= cutoff


def _is_recent_import_sample_without_event_time(row: Any, cutoff: float) -> bool:
    if _event_timestamp(row) > 0:
        return False
    return _created_at_timestamp(row) >= cutoff


async def _query_source_bootstrap_samples(l1: Any, source: str, cutoff: float) -> list[dict[str, Any]]:
    rows = await l1.query_events(
        source_filters=[source],
        cognition_eligible=True,
        start_time=cutoff,
        limit=BOOTSTRAP_IMPORT_SAMPLE_QUERY_LIMIT,
        order_by="timestamp_desc",
        include_embedding_fields=False,
    )
    recent_rows = [row for row in rows or [] if _is_recent_event_sample(row, cutoff)]
    if recent_rows:
        return recent_rows

    fallback_rows = await l1.query_events(
        source_filters=[source],
        cognition_eligible=True,
        limit=BOOTSTRAP_IMPORT_SAMPLE_QUERY_LIMIT,
        order_by="created_at_desc",
        include_embedding_fields=False,
    )
    return [
        row
        for row in fallback_rows or []
        if _is_recent_import_sample_without_event_time(row, cutoff)
    ]


async def _fetch_recent_import_activity_snippet(memory: Any) -> Optional[str]:
    l1 = getattr(memory, "l1", None)
    if l1 is None or not hasattr(l1, "summarize_event_sources") or not hasattr(l1, "query_events"):
        return None

    source_rows = await l1.summarize_event_sources(cognition_eligible=True)
    if not source_rows:
        return None

    cutoff = time.time() - BOOTSTRAP_IMPORT_SAMPLE_WINDOW_SECONDS
    source_blocks: list[tuple[str, list[str]]] = []
    for source_row in source_rows:
        source = str((source_row or {}).get("source") or "").strip()
        if not source:
            continue
        rows = await _query_source_bootstrap_samples(l1, source, cutoff)
        samples: list[str] = []
        for row in rows or []:
            content = _compact_import_sample_content(row.get("content"))
            if content and not _is_low_signal_import_sample(content):
                samples.append(content)
            if len(samples) >= BOOTSTRAP_IMPORT_SAMPLE_PER_SOURCE:
                break
        if samples:
            source_blocks.append((source, samples))
        if len(source_blocks) >= BOOTSTRAP_IMPORT_SAMPLE_MAX_SOURCES:
            break

    if not source_blocks:
        return None

    lines: list[str] = []
    for source, samples in source_blocks:
        lines.append(f"- Source {source}:")
        for sample in samples:
            lines.append(f"  - {sample}")
    return "\n".join(lines)


async def _fetch_recent_activity_snippet() -> Optional[str]:
    """Best-effort one-line 'what magi can already see' summary, or None.

    Used to make the first opening data-aware. Any failure (no memory, no data,
    ingest not done yet) returns None so the opener falls back to the existing
    'ask the user' behavior. Never fabricates.
    """
    try:
        from ..memory.provider import get_unified_memory

        memory = get_unified_memory()
    except Exception as exc:  # noqa: BLE001 - best-effort, never block the opening
        logger.info("bootstrap memory unavailable: %s", exc)
        return None

    try:
        import_snippet = await _fetch_recent_import_activity_snippet(memory)
        if import_snippet:
            return import_snippet
    except Exception as exc:  # noqa: BLE001 - import samples are best-effort
        logger.info("bootstrap recent-import snippet unavailable: %s", exc)

    try:
        summary = await memory.generate_source_activity_summary(
            summary_category="bootstrap_opening",
            source_filter=[],
            period_type="day",
            min_events=1,
        )
        if not summary:
            return None
        # The L3 temporal-summary dict carries its prose under "content"
        # (with an optional richer "essence_prose"); there is no "summary" key.
        text = str(
            summary.get("content") or summary.get("essence_prose") or ""
        ).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - best-effort, never block the opening
        logger.info("bootstrap recent-activity snippet unavailable: %s", exc)
        return None


def _milestone_matches_persona(milestone: Any, persona_name: str, persona_id: str) -> bool:
    metadata = getattr(milestone, "metadata", {}) or {}
    if persona_id and metadata.get("persona_id") == persona_id:
        return True
    return metadata.get("persona_name") == persona_name


def _milestone_matches_scope(
    milestone: Any,
    *,
    persona_name: str,
    persona_id: str,
    user_id: str,
    session_id: str,
) -> bool:
    metadata = getattr(milestone, "metadata", {}) or {}
    if not _milestone_matches_persona(milestone, persona_name, persona_id):
        return False
    if user_id and str(metadata.get("user_id") or "") != user_id:
        return False
    if session_id and str(metadata.get("session_id") or "") != session_id:
        return False
    return True


async def get_shared_growth_engine() -> GrowthMemoryEngine:
    """Return a lazily initialized GrowthMemoryEngine singleton."""
    global _growth_engine_instance
    if _growth_engine_instance is None:
        runtime_paths = get_runtime_paths()
        _growth_engine_instance = GrowthMemoryEngine(str(runtime_paths.growth_db_path))
        await _growth_engine_instance.init()
    return _growth_engine_instance


async def build_bootstrap_l2_priority_metadata(
    *,
    user_id: str,
    session_id: str = "",
    persona_name: str,
    persona_id: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """Return short-lived queue overrides right after the opening is injected."""
    normalized_persona_name = str(persona_name or "").strip()
    if not normalized_persona_name:
        return {}

    if not force:
        growth_engine = await get_shared_growth_engine()
        started_milestones = await growth_engine.get_milestones(
            milestone_type=MilestoneType.BOOTSTRAP_STARTED,
            limit=20,
        )
        matching = next(
            (
                milestone
                for milestone in started_milestones
                if _milestone_matches_scope(
                    milestone,
                    persona_name=normalized_persona_name,
                    persona_id=persona_id,
                    user_id=user_id,
                    session_id=session_id,
                )
            ),
            None,
        )
        if matching is None:
            return {}
        if (
            time.time() - float(getattr(matching, "timestamp", 0.0) or 0.0)
        ) > BOOTSTRAP_L2_PRIORITY_WINDOW_SECONDS:
            return {}

    owner_suffix = str(persona_id or normalized_persona_name).strip()
    if not owner_suffix:
        raise ValueError("bootstrap L2 priority metadata requires persona_id or persona_name")
    return {
        "l2_batch_owner": f"bootstrap:{user_id}:{owner_suffix}",
        "l2_batch_max_events": 1,
        "l2_batch_min_ready_events": 1,
        "l2_batch_max_wait_seconds": BOOTSTRAP_L2_PRIORITY_MAX_WAIT_SECONDS,
    }


class BootstrapDialogueService:
    """Orchestrates the one-shot first-contact opening for a persona."""

    def __init__(
        self,
        *,
        growth_engine: GrowthMemoryEngine,
        l2_store: Any = None,
        memory_snippet_provider: Callable[[], Awaitable[Optional[str]]] | None = None,
    ) -> None:
        self._growth_engine = growth_engine
        self._l2_store = l2_store
        self._memory_snippet_provider = memory_snippet_provider

    async def needs_bootstrap(self, persona_name: str, *, persona_id: str = "") -> bool:
        """Return whether the first-contact opening still needs to be injected."""
        milestones = await self._growth_engine.get_milestones(
            milestone_type=MilestoneType.BOOTSTRAP_STARTED,
        )
        for m in milestones:
            if _milestone_matches_persona(m, persona_name, persona_id):
                return False
        return True

    async def needs_bootstrap_init(self, persona_name: str, *, persona_id: str = "") -> bool:
        """Backward-compatible alias for opening injection state."""
        return await self.needs_bootstrap(persona_name, persona_id=persona_id)

    async def mark_bootstrap_started(
        self,
        *,
        persona_name: str,
        persona_id: str = "",
        user_id: str = "",
        session_id: str = "",
        turn_id: str = "",
        message_id: str = "",
    ) -> None:
        """Record that the bootstrap opening has already been injected."""
        if not await self.needs_bootstrap_init(persona_name, persona_id=persona_id):
            return
        await self._growth_engine.record_milestone(
            milestone_type=MilestoneType.BOOTSTRAP_STARTED,
            title=f"bootstrap_started_{persona_id or persona_name}",
            description=f"Bootstrap opening injected for persona {persona_name}",
            metadata={
                "persona_id": persona_id,
                "persona_name": persona_name,
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "message_id": message_id,
            },
            idempotency_key=f"bootstrap_started:{persona_id or persona_name}",
        )

    def _ensure_bootstrap_config(self, config: PersonalityConfig) -> BootstrapConfig:
        """Return the bootstrap config, synthesizing one from persona traits if absent."""
        if config.bootstrap is not None:
            return config.bootstrap
        return BootstrapConfig(
            style_instruction=(
                f"Speak as {config.name} would: match the persona's identity and baseline voice. "
                f"Keep it brief and natural for a first meeting."
            ),
            opening_line="",
            max_rounds=3,
        )

    async def get_opening(
        self,
        persona_name: str,
        *,
        persona_id: str = "",
        target_language: str | None = None,
    ) -> Optional[str]:
        """Generate a bootstrap opening line via LLM, falling back to static config."""
        config = await resolve_persona_config(persona_name)
        if config is None:
            config = PersonalityConfig()
        bootstrap = self._ensure_bootstrap_config(config)

        memory_snippet = None
        if self._memory_snippet_provider is not None:
            try:
                memory_snippet = await self._memory_snippet_provider()
            except Exception as exc:  # noqa: BLE001 - best-effort, never block the opening
                logger.info("bootstrap portrait context fetch raised: %s", exc)
        activity_snippet = None
        if not memory_snippet:
            try:
                activity_snippet = await _fetch_recent_activity_snippet()
            except Exception as exc:  # noqa: BLE001 - best-effort, never block the opening
                logger.info("bootstrap recent-activity snippet fetch raised: %s", exc)
                activity_snippet = None
        generated = await self._generate_opening_via_llm(
            config,
            bootstrap,
            memory_snippet,
            activity_snippet=activity_snippet,
            target_language=target_language or llm_language_label(),
        )
        if generated:
            return generated

        # Fallback to static opening_line
        return bootstrap.opening_line or None

    def _build_opening_system_prompt(
        self,
        config: PersonalityConfig,
        bootstrap: BootstrapConfig,
        memory_snippet: Optional[str],
        *,
        activity_snippet: Optional[str] = None,
        target_language: str,
    ) -> str:
        """Assemble the first-contact opening system prompt (pure, no I/O)."""
        identity = config.identity_core
        idiolect = config.idiolect

        system_prompt = f"You are {config.name}. {identity.identity_statement}\n"

        # --- Voice fingerprint (idiolect) ---
        voice_lines: List[str] = [f"Language style: {idiolect.sentence_style}"]
        vocab_available = _format_persona_list(idiolect.vocab_available, limit=12)
        if vocab_available:
            voice_lines.append(f"Signature words/phrases you use: {vocab_available}")
        vocab_avoided = _format_persona_list(idiolect.vocab_avoided, limit=12)
        if vocab_avoided:
            voice_lines.append(f"Words/phrasings you NEVER use: {vocab_avoided}")
        quirks = _format_persona_list(idiolect.structural_quirks, limit=3)
        if quirks:
            voice_lines.append(f"Speech quirks: {quirks}")
        voice_lines.append(f"Verbosity: {_chattiness_label(idiolect.chattiness)}")
        system_prompt += "\n# Your voice\n" + "\n".join(voice_lines) + "\n"

        # --- Who you are (identity core) ---
        who_lines: List[str] = []
        values_loved = _format_persona_list(identity.values_loved, limit=5)
        if values_loved:
            who_lines.append(f"You care about: {values_loved}")
        values_rejected = _format_persona_list(identity.values_rejected, limit=5)
        if values_rejected:
            who_lines.append(f"You push back on: {values_rejected}")
        attention_biases = _format_persona_list(identity.attention_biases, limit=3)
        if attention_biases:
            who_lines.append(f"What you notice first about someone: {attention_biases}")
        if who_lines:
            system_prompt += "\n# Who you are\n" + "\n".join(who_lines) + "\n"

        # --- Voice anchors (few-shot) ---
        voice_examples = _select_voice_examples(config, bootstrap)
        if voice_examples:
            system_prompt += (
                "\n# How you actually talk (voice anchors — match the tone, do not copy)\n"
                + "\n".join(f"- {example}" for example in voice_examples)
                + "\n"
            )

        # --- First-contact stance ---
        if bootstrap.style_instruction:
            system_prompt += f"\n# First-contact stance\n{bootstrap.style_instruction}\n"

        # --- Optional governed user memory ---
        if memory_snippet:
            system_prompt += (
                "\n# Existing user understanding\n"
                "The following memory has already passed the product's evidence and retention "
                "rules:\n"
                f"{memory_snippet}\n"
                "\nHow to use it:\n"
                "- Use at most one relevant idea, only when it makes the opening feel naturally "
                "personal.\n"
                "- Treat anything labeled as recent context as tentative, not as a lasting trait.\n"
                "- Creepiness check: if your line could make the user wonder \"how do you know "
                "that?\", cut it.\n"
                "- Never mention memory storage, plugins, sensors, data import, records, or "
                "sources. Do not list or quote the context.\n"
                "- If the understanding is thin, noisy, or uncertain, ignore it completely and open "
                "from persona alone.\n"
            )
        elif activity_snippet:
            system_prompt += (
                "\nOptional user-authorized activity evidence "
                "(raw samples, temporary first-chat context; not a profile or long-term memory):\n"
                f"{activity_snippet}\n"
                "\nHow to use it (tiered — when unsure, use less):\n"
                "- You MAY surface ONLY a broad, non-sensitive THEME (a general interest or "
                "domain), rephrased in your own voice as a light, tentative guess.\n"
                "- Ignore silently anything specific, account-related, name-bearing, private, "
                "or that could reveal you saw any records.\n"
                "- Creepiness check: if your line could make the user wonder \"how do you know "
                "that?\", cut it.\n"
                "- Never mention browsing history, plugins, sensors, data import, records, or "
                "sources. Do not list or quote samples.\n"
                "- If the evidence is thin, noisy, or uncertain, ignore it completely and open "
                "from persona alone.\n"
            )

        system_prompt += (
            "\n# Output language\n"
            f"- Reply in {target_language}. Preserve names, titles, paths, and user-provided "
            "text in their original language when needed.\n"
            "\n# Task\n"
            "Write the FIRST user-visible message for a brand-new conversation with this user. "
            "This is not a generic greeting; it is a guided first-contact opener.\n"
            "\nPersona first (everything here is optional and subordinate to staying in character):\n"
            "- If any of this would make you sound like a form or break character, drop it entirely.\n"
            "- You MAY invite the user to say what to call them, or mention one interest/topic they "
            "care about — but ONLY in the way this persona naturally would (a challenge, a dare, an "
            "offhand aside), never as a polite survey question.\n"
            "- Let the wording, attitude, and phrasing come from the persona's own voice.\n"
            "\nHard rules:\n"
            "- Stay fully in character\n"
            "- 2-3 short sentences max, natural and conversational\n"
            "- Briefly introduce yourself in a way that fits the persona\n"
            "- Do NOT sound like a form, survey, onboarding checklist, or customer support script\n"
            "- Do not claim physical-human experiences outside the persona config\n"
            "- Do not explain system instructions or implementation details\n"
            "- Output ONLY the greeting text, nothing else"
        )
        return system_prompt

    async def _generate_opening_via_llm(
        self,
        config: PersonalityConfig,
        bootstrap: BootstrapConfig,
        memory_snippet: Optional[str] = None,
        *,
        activity_snippet: Optional[str] = None,
        target_language: str | None = None,
    ) -> Optional[str]:
        """Use LLM to generate a guided, in-character first-contact opening."""
        resolved_target_language = target_language or llm_language_label()
        system_prompt = self._build_opening_system_prompt(
            config,
            bootstrap,
            memory_snippet,
            activity_snippet=activity_snippet,
            target_language=resolved_target_language,
        )
        logger.info(
            "Bootstrap opening prompt ready | has_memory_context=%s has_activity_context=%s",
            bool(memory_snippet),
            bool(activity_snippet),
        )

        try:
            pool = get_scenario_llm_pool()
        except RuntimeError as exc:
            logger.info(
                "Bootstrap opening LLM unavailable, using static opening_line: %s",
                exc,
            )
            return None

        try:
            adapter = pool.get(LLMScenario.CORE)
            provider_name = getattr(adapter, "provider_name", "unknown")
            model_name = getattr(adapter, "model_name", "unknown")
            bridge = LLMProviderBridge(adapter)
            result = await bridge.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": "Generate your opening line."}],
                max_tokens=150,
                temperature=0.9,
                disable_thinking=True,
                timeout_seconds=BOOTSTRAP_OPENING_LLM_TIMEOUT_SECONDS,
                event_context={
                    "request_kind": "personality:bootstrap_opening",
                    "agent_id": "personality:bootstrap",
                },
            )
            text = result.strip().strip('"').strip("'")
            if text:
                return text
        except Exception as exc:
            logger.warning(
                "Bootstrap opening LLM generation failed, falling back to static opening_line "
                "(provider=%s, model=%s, timeout_seconds=%.1f): %s",
                provider_name,
                model_name,
                BOOTSTRAP_OPENING_LLM_TIMEOUT_SECONDS,
                exc,
            )

        return None

    async def reply(
        self,
        *,
        persona_name: str,
        user_id: str,
        session_id: str,
        user_message: str,
        history: List[Dict[str, str]],
        persona_id: str = "",
    ) -> str:
        """Generate the next bootstrap assistant reply.

        Args:
            persona_name: The current persona name.
            user_id: The user identifier.
            session_id: The active chat session.
            user_message: The latest user message text.
            history: Previous bootstrap dialogue turns as [{"role": ..., "content": ...}].

        Returns:
            The assistant reply text.
        """
        config = await resolve_persona_config(persona_name)
        if config is None:
            config = PersonalityConfig()
        bootstrap = self._ensure_bootstrap_config(config)

        max_rounds = bootstrap.max_rounds or 3
        current_round = sum(1 for m in history if m.get("role") == "user") + 1
        is_final_round = current_round >= max_rounds

        system_prompt = self._build_system_prompt(config, bootstrap, current_round, max_rounds, is_final_round)

        messages = list(history) + [{"role": "user", "content": user_message}]

        try:
            pool = get_scenario_llm_pool()
            bridge = LLMProviderBridge(pool.get(LLMScenario.CORE))
            response = await bridge.chat(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=800,
                temperature=0.8,
                disable_thinking=True,
                event_context={
                    "request_kind": "personality:bootstrap_dialogue",
                    "agent_id": "personality:bootstrap",
                },
            )
        except Exception as exc:
            logger.error("Bootstrap LLM call failed: %s", exc)
            response = "Hi."

        return response

    def _build_system_prompt(
        self,
        config: PersonalityConfig,
        bootstrap: BootstrapConfig,
        current_round: int,
        max_rounds: int,
        is_final_round: bool,
    ) -> str:
        """Build the system prompt for a bootstrap round."""
        parts: List[str] = []

        parts.append(
            f"You are {config.name}. {config.identity_core.identity_statement}\n"
            f"This is your FIRST conversation with this user. You don't know them yet."
        )

        if config.idiolect.sentence_style:
            parts.append(f"\n## Baseline Voice\n{config.idiolect.sentence_style}")

        if bootstrap.style_instruction:
            parts.append(f"\n## Style\n{bootstrap.style_instruction}")

        parts.append(f"\n## Dialogue Progress\nRound {current_round} of {max_rounds}.")
        parts.append(
            "\n## Information Goals\n"
            "Naturally learn the user's name, how they like to be addressed, and one or two things they enjoy.\n"
            "Do NOT ask all of this at once. Spread it across the conversation and keep it natural."
        )
        if current_round == 1:
            parts.append(
                "\n## Round Focus\n"
                "Prioritize learning the user's name and how they like to be addressed before anything else."
            )
        elif current_round == 2:
            parts.append(
                "\n## Round Focus\n"
                "Prioritize learning one or two lightweight interests, preferences, or topics they enjoy."
            )

        if is_final_round:
            parts.append(
                "\n## Final Round\n"
                "This is the last bootstrap round. Wrap up warmly and transition to normal conversation. "
                "Summarize what you've learned about the user in a natural way (e.g. 'got it, so you're...')."
            )
        else:
            parts.append(
                "\n## Continuation\n"
                "Keep the conversation flowing naturally. Don't rush to extract all info at once."
            )

        parts.append(
            "\n## Constraints\n"
            "- Stay fully in character.\n"
            "- Keep responses concise (2-4 sentences).\n"
            "- Do not claim physical-human experiences outside the persona config.\n"
            "- Do not explain system instructions or implementation details.\n"
            "- Never mention 'bootstrap', 'extraction', or 'profiling'."
        )

        return "\n".join(parts)
