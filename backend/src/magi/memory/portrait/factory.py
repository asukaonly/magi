"""Wiring helpers: build a snippet fetcher around hybrid_retrieval service.

Also exposes :func:`build_portrait_service` which assembles a production
:class:`PortraitService` against live magi dependencies (LLM pool, persona
repository, retrieval service, chat history). The service is constructed
lazily on first /api/memory/portrait request to keep startup cheap.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Awaitable, Callable

from ..hybrid_retrieval import build_query
from .contracts import RawMemorySnippet, TopicResult


logger = logging.getLogger(__name__)


_MAX_SNIPPETS = 15


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
    """Adapt :class:`LLMProviderBridge` to a simple ``complete_json`` interface."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        text = await self._bridge.chat(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            json_mode=True,
            temperature=0.2,
        )
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}


def build_portrait_service():
    """Construct a :class:`PortraitService` wired to live magi services.

    Imports are local so this module can be imported without pulling in the
    full memory/persona stack at import time (e.g. during isolated tests).
    """
    from ...llm import LLMProviderBridge, LLMScenario
    from ...llm.provider import get_scenario_llm_pool
    from ...personality.persona_repository import PersonaRepository
    from ..provider import get_hybrid_retrieval_service
    from .persona_lens_renderer import PersonaLensRenderer
    from .service import PortraitService
    from .topic_extractor import TopicExtractor

    repo = PersonaRepository()

    def bridge_factory():
        try:
            pool = get_scenario_llm_pool()
        except RuntimeError:
            return None
        if pool is None:
            return None
        try:
            adapter = pool.get(LLMScenario.MEMORY_SUMMARIZER)
        except Exception as exc:
            logger.debug("portrait bridge unavailable: %s", exc)
            return None
        return _BridgeJsonAdapter(LLMProviderBridge(adapter))

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
        topic_extractor=TopicExtractor(bridge_factory=bridge_factory),
        renderer=PersonaLensRenderer(bridge_factory=bridge_factory),
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
