"""Wiring helpers: build a snippet fetcher around hybrid_retrieval service.

Also exposes :func:`build_portrait_service` which assembles a production
:class:`PortraitService` against live magi dependencies (LLM pool, persona
repository, retrieval service, chat history). The service is constructed
lazily on first /api/memory/portrait request to keep startup cheap.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Awaitable, Callable

from ..hybrid_retrieval import build_query
from .contracts import RawMemorySnippet, TopicResult


logger = logging.getLogger(__name__)


_MAX_SNIPPETS = 15


def _llm_debug_enabled() -> bool:
    """Toggle full prompt + response dumps via MAGI_PORTRAIT_LLM_DEBUG=1."""
    return os.environ.get("MAGI_PORTRAIT_LLM_DEBUG", "").strip() not in ("", "0", "false", "False")


def build_snippet_fetcher(
    *,
    retrieval_service_provider: Callable[[], Any | None],
) -> Callable[[str, TopicResult], Awaitable[list[RawMemorySnippet]]]:
    """Return an async fetcher that converts a TopicResult to RawMemorySnippet list."""

    async def fetch(user_id: str, topic_result: TopicResult) -> list[RawMemorySnippet]:
        if topic_result.is_empty():
            return []
        service = retrieval_service_provider()
        if service is None:
            return []
        query_text = " ".join(filter(None, [topic_result.topic, *topic_result.entities]))
        try:
            request = build_query(
                query=query_text,
                user_id=user_id,
                session_id=None,
                time_range={},
                query_mode="summary",
                limit=_MAX_SNIPPETS,
            )
            payload = await service.query(request)
        except Exception as exc:
            logger.debug("portrait retrieval failed: %s", exc)
            return []
        return _to_snippets(payload)

    return fetch


def _to_snippets(payload: Any) -> list[RawMemorySnippet]:
    out: list[RawMemorySnippet] = []
    for item in getattr(payload, "l3_reflections", None) or []:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("content") or "").strip()
        if not statement:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("summary_id") or item.get("id") or f"l3-{len(out)}"),
            kind="reflection",
            layer="L3",
            statement=statement,
            confidence=_safe_float(item.get("confidence")),
        ))
    for item in getattr(payload, "l2_assertions", None) or []:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or item.get("content") or "").strip()
        if not statement:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("assertion_id") or item.get("id") or f"l2a-{len(out)}"),
            kind="assertion",
            layer="L2",
            statement=statement,
            confidence=_safe_float(item.get("confidence")),
        ))
    for item in getattr(payload, "l2_relationships", None) or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "").strip()
        predicate = str(item.get("predicate") or "").strip()
        obj = str(item.get("object") or "").strip()
        statement = f"{subject} {predicate} {obj}".strip()
        if not statement:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("relationship_id") or item.get("id") or f"l2r-{len(out)}"),
            kind="relationship",
            layer="L2",
            statement=statement,
            confidence=_safe_float(item.get("confidence")),
        ))
    for item in getattr(payload, "l4_procedures", None) or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("procedure_id") or item.get("id") or f"l4-{len(out)}"),
            kind="procedure",
            layer="L4",
            statement=title,
            confidence=_safe_float(item.get("success_rate")),
        ))
    return out[:_MAX_SNIPPETS]


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


# ---------------------------------------------------------------------------
# Production service assembly
# ---------------------------------------------------------------------------


class _BridgeJsonAdapter:
    """Adapt :class:`LLMProviderBridge` to a simple ``complete_json`` interface.

    Carries a ``thinking_depth`` setting so callers can pick how hard the
    model reasons per scenario, and an explicit ``timeout_seconds`` that
    overrides the LLM provider config default (60s) — the portrait
    pipeline runs in a background task and tolerates longer LLM calls.

    Logging follows the same pattern as ``LLMIntentDecider``:

    - INFO on every call with metadata (model, elapsed_ms, thinking,
      prompt_len, response_len).
    - WARNING on failure with full system_prompt + user_prompt + exc_info.
    - Optional INFO dump of full prompts and response when
      ``MAGI_PORTRAIT_LLM_DEBUG=1`` is set.

    ``label`` distinguishes the two pipeline stages in the logs
    ("topic" or "lens").
    """

    def __init__(
        self,
        bridge: Any,
        *,
        label: str,
        thinking_depth: Any = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._bridge = bridge
        self._label = label
        self._thinking_depth = thinking_depth
        self._timeout_seconds = timeout_seconds

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        import time as _time

        kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "json_mode": True,
            "temperature": 0.2,
        }
        if self._thinking_depth is not None:
            kwargs["thinking_depth"] = self._thinking_depth
        if self._timeout_seconds is not None:
            kwargs["timeout_seconds"] = self._timeout_seconds

        model = getattr(getattr(self._bridge, "llm", None), "model_name", "unknown")
        base_url = str(getattr(getattr(self._bridge, "llm", None), "base_url", "unknown"))
        debug = _llm_debug_enabled()

        if debug:
            logger.info(
                "portrait %s LLM ▶ model=%s thinking=%s timeout=%s"
                "\n  system_prompt:\n%s"
                "\n  user_prompt:\n%s",
                self._label, model, self._thinking_depth, self._timeout_seconds,
                system_prompt, user_prompt,
            )

        t0 = _time.monotonic()
        try:
            text = await self._bridge.chat(**kwargs)
        except Exception:
            elapsed_ms = (_time.monotonic() - t0) * 1000
            logger.warning(
                "portrait %s LLM failed model=%s base_url=%s elapsed_ms=%.1f"
                " timeout=%s prompt_len=%d"
                "\n  system_prompt:\n%s"
                "\n  user_prompt:\n%s",
                self._label, model, base_url, elapsed_ms,
                self._timeout_seconds, len(user_prompt),
                system_prompt, user_prompt,
                exc_info=True,
            )
            return {}

        elapsed_ms = (_time.monotonic() - t0) * 1000
        response_text = text or ""
        logger.info(
            "portrait %s LLM completed model=%s base_url=%s elapsed_ms=%.1f"
            " timeout=%s prompt_len=%d response_len=%d",
            self._label, model, base_url, elapsed_ms,
            self._timeout_seconds, len(user_prompt), len(response_text),
        )
        if debug:
            logger.info("portrait %s LLM ◀ raw_response:\n%s", self._label, response_text)
        try:
            return json.loads(response_text)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "portrait %s LLM returned non-JSON (%s); raw=%r",
                self._label, exc, response_text,
            )
            return {}


def build_portrait_service():
    """Construct a :class:`PortraitService` wired to live magi services.

    Imports are local so this module can be imported without pulling in the
    full memory/persona stack at import time (e.g. during isolated tests).
    """
    from ...config.models import ThinkingDepth
    from ...llm import LLMProviderBridge, LLMScenario
    from ...llm.provider import get_scenario_llm_pool
    from ...personality.persona_repository import PersonaRepository
    from ..provider import get_hybrid_retrieval_service
    from .persona_lens_renderer import PersonaLensRenderer
    from .service import PortraitService
    from .topic_extractor import TopicExtractor

    repo = PersonaRepository()

    def _build_bridge(
        label: str,
        scenarios: tuple[LLMScenario, ...],
        thinking_depth,
        *,
        timeout_seconds: float,
    ):
        """Try scenarios in order; return a bridge adapter or None."""
        try:
            pool = get_scenario_llm_pool()
        except RuntimeError:
            return None
        if pool is None:
            return None
        for scenario in scenarios:
            try:
                adapter = pool.get(scenario)
            except Exception as exc:
                logger.debug("portrait bridge: scenario %s unavailable (%s)", scenario.value, exc)
                continue
            return _BridgeJsonAdapter(
                LLMProviderBridge(adapter),
                label=label,
                thinking_depth=thinking_depth,
                timeout_seconds=timeout_seconds,
            )
        return None

    # Topic extraction is essentially intent recognition: no reasoning needed.
    # 25s inner timeout < 30s outer wait_for in TopicExtractor.
    def topic_bridge_factory():
        return _build_bridge(
            "topic",
            (LLMScenario.CONTEXT_DECIDER, LLMScenario.CORE),
            ThinkingDepth.NONE,
            timeout_seconds=25.0,
        )

    # Persona-lens rendering needs to interpret raw memory through the
    # persona's voice — medium reasoning effort is appropriate.
    # 220s inner timeout < 240s outer wait_for in PersonaLensRenderer.
    def render_bridge_factory():
        return _build_bridge(
            "lens",
            (LLMScenario.MEMORY_SUMMARIZER, LLMScenario.CORE),
            ThinkingDepth.MEDIUM,
            timeout_seconds=220.0,
        )

    async def active_persona_resolver():
        try:
            return await repo.get_active_id()
        except Exception as exc:
            logger.debug("portrait active persona lookup failed: %s", exc)
            return None

    async def persona_loader(persona_id: str):
        if not persona_id:
            return None
        try:
            record = await repo.get(persona_id)
        except Exception as exc:
            logger.debug("portrait persona load failed (%s): %s", persona_id, exc)
            return None
        config = record.config
        config_dict = asdict(config) if is_dataclass(config) else dict(config or {})
        return {
            "persona_id": record.persona_id,
            "name": record.name,
            "config": config_dict,
        }

    async def message_loader(user_id: str, session_id: str) -> list[dict[str, str]]:
        try:
            from ...api.routers.memory.dependencies import get_chat_read_service
            svc = get_chat_read_service()
            history = await svc.aget_display_history(user_id, session_id)
        except Exception as exc:
            logger.debug("portrait message loader failed: %s", exc)
            return []
        return [_message_to_dict(msg) for msg in history if msg is not None]

    snippet_fetcher = build_snippet_fetcher(
        retrieval_service_provider=lambda: _safe_get_retrieval_service(get_hybrid_retrieval_service),
    )

    return PortraitService(
        topic_extractor=TopicExtractor(bridge_factory=topic_bridge_factory),
        renderer=PersonaLensRenderer(bridge_factory=render_bridge_factory),
        snippet_fetcher=snippet_fetcher,
        persona_loader=persona_loader,
        message_loader=message_loader,
        active_persona_resolver=active_persona_resolver,
    )


def _safe_get_retrieval_service(getter: Callable[[], Any]) -> Any | None:
    try:
        return getter()
    except Exception as exc:
        logger.debug("portrait retrieval service unavailable: %s", exc)
        return None


def _message_to_dict(msg: Any) -> dict[str, str]:
    if isinstance(msg, dict):
        return {"role": str(msg.get("role") or "user"),
                "content": str(msg.get("content") or "")}
    # Display history messages typically have to_dict() and role/content attrs.
    if hasattr(msg, "to_dict"):
        try:
            data = msg.to_dict()
        except Exception:
            data = {}
        if isinstance(data, dict):
            return {"role": str(data.get("role") or "user"),
                    "content": str(data.get("content") or "")}
    return {
        "role": str(getattr(msg, "role", None) or "user"),
        "content": str(getattr(msg, "content", None) or ""),
    }
