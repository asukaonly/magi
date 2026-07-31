"""Production assembly for the chat portrait rail."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from ...utils.diagnostic_logging import full_content_logging_enabled
from ...memory.portrait.snippet_fetcher import build_snippet_fetcher

logger = logging.getLogger(__name__)


def _llm_debug_enabled() -> bool:
    """Toggle full prompt + response dumps via MAGI_PORTRAIT_LLM_DEBUG=1."""
    return os.environ.get("MAGI_PORTRAIT_LLM_DEBUG", "").strip() not in ("", "0", "false", "False")


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

        kwargs = self._chat_kwargs(system_prompt, user_prompt)
        model, base_url = self._bridge_metadata()
        if full_content_logging_enabled() and _llm_debug_enabled():
            self._log_llm_request(system_prompt, user_prompt, model)

        t0 = _time.monotonic()
        try:
            text = await self._bridge.chat(**kwargs)
        except Exception:
            elapsed_ms = (_time.monotonic() - t0) * 1000
            self._log_llm_failure(
                system_prompt,
                user_prompt,
                model,
                base_url,
                elapsed_ms,
            )
            return {}

        elapsed_ms = (_time.monotonic() - t0) * 1000
        response_text = text or ""
        self._log_llm_success(user_prompt, response_text, model, base_url, elapsed_ms)
        if full_content_logging_enabled() and _llm_debug_enabled():
            logger.info("portrait %s LLM ◀ raw_response:\n%s", self._label, response_text)
        return self._parse_json_response(response_text)

    def _chat_kwargs(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
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
        return kwargs

    def _bridge_metadata(self) -> tuple[str, str]:
        llm = getattr(self._bridge, "llm", None)
        model = str(getattr(llm, "model_name", "unknown"))
        base_url = str(getattr(llm, "base_url", "unknown"))
        return model, base_url

    def _log_llm_request(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> None:
        logger.info(
            "portrait %s LLM ▶ model=%s thinking=%s timeout=%s"
            "\n  system_prompt:\n%s"
            "\n  user_prompt:\n%s",
            self._label,
            model,
            self._thinking_depth,
            self._timeout_seconds,
            system_prompt,
            user_prompt,
        )

    def _log_llm_failure(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        base_url: str,
        elapsed_ms: float,
    ) -> None:
        if full_content_logging_enabled():
            logger.warning(
                "portrait %s LLM failed model=%s base_url=%s elapsed_ms=%.1f"
                " timeout=%s prompt_len=%d"
                "\n  system_prompt:\n%s"
                "\n  user_prompt:\n%s",
                self._label,
                model,
                base_url,
                elapsed_ms,
                self._timeout_seconds,
                len(user_prompt),
                system_prompt,
                user_prompt,
                exc_info=True,
            )
            return
        logger.warning(
            "portrait %s LLM failed model=%s base_url=%s elapsed_ms=%.1f"
            " timeout=%s system_prompt_len=%d user_prompt_len=%d",
            self._label,
            model,
            base_url,
            elapsed_ms,
            self._timeout_seconds,
            len(system_prompt),
            len(user_prompt),
            exc_info=True,
        )

    def _log_llm_success(
        self,
        user_prompt: str,
        response_text: str,
        model: str,
        base_url: str,
        elapsed_ms: float,
    ) -> None:
        logger.info(
            "portrait %s LLM completed model=%s base_url=%s elapsed_ms=%.1f"
            " timeout=%s prompt_len=%d response_len=%d",
            self._label,
            model,
            base_url,
            elapsed_ms,
            self._timeout_seconds,
            len(user_prompt),
            len(response_text),
        )

    def _parse_json_response(self, response_text: str) -> dict:
        try:
            return json.loads(response_text)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            if full_content_logging_enabled():
                logger.warning(
                    "portrait %s LLM returned non-JSON (%s); raw=%r",
                    self._label,
                    exc,
                    response_text,
                )
            else:
                logger.warning(
                    "portrait %s LLM returned non-JSON (%s); response_len=%d",
                    self._label,
                    type(exc).__name__,
                    len(response_text),
                )
            return {}


def build_chat_portrait_service(chat_read_service_factory=None):
    """Construct a :class:`PortraitService` wired to live magi services.

    Imports are local so this module can be imported without pulling in the
    full memory/persona stack at import time (e.g. during isolated tests).

    ``chat_read_service_factory`` is a zero-arg callable returning the chat
    read service, injected by the composition root (the api portrait route).
    Injected rather than imported here so this chat rail assembly stays testable
    and does not depend directly on the API router. When ``None`` (e.g. isolated
    tests that never exercise ``message_loader``) the loader yields no history.
    """
    from ...config.models import ThinkingDepth
    from ...llm import LLMScenario
    from ...personality.persona_repository import PersonaRepository
    from .persona_lens_renderer import PersonaLensRenderer
    from .service import PortraitService
    from .topic_extractor import TopicExtractor

    repo = PersonaRepository()

    return PortraitService(
        topic_extractor=TopicExtractor(
            bridge_factory=_build_topic_bridge_factory(LLMScenario, ThinkingDepth)
        ),
        renderer=PersonaLensRenderer(
            bridge_factory=_build_render_bridge_factory(LLMScenario, ThinkingDepth)
        ),
        snippet_fetcher=_build_portrait_snippet_fetcher(),
        persona_loader=_build_persona_loader(repo),
        message_loader=_build_message_loader(chat_read_service_factory),
        active_persona_resolver=_build_active_persona_resolver(repo),
        cache=_build_portrait_cache(),
    )


def _build_portrait_cache():
    from ...utils.runtime import get_runtime_paths
    from .cache import PortraitCache

    # Disk persistence so the rail survives a backend restart instead of
    # flashing back to the cold-start placeholder for the first ~25s.
    portrait_cache_path = get_runtime_paths().cache_dir / "portrait" / "cache.json"
    return PortraitCache(persistence_path=portrait_cache_path)


def _build_topic_bridge_factory(llm_scenario_enum: Any, thinking_depth_enum: Any):
    # Topic extraction is essentially intent recognition: no reasoning needed.
    # 25s inner timeout < 30s outer wait_for in TopicExtractor.
    def topic_bridge_factory():
        return _build_bridge(
            "topic",
            (llm_scenario_enum.CONTEXT_DECIDER, llm_scenario_enum.CORE),
            thinking_depth_enum.NONE,
            timeout_seconds=25.0,
        )

    return topic_bridge_factory


def _build_render_bridge_factory(llm_scenario_enum: Any, thinking_depth_enum: Any):
    # Persona-lens rendering needs to interpret raw memory through the
    # persona's voice — medium reasoning effort is appropriate.
    # 220s inner timeout < 240s outer wait_for in PersonaLensRenderer.
    def render_bridge_factory():
        return _build_bridge(
            "lens",
            (llm_scenario_enum.MEMORY_SUMMARIZER, llm_scenario_enum.CORE),
            thinking_depth_enum.MEDIUM,
            timeout_seconds=220.0,
        )

    return render_bridge_factory


def _build_bridge(
    label: str,
    scenarios: tuple[Any, ...],
    thinking_depth: Any,
    *,
    timeout_seconds: float,
):
    from ...llm import LLMProviderBridge
    from ...llm.provider import get_scenario_llm_pool

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


def _build_active_persona_resolver(repo: Any):
    async def active_persona_resolver():
        try:
            return await repo.get_active_id()
        except Exception as exc:
            logger.debug("portrait active persona lookup failed: %s", exc)
            return None

    return active_persona_resolver


def _build_persona_loader(repo: Any):
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

    return persona_loader


def _build_message_loader(chat_read_service_factory):
    async def message_loader(user_id: str, session_id: str) -> list[dict[str, str]]:
        if chat_read_service_factory is None:
            return []
        try:
            svc = chat_read_service_factory()
            history = await svc.aget_display_history(user_id, session_id)
        except Exception as exc:
            logger.debug("portrait message loader failed: %s", exc)
            return []
        return [_message_to_dict(msg) for msg in history if msg is not None]

    return message_loader


def _build_portrait_snippet_fetcher():
    from ...memory.provider import get_hybrid_retrieval_service

    return build_snippet_fetcher(
        retrieval_service_provider=lambda: _safe_get_retrieval_service(
            get_hybrid_retrieval_service
        ),
    )


def _safe_get_retrieval_service(getter: Callable[[], Any]) -> Any | None:
    try:
        return getter()
    except Exception as exc:
        logger.debug("portrait retrieval service unavailable: %s", exc)
        return None


def _message_to_dict(msg: Any) -> dict[str, str]:
    if isinstance(msg, dict):
        return {"role": str(msg.get("role") or "user"), "content": str(msg.get("content") or "")}
    # Display history messages typically have to_dict() and role/content attrs.
    if hasattr(msg, "to_dict"):
        try:
            data = msg.to_dict()
        except Exception:
            data = {}
        if isinstance(data, dict):
            return {
                "role": str(data.get("role") or "user"),
                "content": str(data.get("content") or ""),
            }
    return {
        "role": str(getattr(msg, "role", None) or "user"),
        "content": str(getattr(msg, "content", None) or ""),
    }
