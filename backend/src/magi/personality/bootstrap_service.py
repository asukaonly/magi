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
BOOTSTRAP_IMPORT_SAMPLE_WINDOW_SECONDS = 24 * 60 * 60
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
        rows = await l1.query_events(
            source_filters=[source],
            cognition_eligible=True,
            limit=BOOTSTRAP_IMPORT_SAMPLE_QUERY_LIMIT,
            order_by="created_at_desc",
            include_embedding_fields=False,
        )
        samples: list[str] = []
        for row in rows or []:
            if _safe_float(row.get("created_at")) < cutoff:
                break
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
) -> Dict[str, Any]:
    """Return short-lived queue overrides right after the opening is injected."""
    normalized_persona_name = str(persona_name or "").strip()
    if not normalized_persona_name:
        return {}

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
    if (time.time() - float(getattr(matching, "timestamp", 0.0) or 0.0)) > BOOTSTRAP_L2_PRIORITY_WINDOW_SECONDS:
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
    ) -> None:
        self._growth_engine = growth_engine
        self._l2_store = l2_store

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

        try:
            activity_snippet = await _fetch_recent_activity_snippet()
        except Exception as exc:  # noqa: BLE001 - best-effort, never block the opening
            logger.info("bootstrap recent-activity snippet fetch raised: %s", exc)
            activity_snippet = None
        generated = await self._generate_opening_via_llm(
            config,
            bootstrap,
            activity_snippet,
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
        activity_snippet: Optional[str],
        *,
        target_language: str,
    ) -> str:
        """Assemble the first-contact opening system prompt (pure, no I/O)."""
        system_prompt = (
            f"You are {config.name}. {config.identity_core.identity_statement}\n\n"
            f"Language style: {config.idiolect.sentence_style}\n"
        )
        if bootstrap.style_instruction:
            system_prompt += f"Style: {bootstrap.style_instruction}\n"
        if activity_snippet:
            system_prompt += (
                "\nOptional user-authorized activity evidence "
                "(raw samples, temporary first-chat context; not a profile or long-term memory):\n"
                f"{activity_snippet}\n"
                "\nEvidence handling:\n"
                "- Treat this as optional evidence; you may use it only if it gives you a safe and natural opening.\n"
                "- If the evidence is thin, noisy, private, account-related, or uncertain, ignore it completely.\n"
                "- Never mention browsing history, plugins, sensors, data import, sources, or that you can see records.\n"
                "- Do not list or quote samples. If you use them, make only a tentative broad observation or gentle question.\n"
            )
        system_prompt += (
            "\nOutput language:\n"
            f"- Reply in {target_language}. Preserve names, titles, paths, and user-provided text in their original language when needed.\n"
            "\nGenerate the FIRST user-visible message for a brand-new conversation with this user. "
            "This is not a generic greeting; it is a guided first-contact opener.\n"
            "Goals:\n"
            "- Make it easy for the user to reply naturally\n"
            "- If it fits the persona and does not feel forced, ask how the user wants to be addressed\n"
            "- Optionally invite one lightweight preference, interest, hobby, or topic they care about\n"
            "- Let the wording, attitude, and phrasing come from the persona's own voice\n"
            "Requirements:\n"
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
        activity_snippet: Optional[str] = None,
        *,
        target_language: str | None = None,
    ) -> Optional[str]:
        """Use LLM to generate a guided, in-character first-contact opening."""
        resolved_target_language = target_language or llm_language_label()
        system_prompt = self._build_opening_system_prompt(
            config,
            bootstrap,
            activity_snippet,
            target_language=resolved_target_language,
        )
        logger.info(
            "Bootstrap opening system prompt | has_activity_context=%s prompt=%s",
            bool(activity_snippet),
            system_prompt,
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
