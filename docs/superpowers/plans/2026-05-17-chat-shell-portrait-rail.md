# Chat Shell — Persona Portrait Rail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a right-side rail in the chat shell that shows the active persona's "view" of the user — observations about who they are, rendered through the persona's voice, filtered by current conversation topic.

**Architecture:** New backend endpoint `GET /api/memory/portrait` that runs two LLM calls (topic extraction → persona-lens rendering) over filtered L2/L3/L4 memory, with a 5-min in-memory cache keyed by `(session_id, topic_hash, persona_id)`. New frontend rail column composes a hook + card components, behind a responsive breakpoint that turns it into a floater under 1280px.

**Tech Stack:** Python (FastAPI, asyncio, dataclasses, pytest), TypeScript (React, react-i18next, Tailwind, vitest). Reuses existing `hybrid_retrieval_service`, `LLMScenario.MEMORY_SUMMARIZER`, `personasApi`, `ChatRoleAvatar`.

**Source spec:** `docs/superpowers/specs/2026-05-17-chat-shell-portrait-rail-design.md`

---

## File Structure

### Backend (new)

| File | Responsibility |
|------|----------------|
| `backend/src/magi/memory/portrait/__init__.py` | package init, re-export public API |
| `backend/src/magi/memory/portrait/contracts.py` | dataclasses: `PortraitObservation`, `PortraitPayload`, `TopicResult`, `RawMemorySnippet` |
| `backend/src/magi/memory/portrait/cache.py` | `PortraitCache` — in-memory LRU + 300s TTL, key = (session_id, topic_hash, persona_id) |
| `backend/src/magi/memory/portrait/topic_extractor.py` | `TopicExtractor.extract(messages) -> TopicResult` — LLM call returning `{topic, entities}` |
| `backend/src/magi/memory/portrait/persona_lens_renderer.py` | `PersonaLensRenderer.render(persona_config, raw_snippets, recent_message) -> list[PortraitObservation]` — LLM call rendering observations in persona voice |
| `backend/src/magi/memory/portrait/service.py` | `PortraitService.get_portrait(user_id, session_id, force) -> PortraitPayload` — orchestrates the 5-step pipeline |
| `backend/src/magi/api/routers/memory/portrait_routes.py` | FastAPI route `GET /portrait` (mounted under `/api/memory`) |

### Backend (modified)

| File | Change |
|------|--------|
| `backend/src/magi/api/routers/memory/router.py` | include `portrait_routes.router` |
| `backend/src/magi/api/routes.py:16` | add `"GET"` to `_PUBLIC_ROUTE_METHODS["memory"]` if needed (verify, may already be OK since `/portrait` is GET and memory router already allows GET) |
| `backend/src/magi/personality/seed/` builtin persona JSONs | add `interim_lines.portrait_cold_start: [str]` to each |

### Frontend (new)

| File | Responsibility |
|------|----------------|
| `frontend/src/api/modules/memoryPortrait.ts` | API client wrapper: `getPortrait(sessionId, force)` |
| `frontend/src/hooks/useMemoryPortrait.ts` | fetch + refresh policy hook; returns `{payload, isLoading, error, refresh}` |
| `frontend/src/components/chat/portrait/PortraitCard.tsx` | one observation card (kind icon + text + basis summary) |
| `frontend/src/components/chat/portrait/PortraitColdStart.tsx` | cold-start empty state component |
| `frontend/src/components/chat/portrait/PortraitFloater.tsx` | popover wrapper for < 1280px |
| `frontend/src/components/chat/MemoryPortraitRail.tsx` | container: composes hook + maps observations to cards (or ColdStart) |

### Frontend (modified)

| File | Change |
|------|--------|
| `frontend/src/components/layout/MainLayout.tsx:93` | grid `grid-cols-[auto_minmax(0,1fr)_auto]`; render `<MemoryPortraitRail />` in 3rd col |
| `frontend/src/stores/chat-shell.ts` | add `portraitRailOpen: boolean`, `viewportIsNarrow: boolean`, `setPortraitRailOpen()`, `setViewportIsNarrow()` |
| `frontend/src/components/layout/Sidebar.tsx` | add rail toggle button in activity bar bottom group (above settings) |
| `frontend/src/i18n/locales/{zh-CN,en}/app.json` | add `chat.portrait.*` keys |

---

## Task 1: Backend portrait contracts

**Files:**
- Create: `backend/src/magi/memory/portrait/__init__.py`
- Create: `backend/src/magi/memory/portrait/contracts.py`
- Test: `backend/tests/memory/portrait/__init__.py` (empty)
- Test: `backend/tests/memory/portrait/test_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/memory/portrait/test_contracts.py
from magi.memory.portrait.contracts import (
    PortraitObservation,
    PortraitPayload,
    TopicResult,
    RawMemorySnippet,
)


def test_portrait_observation_to_dict_roundtrip():
    obs = PortraitObservation(
        kind="reflection",
        text="你最近老聊'落寞英雄'",
        basis_count=5,
        basis_summary="5 条反思 · 上周以来",
        basis_refs=["mem_a", "mem_b"],
    )
    data = obs.to_dict()
    assert data["kind"] == "reflection"
    assert data["text"].startswith("你最近")
    assert data["basis_count"] == 5
    assert data["basis_refs"] == ["mem_a", "mem_b"]


def test_portrait_payload_cold_start_shape():
    payload = PortraitPayload(
        session_id="s1",
        persona_id="p1",
        topic="",
        generated_at=1700000000,
        observations=[],
        is_cold_start=True,
        cold_start_line="七号还在认识你",
    )
    data = payload.to_dict()
    assert data["is_cold_start"] is True
    assert data["cold_start_line"] == "七号还在认识你"
    assert data["observations"] == []


def test_topic_result_default_empty():
    result = TopicResult(topic="", entities=[])
    assert result.is_empty() is True
    assert TopicResult(topic="罗永浩", entities=[]).is_empty() is False


def test_raw_memory_snippet_kind_required():
    s = RawMemorySnippet(
        id="mem_1",
        kind="reflection",
        layer="L3",
        statement="对失败者有同理心",
        confidence=0.7,
    )
    assert s.kind == "reflection"
    assert s.layer == "L3"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/memory/portrait/test_contracts.py -v
```

Expected: `ModuleNotFoundError: No module named 'magi.memory.portrait'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/magi/memory/portrait/__init__.py
from .contracts import (
    PortraitObservation,
    PortraitPayload,
    TopicResult,
    RawMemorySnippet,
)

__all__ = [
    "PortraitObservation",
    "PortraitPayload",
    "TopicResult",
    "RawMemorySnippet",
]
```

```python
# backend/src/magi/memory/portrait/contracts.py
"""Dataclass contracts for the persona portrait rail."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ObservationKind = Literal["reflection", "assertion", "relationship", "procedure"]
MemoryLayer = Literal["L2", "L3", "L4"]


@dataclass
class PortraitObservation:
    """One persona-voiced observation derived from raw memory."""

    kind: ObservationKind
    text: str
    basis_count: int
    basis_summary: str
    basis_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "basis_count": self.basis_count,
            "basis_summary": self.basis_summary,
            "basis_refs": list(self.basis_refs),
        }


@dataclass
class PortraitPayload:
    """Response payload returned by /api/memory/portrait."""

    session_id: str
    persona_id: str
    topic: str
    generated_at: int  # unix seconds
    observations: list[PortraitObservation] = field(default_factory=list)
    is_cold_start: bool = False
    cold_start_line: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "topic": self.topic,
            "generated_at": self.generated_at,
            "observations": [o.to_dict() for o in self.observations],
            "is_cold_start": self.is_cold_start,
            "cold_start_line": self.cold_start_line,
        }


@dataclass
class TopicResult:
    """Output of TopicExtractor."""

    topic: str
    entities: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.topic.strip() and not self.entities


@dataclass
class RawMemorySnippet:
    """A raw L2/L3/L4 memory fragment passed to the persona-lens renderer."""

    id: str
    kind: ObservationKind
    layer: MemoryLayer
    statement: str
    confidence: float | None = None
    occurred_at: float | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/memory/portrait/test_contracts.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/portrait/__init__.py \
        backend/src/magi/memory/portrait/contracts.py \
        backend/tests/memory/portrait/__init__.py \
        backend/tests/memory/portrait/test_contracts.py
git commit -m "feat(memory/portrait): contracts for portrait rail payloads"
```

---

## Task 2: Backend portrait cache

**Files:**
- Create: `backend/src/magi/memory/portrait/cache.py`
- Test: `backend/tests/memory/portrait/test_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/memory/portrait/test_cache.py
import time

import pytest

from magi.memory.portrait.cache import PortraitCache
from magi.memory.portrait.contracts import PortraitPayload


def _payload(session: str, persona: str) -> PortraitPayload:
    return PortraitPayload(
        session_id=session,
        persona_id=persona,
        topic="t",
        generated_at=int(time.time()),
    )


def test_set_then_get_returns_payload():
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    key = ("s1", "topic_hash", "p1")
    payload = _payload("s1", "p1")
    cache.set(key, payload)
    assert cache.get(key) is payload


def test_get_expired_entry_returns_none(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr("magi.memory.portrait.cache.time.monotonic", lambda: now[0])
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    key = ("s1", "h", "p1")
    cache.set(key, _payload("s1", "p1"))
    now[0] += 301
    assert cache.get(key) is None


def test_invalidate_by_persona():
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    cache.set(("s1", "h", "p1"), _payload("s1", "p1"))
    cache.set(("s1", "h", "p2"), _payload("s1", "p2"))
    cache.invalidate_persona("p1")
    assert cache.get(("s1", "h", "p1")) is None
    assert cache.get(("s1", "h", "p2")) is not None


def test_lru_eviction_when_over_capacity():
    cache = PortraitCache(ttl_seconds=300, max_entries=2)
    cache.set(("s1", "h", "p1"), _payload("s1", "p1"))
    cache.set(("s2", "h", "p1"), _payload("s2", "p1"))
    # Access s1 → makes s2 the LRU
    cache.get(("s1", "h", "p1"))
    cache.set(("s3", "h", "p1"), _payload("s3", "p1"))
    assert cache.get(("s2", "h", "p1")) is None
    assert cache.get(("s1", "h", "p1")) is not None
    assert cache.get(("s3", "h", "p1")) is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/memory/portrait/test_cache.py -v
```

Expected: `ModuleNotFoundError: No module named 'magi.memory.portrait.cache'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/magi/memory/portrait/cache.py
"""In-memory LRU cache for persona portraits with TTL eviction.

Keyed by (session_id, topic_hash, persona_id). Topic hash is opaque to this
module — callers compute it (typically sha1 of normalized topic + entities).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import RLock
from typing import Tuple

from .contracts import PortraitPayload


CacheKey = Tuple[str, str, str]


class PortraitCache:
    """Thread-safe LRU + TTL cache for portraits."""

    def __init__(self, *, ttl_seconds: float = 300.0, max_entries: int = 256) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._data: OrderedDict[CacheKey, tuple[float, PortraitPayload]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: CacheKey) -> PortraitPayload | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, payload = entry
            if time.monotonic() - ts > self._ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return payload

    def set(self, key: CacheKey, payload: PortraitPayload) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), payload)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def invalidate_persona(self, persona_id: str) -> None:
        with self._lock:
            stale = [k for k in self._data if k[2] == persona_id]
            for k in stale:
                self._data.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/memory/portrait/test_cache.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/portrait/cache.py backend/tests/memory/portrait/test_cache.py
git commit -m "feat(memory/portrait): in-memory LRU+TTL cache"
```

---

## Task 3: Backend TopicExtractor service

**Files:**
- Create: `backend/src/magi/memory/portrait/topic_extractor.py`
- Test: `backend/tests/memory/portrait/test_topic_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/memory/portrait/test_topic_extractor.py
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.portrait.contracts import TopicResult
from magi.memory.portrait.topic_extractor import TopicExtractor


@pytest.mark.asyncio
async def test_extract_returns_topic_and_entities():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(return_value={
        "topic": "罗永浩",
        "entities": ["罗永浩", "锤子手机"],
    })
    extractor = TopicExtractor(bridge_factory=lambda: mock_bridge)
    result = await extractor.extract([
        {"role": "user", "content": "你怎么看罗永浩"},
        {"role": "assistant", "content": "老罗是个把失败做成IP的人"},
    ])
    assert isinstance(result, TopicResult)
    assert result.topic == "罗永浩"
    assert "锤子手机" in result.entities


@pytest.mark.asyncio
async def test_extract_empty_messages_returns_empty_result():
    extractor = TopicExtractor(bridge_factory=lambda: AsyncMock())
    result = await extractor.extract([])
    assert result.is_empty()


@pytest.mark.asyncio
async def test_extract_llm_failure_returns_empty():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(side_effect=RuntimeError("llm down"))
    extractor = TopicExtractor(bridge_factory=lambda: mock_bridge)
    result = await extractor.extract([{"role": "user", "content": "hi"}])
    assert result.is_empty()


@pytest.mark.asyncio
async def test_extract_no_bridge_returns_empty():
    extractor = TopicExtractor(bridge_factory=lambda: None)
    result = await extractor.extract([{"role": "user", "content": "hi"}])
    assert result.is_empty()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/memory/portrait/test_topic_extractor.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/magi/memory/portrait/topic_extractor.py
"""Topic and entity extraction for the persona portrait rail.

Given the last N chat messages, produce a {topic, entities} tuple. The output
feeds the cross-layer retrieval that gathers L2/L3/L4 snippets relevant to
the current conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from .contracts import TopicResult


logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You extract the single most salient conversation topic and the named "
    "entities it revolves around. Output strict JSON: "
    '{"topic": "<short noun phrase>", "entities": ["<entity>", ...]}. '
    "If the messages have no coherent topic yet, return "
    '{"topic": "", "entities": []}.'
)


class TopicExtractor:
    """Extract conversation topic via an LLM call."""

    def __init__(
        self,
        *,
        bridge_factory: Callable[[], Any | None],
        timeout_seconds: float = 4.0,
    ) -> None:
        self._bridge_factory = bridge_factory
        self._timeout = float(timeout_seconds)

    async def extract(self, messages: list[dict[str, str]]) -> TopicResult:
        if not messages:
            return TopicResult(topic="", entities=[])
        bridge = self._bridge_factory()
        if bridge is None:
            return TopicResult(topic="", entities=[])
        prompt = self._format_messages(messages)
        try:
            payload = await asyncio.wait_for(
                bridge.complete_json(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=prompt,
                ),
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.debug("portrait topic extraction failed: %s", exc)
            return TopicResult(topic="", entities=[])
        return self._parse(payload)

    def _format_messages(self, messages: list[dict[str, str]]) -> str:
        lines = []
        for msg in messages[-10:]:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _parse(self, payload: Any) -> TopicResult:
        if not isinstance(payload, dict):
            return TopicResult(topic="", entities=[])
        topic = str(payload.get("topic") or "").strip()
        entities_raw = payload.get("entities") or []
        if not isinstance(entities_raw, list):
            return TopicResult(topic=topic, entities=[])
        entities = [str(e).strip() for e in entities_raw if str(e).strip()]
        return TopicResult(topic=topic, entities=entities)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/memory/portrait/test_topic_extractor.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/portrait/topic_extractor.py backend/tests/memory/portrait/test_topic_extractor.py
git commit -m "feat(memory/portrait): topic+entity extractor with LLM fallback"
```

---

## Task 4: Backend PersonaLensRenderer

**Files:**
- Create: `backend/src/magi/memory/portrait/persona_lens_renderer.py`
- Test: `backend/tests/memory/portrait/test_persona_lens_renderer.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/memory/portrait/test_persona_lens_renderer.py
from unittest.mock import AsyncMock

import pytest

from magi.memory.portrait.contracts import PortraitObservation, RawMemorySnippet
from magi.memory.portrait.persona_lens_renderer import PersonaLensRenderer


_PERSONA_CONFIG = {
    "name": "七号",
    "identity_core": {
        "identity_statement": "陪在 asuka 身边的猫一样的搭档",
        "values_loved": ["真诚"],
        "values_rejected": ["假大空"],
        "attention_biases": [],
    },
    "idiolect": {
        "sentence_style": "短句，偶尔毒舌但有温度",
        "vocab_available": ["子涵", "你"],
        "vocab_avoided": ["用户", "亲爱的"],
        "structural_quirks": [],
    },
}


_SNIPPETS = [
    RawMemorySnippet(id="mem_a", kind="reflection", layer="L3",
                     statement="对失败者有同理心", confidence=0.8),
    RawMemorySnippet(id="mem_b", kind="assertion", layer="L2",
                     statement="不喜欢直播带货", confidence=0.9),
]


@pytest.mark.asyncio
async def test_render_returns_observations_from_llm_json():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(return_value={
        "observations": [
            {
                "kind": "reflection",
                "text": "你又开始想那些没做成的事了？",
                "basis_count": 1,
                "basis_summary": "1 条反思",
                "basis_refs": ["mem_a"],
            },
        ],
    })
    renderer = PersonaLensRenderer(bridge_factory=lambda: mock_bridge)
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=_SNIPPETS,
        recent_message_excerpt="你怎么看罗永浩",
        topic="罗永浩",
    )
    assert len(observations) == 1
    assert isinstance(observations[0], PortraitObservation)
    assert observations[0].kind == "reflection"
    assert "你" in observations[0].text


@pytest.mark.asyncio
async def test_render_no_snippets_returns_empty():
    renderer = PersonaLensRenderer(bridge_factory=lambda: AsyncMock())
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=[],
        recent_message_excerpt="hi",
        topic="",
    )
    assert observations == []


@pytest.mark.asyncio
async def test_render_llm_failure_returns_empty():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(side_effect=RuntimeError("boom"))
    renderer = PersonaLensRenderer(bridge_factory=lambda: mock_bridge)
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=_SNIPPETS,
        recent_message_excerpt="hi",
        topic="t",
    )
    assert observations == []


@pytest.mark.asyncio
async def test_render_drops_invalid_kind():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(return_value={
        "observations": [
            {"kind": "garbage", "text": "x", "basis_count": 0,
             "basis_summary": "", "basis_refs": []},
            {"kind": "assertion", "text": "你不喜欢直播", "basis_count": 1,
             "basis_summary": "1 条事实", "basis_refs": ["mem_b"]},
        ],
    })
    renderer = PersonaLensRenderer(bridge_factory=lambda: mock_bridge)
    observations = await renderer.render(
        persona_config=_PERSONA_CONFIG,
        snippets=_SNIPPETS,
        recent_message_excerpt="hi",
        topic="t",
    )
    assert len(observations) == 1
    assert observations[0].kind == "assertion"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/memory/portrait/test_persona_lens_renderer.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/magi/memory/portrait/persona_lens_renderer.py
"""Render raw L2/L3/L4 snippets into persona-voiced observations."""

from __future__ import annotations

import asyncio
import json
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
        timeout_seconds: float = 8.0,
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/memory/portrait/test_persona_lens_renderer.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/portrait/persona_lens_renderer.py backend/tests/memory/portrait/test_persona_lens_renderer.py
git commit -m "feat(memory/portrait): persona-lens renderer for observations"
```

---

## Task 5: Backend PortraitService orchestrator

**Files:**
- Create: `backend/src/magi/memory/portrait/service.py`
- Test: `backend/tests/memory/portrait/test_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/memory/portrait/test_service.py
import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.portrait.contracts import (
    PortraitObservation,
    PortraitPayload,
    RawMemorySnippet,
    TopicResult,
)
from magi.memory.portrait.service import PortraitService


def _persona_detail(name="七号", cold_lines=None):
    return {
        "persona_id": "p1",
        "name": name,
        "config": {
            "name": name,
            "identity_core": {"identity_statement": "猫一样的搭档"},
            "idiolect": {"sentence_style": "短句"},
            "interim_lines": {
                "portrait_cold_start": cold_lines or [],
            },
        },
    }


@pytest.fixture
def deps():
    return {
        "topic_extractor": MagicMock(),
        "renderer": MagicMock(),
        "snippet_fetcher": AsyncMock(),
        "persona_loader": MagicMock(),
        "message_loader": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_cold_start_when_no_snippets(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail(
        cold_lines=["七号还在认识你"],
    )
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=["e"]))
    deps["snippet_fetcher"].return_value = []
    deps["renderer"].render = AsyncMock(return_value=[])

    service = PortraitService(**deps, active_persona_resolver=lambda: "p1",
                              random_seed=42)
    payload = await service.get_portrait(user_id="u1", session_id="s1")

    assert payload.is_cold_start is True
    assert payload.cold_start_line == "七号还在认识你"
    assert payload.observations == []
    assert payload.persona_id == "p1"


@pytest.mark.asyncio
async def test_full_flow_returns_observations(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "你怎么看罗永浩"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="罗永浩", entities=["罗永浩"]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="你又在想老罗", basis_count=1,
                            basis_summary="1 条", basis_refs=["m1"]),
    ])

    service = PortraitService(**deps, active_persona_resolver=lambda: "p1")
    payload = await service.get_portrait(user_id="u1", session_id="s1")

    assert payload.is_cold_start is False
    assert len(payload.observations) == 1
    assert payload.observations[0].text == "你又在想老罗"
    assert payload.topic == "罗永浩"


@pytest.mark.asyncio
async def test_cache_hit_skips_llm(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=[]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="o1", basis_count=1,
                            basis_summary="1", basis_refs=["m1"]),
    ])
    service = PortraitService(**deps, active_persona_resolver=lambda: "p1")
    await service.get_portrait(user_id="u1", session_id="s1")
    # second call should hit cache
    deps["topic_extractor"].extract.reset_mock()
    deps["renderer"].render.reset_mock()
    payload = await service.get_portrait(user_id="u1", session_id="s1")
    assert payload.observations[0].text == "o1"
    deps["topic_extractor"].extract.assert_not_called()
    deps["renderer"].render.assert_not_called()


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=[]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="o1", basis_count=1,
                            basis_summary="1", basis_refs=["m1"]),
    ])
    service = PortraitService(**deps, active_persona_resolver=lambda: "p1")
    await service.get_portrait(user_id="u1", session_id="s1")
    deps["topic_extractor"].extract.reset_mock()
    await service.get_portrait(user_id="u1", session_id="s1", force=True)
    deps["topic_extractor"].extract.assert_called_once()


@pytest.mark.asyncio
async def test_no_active_persona_returns_empty_cold_start(deps):
    service = PortraitService(**deps, active_persona_resolver=lambda: None)
    payload = await service.get_portrait(user_id="u1", session_id="s1")
    assert payload.is_cold_start is True
    assert payload.persona_id == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/memory/portrait/test_service.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/magi/memory/portrait/service.py
"""Portrait orchestrator: messages → topic → snippets → persona-rendered observations."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from typing import Any, Awaitable, Callable

from .cache import PortraitCache
from .contracts import (
    PortraitObservation,
    PortraitPayload,
    RawMemorySnippet,
    TopicResult,
)


logger = logging.getLogger(__name__)


SnippetFetcher = Callable[[str, TopicResult], Awaitable[list[RawMemorySnippet]]]
MessageLoader = Callable[[str, str], Awaitable[list[dict[str, str]]]]
PersonaLoader = Callable[[str], dict[str, Any] | None]
ActivePersonaResolver = Callable[[], str | None]


class PortraitService:
    """Compose topic extraction, snippet fetching, and persona-lens rendering."""

    def __init__(
        self,
        *,
        topic_extractor: Any,
        renderer: Any,
        snippet_fetcher: SnippetFetcher,
        persona_loader: PersonaLoader,
        message_loader: MessageLoader,
        active_persona_resolver: ActivePersonaResolver,
        cache: PortraitCache | None = None,
        message_window: int = 10,
        random_seed: int | None = None,
    ) -> None:
        self._topic_extractor = topic_extractor
        self._renderer = renderer
        self._snippet_fetcher = snippet_fetcher
        self._persona_loader = persona_loader
        self._message_loader = message_loader
        self._active_persona_resolver = active_persona_resolver
        self._cache = cache or PortraitCache()
        self._message_window = int(message_window)
        self._rand = random.Random(random_seed)

    async def get_portrait(
        self,
        *,
        user_id: str,
        session_id: str,
        force: bool = False,
    ) -> PortraitPayload:
        persona_id = self._active_persona_resolver() or ""
        if not persona_id:
            return self._build_cold_start(session_id, persona_id="", cold_line="")

        messages = await self._message_loader(user_id, session_id)
        if len(messages) > self._message_window:
            messages = messages[-self._message_window:]

        topic_result = await self._topic_extractor.extract(messages)
        topic_hash = self._hash_topic(topic_result)

        key = (session_id, topic_hash, persona_id)
        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        snippets = await self._snippet_fetcher(user_id, topic_result)
        if not snippets:
            return self._cold_start_for_persona(session_id, persona_id)

        persona_detail = self._persona_loader(persona_id)
        persona_config = (persona_detail or {}).get("config") or {}

        recent_excerpt = self._last_user_message(messages)
        observations = await self._renderer.render(
            persona_config=persona_config,
            snippets=snippets,
            recent_message_excerpt=recent_excerpt,
            topic=topic_result.topic,
        )

        if not observations:
            return self._cold_start_for_persona(session_id, persona_id)

        payload = PortraitPayload(
            session_id=session_id,
            persona_id=persona_id,
            topic=topic_result.topic,
            generated_at=int(time.time()),
            observations=observations,
            is_cold_start=False,
        )
        self._cache.set(key, payload)
        return payload

    def invalidate_persona(self, persona_id: str) -> None:
        self._cache.invalidate_persona(persona_id)

    def _hash_topic(self, topic_result: TopicResult) -> str:
        raw = (topic_result.topic.lower() + "|" + ",".join(sorted(topic_result.entities))).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:16]

    def _last_user_message(self, messages: list[dict[str, str]]) -> str:
        for msg in reversed(messages):
            if str(msg.get("role") or "") == "user":
                return str(msg.get("content") or "")
        return ""

    def _cold_start_for_persona(self, session_id: str, persona_id: str) -> PortraitPayload:
        detail = self._persona_loader(persona_id) or {}
        config = detail.get("config") or {}
        interim_lines = (config.get("interim_lines") or {}).get("portrait_cold_start") or []
        line = ""
        if interim_lines:
            line = self._rand.choice(list(interim_lines))
        else:
            name = config.get("name") or "AI"
            line = f"{name} 还在认识你 · 跟我多聊聊"
        return self._build_cold_start(session_id, persona_id=persona_id, cold_line=line)

    def _build_cold_start(
        self,
        session_id: str,
        *,
        persona_id: str,
        cold_line: str,
    ) -> PortraitPayload:
        return PortraitPayload(
            session_id=session_id,
            persona_id=persona_id,
            topic="",
            generated_at=int(time.time()),
            observations=[],
            is_cold_start=True,
            cold_start_line=cold_line or None,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/memory/portrait/test_service.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/portrait/service.py backend/tests/memory/portrait/test_service.py
git commit -m "feat(memory/portrait): orchestrator with cache + cold-start"
```

---

## Task 6: Wire PortraitService to hybrid_retrieval (snippet fetcher)

**Files:**
- Modify: `backend/src/magi/memory/portrait/__init__.py` (add factory)
- Create: `backend/src/magi/memory/portrait/factory.py`
- Test: `backend/tests/memory/portrait/test_factory_snippet_fetcher.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/memory/portrait/test_factory_snippet_fetcher.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.portrait.contracts import RawMemorySnippet, TopicResult
from magi.memory.portrait.factory import build_snippet_fetcher


def _payload(*, l3=None, l2_assertions=None, l2_relationships=None, l4=None):
    return SimpleNamespace(
        l0_workbench=[],
        l1_events=[],
        l1_evidence_bundles=[],
        l1_timeline_summary=[],
        l2_entity_cards=[],
        l2_relationships=l2_relationships or [],
        l2_assertions=l2_assertions or [],
        l3_reflections=l3 or [],
        l4_procedures=l4 or [],
        l2_episodes=[],
        l2_state_facts=[],
        l2_state_history=[],
        trace={},
    )


@pytest.mark.asyncio
async def test_empty_topic_skips_retrieval():
    service = AsyncMock()
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: service)
    result = await fetcher("u1", TopicResult(topic="", entities=[]))
    assert result == []
    service.query.assert_not_called()


@pytest.mark.asyncio
async def test_aggregates_l2_l3_l4_into_snippets():
    service = AsyncMock()
    service.query = AsyncMock(return_value=_payload(
        l3=[{"summary_id": "s1", "content": "对失败者同理", "confidence": 0.8}],
        l2_assertions=[{"assertion_id": "a1", "statement": "不喜欢直播", "confidence": 0.9}],
        l2_relationships=[{"relationship_id": "r1", "subject": "self",
                           "predicate": "LIKES", "object": "Primal Scream",
                           "confidence": 0.7}],
        l4=[{"procedure_id": "p1", "title": "部署 Magi"}],
    ))
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: service)
    snippets = await fetcher("u1", TopicResult(topic="罗永浩", entities=["锤子"]))
    kinds = [s.kind for s in snippets]
    assert "reflection" in kinds
    assert "assertion" in kinds
    assert "relationship" in kinds
    assert "procedure" in kinds
    # L1 events not included
    assert all(s.layer in {"L2", "L3", "L4"} for s in snippets)


@pytest.mark.asyncio
async def test_limit_caps_snippets_to_15():
    service = AsyncMock()
    service.query = AsyncMock(return_value=_payload(
        l3=[{"summary_id": f"s{i}", "content": f"r{i}", "confidence": 0.5} for i in range(30)],
    ))
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: service)
    snippets = await fetcher("u1", TopicResult(topic="t", entities=[]))
    assert len(snippets) <= 15


@pytest.mark.asyncio
async def test_no_service_returns_empty():
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: None)
    result = await fetcher("u1", TopicResult(topic="t", entities=[]))
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/memory/portrait/test_factory_snippet_fetcher.py -v
```

Expected: ImportError / ModuleNotFoundError on `factory`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/magi/memory/portrait/factory.py
"""Wiring helpers: build a snippet fetcher around hybrid_retrieval service."""

from __future__ import annotations

import logging
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/memory/portrait/test_factory_snippet_fetcher.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/portrait/factory.py backend/tests/memory/portrait/test_factory_snippet_fetcher.py
git commit -m "feat(memory/portrait): cross-layer snippet fetcher wrapping hybrid_retrieval"
```

---

## Task 7: Backend API route + integration wiring

**Files:**
- Create: `backend/src/magi/api/routers/memory/portrait_routes.py`
- Modify: `backend/src/magi/api/routers/memory/router.py`
- Modify: `backend/src/magi/memory/portrait/factory.py` (add `build_portrait_service` that wires real adapters)
- Test: `backend/tests/api/test_memory_portrait_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_memory_portrait_routes.py
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.portrait_routes import (
    build_router,
    override_service_for_test,
)
from magi.memory.portrait.contracts import PortraitObservation, PortraitPayload


def _app():
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/memory")
    return app


def test_returns_payload_shape():
    service = AsyncMock()
    service.get_portrait = AsyncMock(return_value=PortraitPayload(
        session_id="s1",
        persona_id="p1",
        topic="罗永浩",
        generated_at=1700000000,
        observations=[
            PortraitObservation(kind="reflection", text="你又在想老罗", basis_count=1,
                                basis_summary="1 条", basis_refs=["m1"]),
        ],
    ))
    with override_service_for_test(service):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait", params={"session_id": "s1", "user_id": "u1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "s1"
    assert body["topic"] == "罗永浩"
    assert body["observations"][0]["text"] == "你又在想老罗"
    assert body["is_cold_start"] is False


def test_force_param_is_forwarded():
    service = AsyncMock()
    service.get_portrait = AsyncMock(return_value=PortraitPayload(
        session_id="s1", persona_id="p1", topic="", generated_at=0,
        is_cold_start=True, cold_start_line="hi",
    ))
    with override_service_for_test(service):
        client = TestClient(_app())
        client.get("/api/memory/portrait", params={"session_id": "s1", "user_id": "u1", "force": "true"})
    assert service.get_portrait.await_args.kwargs["force"] is True


def test_missing_session_id_returns_422():
    service = AsyncMock()
    with override_service_for_test(service):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait", params={"user_id": "u1"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/api/test_memory_portrait_routes.py -v
```

Expected: ImportError on `portrait_routes`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/magi/api/routers/memory/portrait_routes.py
"""GET /api/memory/portrait — persona-rendered observations for chat shell rail."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ....memory.portrait.contracts import PortraitPayload


_service_singleton: Any = None
_service_override: Any = None


def get_service() -> Any:
    if _service_override is not None:
        return _service_override
    if _service_singleton is None:
        raise HTTPException(status_code=503, detail="portrait_service_not_initialized")
    return _service_singleton


def set_service(service: Any) -> None:
    """Called once at app bootstrap to install the real PortraitService."""
    global _service_singleton
    _service_singleton = service


@contextmanager
def override_service_for_test(service: Any):
    global _service_override
    _service_override = service
    try:
        yield
    finally:
        _service_override = None


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/portrait")
    async def get_portrait(
        session_id: str = Query(..., min_length=1),
        user_id: str = Query(..., min_length=1),
        force: bool = Query(False),
        service: Any = Depends(get_service),
    ) -> dict:
        payload: PortraitPayload = await service.get_portrait(
            user_id=user_id,
            session_id=session_id,
            force=force,
        )
        return payload.to_dict()

    return router
```

```python
# backend/src/magi/api/routers/memory/router.py
# Append to existing file's include_router section:
from .portrait_routes import build_router as build_portrait_router

router.include_router(build_portrait_router())
```

Note: the existing `router.py` already exports a `router`. Verify with `Read` and append the include line at the appropriate location (typically after the other `include_router` calls).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/api/test_memory_portrait_routes.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Wire real service at app bootstrap**

Identify where memory subsystem is initialized (search `unified_memory` lifecycle). Add a call to `portrait_routes.set_service(build_portrait_service())` once dependencies are available.

```python
# Add to backend/src/magi/memory/portrait/factory.py
def build_portrait_service():
    """Construct a PortraitService wired to live adapters.

    Called once at app bootstrap after unified memory, persona registry, and
    scenario LLM pool are initialized.
    """
    from ...llm import LLMProviderBridge, LLMScenario
    from ...llm.scenario_pool import default_scenario_llm_pool
    from ...personality import get_persona_registry
    from ..provider import get_hybrid_retrieval_service
    from ...messaging import get_chat_message_loader  # may need to substitute with actual loader
    from .service import PortraitService
    from .topic_extractor import TopicExtractor
    from .persona_lens_renderer import PersonaLensRenderer

    pool = default_scenario_llm_pool()

    def bridge_factory():
        try:
            adapter = pool.get(LLMScenario.MEMORY_SUMMARIZER)
        except Exception:
            return None
        return _BridgeAdapter(adapter)

    topic_extractor = TopicExtractor(bridge_factory=bridge_factory)
    renderer = PersonaLensRenderer(bridge_factory=bridge_factory)
    snippet_fetcher = build_snippet_fetcher(
        retrieval_service_provider=lambda: get_hybrid_retrieval_service(),
    )

    registry = get_persona_registry()

    def persona_loader(persona_id: str):
        return registry.get_detail(persona_id) if persona_id else None

    def active_persona_resolver():
        return registry.get_active_id()

    async def message_loader(user_id: str, session_id: str):
        loader = get_chat_message_loader()
        return await loader.load_recent_messages(user_id=user_id, session_id=session_id, limit=20)

    return PortraitService(
        topic_extractor=topic_extractor,
        renderer=renderer,
        snippet_fetcher=snippet_fetcher,
        persona_loader=persona_loader,
        message_loader=message_loader,
        active_persona_resolver=active_persona_resolver,
    )


class _BridgeAdapter:
    """Adapt the existing chat LLM adapter to expose async `complete_json`."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        from ...llm import LLMProviderBridge
        self._bridge = LLMProviderBridge(adapter)

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        import json
        text = await self._bridge.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        try:
            return json.loads(text)
        except Exception:
            return {}
```

**Note for executor**: the imports for `get_persona_registry`, `default_scenario_llm_pool`, `get_chat_message_loader`, and `LLMProviderBridge.complete` may differ slightly in real codebase. Use `Read`/`Grep` to verify exact symbols before writing this file. If `get_chat_message_loader` doesn't exist, find how `messagesApi.listSessions`/load history is invoked from agent code and adapt.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/api/routers/memory/portrait_routes.py \
        backend/src/magi/api/routers/memory/router.py \
        backend/src/magi/memory/portrait/factory.py \
        backend/tests/api/test_memory_portrait_routes.py
git commit -m "feat(api): GET /api/memory/portrait route + wiring"
```

---

## Task 8: Persona seed JSON — cold-start lines

**Files:**
- Modify: `backend/src/magi/personality/seed/*.json` (each builtin persona)

- [ ] **Step 1: Identify all seed JSON files**

```bash
find backend/src/magi/personality/seed -name "*.json" -type f
```

- [ ] **Step 2: For each seed JSON, add `interim_lines.portrait_cold_start`**

For each seed file (e.g., `seven.json`), open it and add to the `interim_lines` object (create if missing):

```json
{
  "interim_lines": {
    "portrait_cold_start": [
      "我还在认识你呢，跟我多聊聊。",
      "你这边的轮廓还没浮出来。再多说说。",
      "我对你还没什么定见。等聊久一点。"
    ]
  }
}
```

Write 3 lines per persona, **in that persona's voice**. For example a stern academic persona might say "Insufficient data on you yet — proceed."

- [ ] **Step 3: Verify loader picks up the new key (existing test)**

```bash
cd backend && python -m pytest tests/personality/ -v -k "interim"
```

If no existing tests for this key, add a small one:

```python
# backend/tests/personality/test_interim_lines_portrait_cold_start.py
import json
from pathlib import Path


def test_all_builtin_personas_have_cold_start_lines():
    seed_dir = Path(__file__).parent.parent.parent / "src/magi/personality/seed"
    seed_files = list(seed_dir.glob("*.json"))
    assert seed_files, "no seed files found"
    for seed in seed_files:
        data = json.loads(seed.read_text(encoding="utf-8"))
        interim = data.get("interim_lines") or {}
        lines = interim.get("portrait_cold_start") or []
        assert isinstance(lines, list) and len(lines) >= 1, \
            f"{seed.name} missing portrait_cold_start"
```

- [ ] **Step 4: Run the new test**

```bash
cd backend && python -m pytest tests/personality/test_interim_lines_portrait_cold_start.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/personality/seed/*.json \
        backend/tests/personality/test_interim_lines_portrait_cold_start.py
git commit -m "feat(persona): cold-start lines per builtin persona"
```

---

## Task 9: Frontend API module

**Files:**
- Create: `frontend/src/api/modules/memoryPortrait.ts`

- [ ] **Step 1: Write the implementation directly** (frontend API modules are thin wrappers, TDD via component tests in later tasks)

```ts
// frontend/src/api/modules/memoryPortrait.ts
import { api } from '../client';

export type PortraitObservationKind = 'reflection' | 'assertion' | 'relationship' | 'procedure';

export interface PortraitObservation {
  kind: PortraitObservationKind;
  text: string;
  basis_count: number;
  basis_summary: string;
  basis_refs: string[];
}

export interface PortraitPayload {
  session_id: string;
  persona_id: string;
  topic: string;
  generated_at: number;
  observations: PortraitObservation[];
  is_cold_start: boolean;
  cold_start_line?: string | null;
}

export const memoryPortraitApi = {
  get: (sessionId: string, userId: string, options?: { force?: boolean }) =>
    api.get<PortraitPayload>('/memory/portrait', {
      params: {
        session_id: sessionId,
        user_id: userId,
        force: options?.force ? 'true' : 'false',
      },
    }),
};
```

- [ ] **Step 2: Type check**

```bash
cd frontend && npm run type-check
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/modules/memoryPortrait.ts
git commit -m "feat(api): memoryPortraitApi client module"
```

---

## Task 10: Frontend useMemoryPortrait hook

**Files:**
- Create: `frontend/src/hooks/useMemoryPortrait.ts`
- Test: `frontend/src/__tests__/useMemoryPortrait.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/useMemoryPortrait.test.tsx
import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { useMemoryPortrait } from '@/hooks/useMemoryPortrait';
import { memoryPortraitApi } from '@/api/modules/memoryPortrait';

vi.mock('@/api/modules/memoryPortrait');

describe('useMemoryPortrait', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(memoryPortraitApi.get).mockReset().mockResolvedValue({
      session_id: 's1',
      persona_id: 'p1',
      topic: 't',
      generated_at: 0,
      observations: [],
      is_cold_start: true,
      cold_start_line: 'hi',
    } as any);
  });

  it('fetches on mount with session and user', async () => {
    renderHook(() => useMemoryPortrait({ sessionId: 's1', userId: 'u1', personaId: 'p1' }));
    await waitFor(() => {
      expect(memoryPortraitApi.get).toHaveBeenCalledWith('s1', 'u1', { force: false });
    });
  });

  it('refetches with force=true when persona changes', async () => {
    const { rerender } = renderHook(
      ({ personaId }) => useMemoryPortrait({ sessionId: 's1', userId: 'u1', personaId }),
      { initialProps: { personaId: 'p1' } },
    );
    await waitFor(() => expect(memoryPortraitApi.get).toHaveBeenCalledTimes(1));
    rerender({ personaId: 'p2' });
    await waitFor(() => {
      expect(memoryPortraitApi.get).toHaveBeenLastCalledWith('s1', 'u1', { force: true });
    });
  });

  it('throttles refresh within 5 minutes', async () => {
    const { result } = renderHook(() =>
      useMemoryPortrait({ sessionId: 's1', userId: 'u1', personaId: 'p1' }),
    );
    await waitFor(() => expect(memoryPortraitApi.get).toHaveBeenCalledTimes(1));
    act(() => {
      result.current.refresh();
    });
    expect(memoryPortraitApi.get).toHaveBeenCalledTimes(1);
    act(() => {
      vi.advanceTimersByTime(5 * 60 * 1000 + 1);
    });
    act(() => {
      result.current.refresh();
    });
    await waitFor(() => expect(memoryPortraitApi.get).toHaveBeenCalledTimes(2));
  });

  it('returns null payload when sessionId is empty', async () => {
    const { result } = renderHook(() =>
      useMemoryPortrait({ sessionId: '', userId: 'u1', personaId: 'p1' }),
    );
    expect(result.current.payload).toBeNull();
    expect(memoryPortraitApi.get).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/__tests__/useMemoryPortrait.test.tsx
```

Expected: cannot find module `@/hooks/useMemoryPortrait`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/hooks/useMemoryPortrait.ts
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  memoryPortraitApi,
  type PortraitPayload,
} from '@/api/modules/memoryPortrait';

const THROTTLE_MS = 5 * 60 * 1000;

export interface UseMemoryPortraitArgs {
  sessionId: string;
  userId: string;
  personaId: string;
}

export interface UseMemoryPortraitResult {
  payload: PortraitPayload | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useMemoryPortrait({
  sessionId,
  userId,
  personaId,
}: UseMemoryPortraitArgs): UseMemoryPortraitResult {
  const [payload, setPayload] = useState<PortraitPayload | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastFetchAt = useRef<number>(0);
  const lastPersonaId = useRef<string>(personaId);

  const fetchPayload = useCallback(
    async (force: boolean) => {
      if (!sessionId || !userId || !personaId) {
        setPayload(null);
        return;
      }
      setIsLoading(true);
      setError(null);
      try {
        const res = await memoryPortraitApi.get(sessionId, userId, { force });
        setPayload((res as unknown as PortraitPayload) || null);
        lastFetchAt.current = Date.now();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, userId, personaId],
  );

  // initial / session-change fetch
  useEffect(() => {
    void fetchPayload(false);
  }, [sessionId, userId, fetchPayload]);

  // persona-change fetch with force=true
  useEffect(() => {
    if (lastPersonaId.current && lastPersonaId.current !== personaId) {
      void fetchPayload(true);
    }
    lastPersonaId.current = personaId;
  }, [personaId, fetchPayload]);

  const refresh = useCallback(() => {
    if (Date.now() - lastFetchAt.current < THROTTLE_MS) {
      return;
    }
    void fetchPayload(false);
  }, [fetchPayload]);

  return { payload, isLoading, error, refresh };
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/__tests__/useMemoryPortrait.test.tsx
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useMemoryPortrait.ts frontend/src/__tests__/useMemoryPortrait.test.tsx
git commit -m "feat(hooks): useMemoryPortrait fetch+refresh policy"
```

---

## Task 11: Frontend card + cold-start components

**Files:**
- Create: `frontend/src/components/chat/portrait/PortraitCard.tsx`
- Create: `frontend/src/components/chat/portrait/PortraitColdStart.tsx`

- [ ] **Step 1: Write implementations** (small leaf components, tested via container test in Task 13)

```tsx
// frontend/src/components/chat/portrait/PortraitCard.tsx
import { useTranslation } from 'react-i18next';
import { Brain, Heart, Network, Wrench } from 'lucide-react';
import type { PortraitObservation } from '@/api/modules/memoryPortrait';

const KIND_ICON = {
  reflection: Brain,
  assertion: Heart,
  relationship: Network,
  procedure: Wrench,
} as const;

const KIND_LABEL_KEY: Record<PortraitObservation['kind'], string> = {
  reflection: 'chat.portrait.kinds.reflection',
  assertion: 'chat.portrait.kinds.assertion',
  relationship: 'chat.portrait.kinds.relationship',
  procedure: 'chat.portrait.kinds.procedure',
};

export const PortraitCard = ({ observation }: { observation: PortraitObservation }) => {
  const { t } = useTranslation('app');
  const Icon = KIND_ICON[observation.kind];
  const kindLabel = t(KIND_LABEL_KEY[observation.kind]);
  return (
    <div
      className="flex flex-col gap-1.5 rounded-md border border-border/45 bg-background/60 px-3 py-2.5 text-[12.5px] leading-5"
      data-testid="portrait-card"
    >
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{kindLabel}</span>
      </div>
      <div className="text-foreground/90">{observation.text}</div>
      {observation.basis_summary ? (
        <div className="font-mono text-[10px] text-muted-foreground/70">
          {observation.basis_summary}
        </div>
      ) : null}
    </div>
  );
};
```

```tsx
// frontend/src/components/chat/portrait/PortraitColdStart.tsx
import { useTranslation } from 'react-i18next';

export const PortraitColdStart = ({ line }: { line: string | null | undefined }) => {
  const { t } = useTranslation('app');
  const text = line && line.trim() ? line : t('chat.portrait.coldStartFallback');
  return (
    <div
      className="flex flex-col items-start gap-1.5 rounded-md border border-dashed border-border/50 px-3 py-3 text-[12.5px] text-muted-foreground"
      data-testid="portrait-cold-start"
    >
      <span aria-hidden="true">🪞</span>
      <span>{text}</span>
    </div>
  );
};
```

- [ ] **Step 2: Type check**

```bash
cd frontend && npm run type-check
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/chat/portrait/PortraitCard.tsx \
        frontend/src/components/chat/portrait/PortraitColdStart.tsx
git commit -m "feat(chat/portrait): card + cold-start leaf components"
```

---

## Task 12: i18n keys for portrait

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`

- [ ] **Step 1: Add zh-CN keys**

Inside the existing `chat` object, add:

```json
"portrait": {
  "kinds": {
    "reflection": "反思",
    "assertion": "事实",
    "relationship": "关系",
    "procedure": "经验"
  },
  "coldStartFallback": "我还在认识你，多聊聊。",
  "title": "我对你的看法",
  "toggleAria": "切换画像板"
}
```

- [ ] **Step 2: Add en keys** (mirror structure)

```json
"portrait": {
  "kinds": {
    "reflection": "Reflection",
    "assertion": "Fact",
    "relationship": "Relation",
    "procedure": "Procedure"
  },
  "coldStartFallback": "Still getting to know you. Tell me more.",
  "title": "How I see you",
  "toggleAria": "Toggle portrait rail"
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json
git commit -m "i18n: chat.portrait.* keys (zh-CN + en)"
```

---

## Task 13: Frontend MemoryPortraitRail container

**Files:**
- Create: `frontend/src/components/chat/MemoryPortraitRail.tsx`
- Test: `frontend/src/__tests__/memoryPortraitRail.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/memoryPortraitRail.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { MemoryPortraitRail } from '@/components/chat/MemoryPortraitRail';
import { memoryPortraitApi } from '@/api/modules/memoryPortrait';

vi.mock('@/api/modules/memoryPortrait');

describe('MemoryPortraitRail', () => {
  beforeEach(() => {
    vi.mocked(memoryPortraitApi.get).mockReset();
  });

  it('renders cards when observations exist', async () => {
    vi.mocked(memoryPortraitApi.get).mockResolvedValue({
      session_id: 's1',
      persona_id: 'p1',
      topic: 't',
      generated_at: 0,
      observations: [
        { kind: 'reflection', text: '你又在想老罗', basis_count: 1, basis_summary: '1', basis_refs: [] },
        { kind: 'assertion', text: '你不喜欢直播', basis_count: 1, basis_summary: '1', basis_refs: [] },
      ],
      is_cold_start: false,
      cold_start_line: null,
    } as any);
    render(<MemoryPortraitRail sessionId="s1" userId="u1" personaId="p1" />);
    const cards = await screen.findAllByTestId('portrait-card');
    expect(cards).toHaveLength(2);
    expect(screen.getByText('你又在想老罗')).toBeInTheDocument();
  });

  it('renders cold-start when payload is empty', async () => {
    vi.mocked(memoryPortraitApi.get).mockResolvedValue({
      session_id: 's1', persona_id: 'p1', topic: '', generated_at: 0,
      observations: [], is_cold_start: true, cold_start_line: 'hi',
    } as any);
    render(<MemoryPortraitRail sessionId="s1" userId="u1" personaId="p1" />);
    await waitFor(() => expect(screen.getByTestId('portrait-cold-start')).toBeInTheDocument());
    expect(screen.getByText('hi')).toBeInTheDocument();
  });

  it('renders nothing visible when sessionId is missing', () => {
    render(<MemoryPortraitRail sessionId="" userId="u1" personaId="p1" />);
    expect(screen.queryByTestId('portrait-card')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-cold-start')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/__tests__/memoryPortraitRail.test.tsx
```

Expected: cannot find module.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/chat/MemoryPortraitRail.tsx
import { useTranslation } from 'react-i18next';
import { useMemoryPortrait } from '@/hooks/useMemoryPortrait';
import { PortraitCard } from './portrait/PortraitCard';
import { PortraitColdStart } from './portrait/PortraitColdStart';

export interface MemoryPortraitRailProps {
  sessionId: string;
  userId: string;
  personaId: string;
}

export const MemoryPortraitRail = ({
  sessionId,
  userId,
  personaId,
}: MemoryPortraitRailProps) => {
  const { t } = useTranslation('app');
  const { payload } = useMemoryPortrait({ sessionId, userId, personaId });

  if (!sessionId) {
    return null;
  }

  return (
    <aside
      className="flex h-full min-h-0 w-[320px] shrink-0 flex-col border-l border-border/60 bg-background/70"
      data-testid="memory-portrait-rail"
      aria-label={t('chat.portrait.title')}
    >
      <div className="flex h-11 shrink-0 items-center px-4 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {t('chat.portrait.title')}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3 pr-2 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        {payload?.is_cold_start || (payload?.observations.length ?? 0) === 0 ? (
          <PortraitColdStart line={payload?.cold_start_line ?? null} />
        ) : (
          payload?.observations.map((obs, idx) => (
            <PortraitCard key={`${obs.kind}-${idx}`} observation={obs} />
          ))
        )}
      </div>
    </aside>
  );
};
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/__tests__/memoryPortraitRail.test.tsx
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/MemoryPortraitRail.tsx frontend/src/__tests__/memoryPortraitRail.test.tsx
git commit -m "feat(chat): MemoryPortraitRail container"
```

---

## Task 14: MainLayout grid + chat-shell store integration

**Files:**
- Modify: `frontend/src/stores/chat-shell.ts`
- Modify: `frontend/src/components/layout/MainLayout.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Create: `frontend/src/components/chat/portrait/PortraitFloater.tsx`

- [ ] **Step 1: Extend chat-shell store**

Find the store definition (e.g., `useChatShellStore`) and add:

```ts
// frontend/src/stores/chat-shell.ts (add to existing state interface)
portraitRailOpen: boolean;
viewportIsNarrow: boolean;
setPortraitRailOpen: (open: boolean) => void;
setViewportIsNarrow: (narrow: boolean) => void;
```

In the create call, add defaults:

```ts
portraitRailOpen: true,
viewportIsNarrow: false,
setPortraitRailOpen: (open) => set({ portraitRailOpen: open }),
setViewportIsNarrow: (narrow) => set({ viewportIsNarrow: narrow }),
```

- [ ] **Step 2: Add viewport listener in MainLayout**

In `MainLayout.tsx` (`useEffect` near top):

```tsx
const setViewportIsNarrow = useChatShellStore((s) => s.setViewportIsNarrow);
useEffect(() => {
  const mql = window.matchMedia('(max-width: 1279px)');
  const onChange = (e: MediaQueryListEvent | MediaQueryList) => {
    setViewportIsNarrow('matches' in e ? e.matches : (e as MediaQueryList).matches);
  };
  onChange(mql);
  mql.addEventListener('change', onChange as EventListener);
  return () => mql.removeEventListener('change', onChange as EventListener);
}, [setViewportIsNarrow]);
```

- [ ] **Step 3: Update grid to 3 columns**

Change MainLayout's outer grid at line 93:

```tsx
// before
className="desktop-surface relative grid h-full w-full grid-cols-[auto_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden"
// after
className="desktop-surface relative grid h-full w-full grid-cols-[auto_minmax(0,1fr)_auto] grid-rows-[minmax(0,1fr)] overflow-hidden"
```

Then, after the existing chat content `<div className="col-start-2 ...">` block, before `<ShellOverlays />`, add the rail:

```tsx
<RailHost />
```

Below define `RailHost` in same file (or a small new file `MainLayoutRailHost.tsx`):

```tsx
// inline in MainLayout.tsx
import { useConversationStore } from '@/stores';
import { useActivePersona } from '@/hooks/useActivePersona';
import { MemoryPortraitRail } from '@/components/chat/MemoryPortraitRail';
import { PortraitFloater } from '@/components/chat/portrait/PortraitFloater';

const RailHost = () => {
  const portraitRailOpen = useChatShellStore((s) => s.portraitRailOpen);
  const viewportIsNarrow = useChatShellStore((s) => s.viewportIsNarrow);
  const currentSessionId = useConversationStore((s) => s.currentSessionId);
  const { persona } = useActivePersona();
  if (!portraitRailOpen || !currentSessionId || !persona) {
    return null;
  }
  const props = {
    sessionId: currentSessionId,
    userId: 'local_user', // align with DEFAULT_USER_ID; pull from constants
    personaId: persona.personaId,
  };
  return viewportIsNarrow ? <PortraitFloater {...props} /> : <MemoryPortraitRail {...props} />;
};
```

(Replace `'local_user'` with the actual `DEFAULT_USER_ID` import from `@/constants`.)

- [ ] **Step 4: Write PortraitFloater**

```tsx
// frontend/src/components/chat/portrait/PortraitFloater.tsx
import { useEffect } from 'react';
import { useChatShellStore } from '@/stores';
import { MemoryPortraitRail } from '../MemoryPortraitRail';

export interface PortraitFloaterProps {
  sessionId: string;
  userId: string;
  personaId: string;
}

export const PortraitFloater = (props: PortraitFloaterProps) => {
  const setOpen = useChatShellStore((s) => s.setPortraitRailOpen);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [setOpen]);

  return (
    <div
      className="absolute right-3 top-12 z-30 max-h-[70vh] w-[320px] overflow-hidden rounded-lg border border-border/60 bg-background shadow-lg"
      data-testid="portrait-floater"
    >
      <MemoryPortraitRail {...props} />
    </div>
  );
};
```

- [ ] **Step 5: Sidebar toggle button**

In `Sidebar.tsx`'s activity-bar bottom group (around line 626), add a new button **above the existing tasks button** that toggles `portraitRailOpen`:

```tsx
// imports
import { Sparkles } from 'lucide-react';

// inside the bottom group, before the "tasks" renderActivityButton call:
const portraitRailOpen = useChatShellStore((s) => s.portraitRailOpen);
const setPortraitRailOpen = useChatShellStore((s) => s.setPortraitRailOpen);

<button
  type="button"
  onClick={() => setPortraitRailOpen(!portraitRailOpen)}
  aria-label={t('chat.portrait.toggleAria')}
  title={t('chat.portrait.toggleAria')}
  className={activityButtonClass(false, portraitRailOpen)}
>
  <Sparkles className="h-[18px] w-[18px]" />
</button>
```

- [ ] **Step 6: Type check + run sidebar tests**

```bash
cd frontend && npm run type-check
cd frontend && npx vitest run src/__tests__/sidebarNavigation.test.tsx
```

Expected: type check passes; sidebar tests still pass (the new button has no expected `aria-current`, so existing tests remain valid).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/chat-shell.ts \
        frontend/src/components/layout/MainLayout.tsx \
        frontend/src/components/layout/Sidebar.tsx \
        frontend/src/components/chat/portrait/PortraitFloater.tsx
git commit -m "feat(layout): 3-column grid with portrait rail + responsive floater"
```

---

## Task 15: End-to-end acceptance check

**No files. Manual verification against spec section 9.**

- [ ] **Step 1: Start backend + frontend (user's existing Tauri dev session)**

Ensure backend has restarted to pick up the new endpoint and persona seeds.

- [ ] **Step 2: Walk through acceptance criteria**

For each item in the spec's section 9, verify in the running Tauri window:

- Default chat page shows rail within 1.5s (cards or cold-start)
- Switching persona changes rail content qualitatively
- Switching session refreshes rail
- Sending 5 messages in 5min triggers only 1 rail refresh
- Sending message after 5min triggers a refresh
- New user (or empty L2/L3/L4) → cold-start uses persona's `portrait_cold_start` line
- LLM failure → cold-start, no UI crash
- Window < 1280px → floater appears, main chat not squeezed

- [ ] **Step 3: Record any deviations**

If any acceptance item fails, file as follow-up. Do NOT mark the plan done until each item is checked or explicitly accepted.

- [ ] **Step 4: Final commit (if any tweaks needed for AC)**

```bash
git add <fixed-files>
git commit -m "fix(portrait): <specific issue> per acceptance walk-through"
```

---

## Post-Plan Cleanup

- [ ] Update `docs/memory-system-design.md` "对外暴露" section with the `/api/memory/portrait` contract
- [ ] Update `docs/persona-runtime-architecture.md` with the `interim_lines.portrait_cold_start` field
- [ ] Delete the spec file `docs/superpowers/specs/2026-05-17-chat-shell-portrait-rail-design.md`
- [ ] Delete this plan file `docs/superpowers/plans/2026-05-17-chat-shell-portrait-rail.md`
- [ ] Update `docs/dev/chat-shell-redesign-p1-plan.md` to mark P1.C as superseded by this work (or delete that section)
