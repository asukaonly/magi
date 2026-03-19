"""HTTP client for driving LongMemEval against a running Magi backend."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Any
from urllib import error, request

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQuery, EvalMemoryQueryResult


class BackendEvalService:
    """Thin async wrapper over benchmark-facing memory eval API endpoints."""

    def __init__(self, backend_url: str) -> None:
        self._backend_url = str(backend_url).rstrip("/")

    async def write_records(self, *, namespace: str, records: list[Any]) -> dict[str, Any]:
        payload = {
            "namespace": namespace,
            "records": [asdict(record) for record in records],
        }
        return await asyncio.to_thread(self._post_json_sync, "/api/memory/eval/replay", payload)

    async def query_memory(self, query: EvalMemoryQuery) -> EvalMemoryQueryResult:
        payload = asdict(query)
        response = await asyncio.to_thread(self._post_json_sync, "/api/memory/eval/query", payload)
        hits = [
            EvalMemoryHit(
                event_id=str(item.get("event_id") or ""),
                session_id=_normalize_optional_text(item.get("session_id")),
                turn_id=_normalize_optional_text(item.get("turn_id")),
                score=_normalize_optional_float(item.get("score")),
                content=str(item.get("content") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in response.get("hits") or []
        ]
        return EvalMemoryQueryResult(
            hits=hits,
            trace=dict(response.get("trace") or {}),
        )

    def _post_json_sync(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._backend_url}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Backend request failed with {exc.code}: {detail}") from exc


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
