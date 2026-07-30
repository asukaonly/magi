"""HTTP client for driving LongMemEval against a running Magi backend."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import asdict
from typing import Any
from urllib import error, request

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQuery, EvalMemoryQueryResult


SESSION_TOKEN_ENV = "MAGI_DESKTOP_SESSION_TOKEN"
SESSION_TOKEN_HEADER = "X-Magi-Session-Token"


class BackendEvalService:
    """Thin async wrapper over benchmark-facing memory eval API endpoints."""

    def __init__(self, backend_url: str, *, timeout_seconds: float = 600.0) -> None:
        session_token = os.environ.get(SESSION_TOKEN_ENV)
        if session_token is None or not session_token.strip():
            raise RuntimeError(
                f"{SESSION_TOKEN_ENV} must be set to a non-empty temporary credential "
                "for benchmark gateway requests"
            )
        self._backend_url = str(backend_url).rstrip("/")
        self._timeout_seconds = float(timeout_seconds)
        self._session_token = session_token

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
            evidence_bundles=[dict(item) for item in response.get("evidence_bundles") or []],
            timeline_summary=[dict(item) for item in response.get("timeline_summary") or []],
            trace=dict(response.get("trace") or {}),
            answer=_normalize_optional_text(response.get("answer")),
            answer_trace=dict(response.get("answer_trace") or {}),
        )

    async def judge_answer(
        self,
        *,
        system_prompt: str,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "system_prompt": system_prompt,
            "prompt": prompt,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        if timeout_seconds is not None:
            payload["timeout_seconds"] = float(timeout_seconds)
        response = await asyncio.to_thread(
            self._post_json_sync,
            "/api/memory/eval/judge-answer",
            payload,
        )
        return dict(response)

    async def finalize_replay(
        self,
        *,
        period_types: list[str] | None = None,
        generate_summaries: bool = True,
        flush_l2: bool = True,
        drain_l2_edge_embeddings: bool = True,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._post_json_sync,
            "/api/memory/eval/finalize-replay",
            {
                "period_types": list(period_types or ["hour", "day", "week", "month"]),
                "generate_summaries": bool(generate_summaries),
                "flush_l2": bool(flush_l2),
                "drain_l2_edge_embeddings": bool(drain_l2_edge_embeddings),
            },
        )

    async def get_l2_pipeline_stats(self) -> dict[str, Any]:
        response = await asyncio.to_thread(
            self._post_json_sync,
            "/api/memory/eval/finalize-replay",
            _eval_l2_status_payload(),
        )
        stats = dict(response.get("l2_pipeline_stats") or {})
        stats.pop("canonical_self_id", None)
        stats.pop("identity_link_count", None)
        stats.pop("relation_count", None)
        stats.pop("assertion_count", None)
        stats.pop("db_path", None)
        return stats

    async def get_background_pending(self) -> dict[str, Any]:
        background = await asyncio.to_thread(self._get_json_sync, "/api/memory/background/pending")
        l2_stats = await self.get_l2_pipeline_stats()
        merged = dict(background)
        merged["l2"] = _describe_l2_pending(l2_stats)
        merged["all_idle"] = _is_background_pending_idle(merged)
        return merged

    def _post_json_sync(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._backend_url}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                SESSION_TOKEN_HEADER: self._session_token,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Backend request failed with {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError(
                f"Backend request to {path} timed out after {self._timeout_seconds:.1f}s"
            ) from exc

    def _get_json_sync(self, path: str) -> dict[str, Any]:
        url = f"{self._backend_url}{path}"
        req = request.Request(
            url,
            headers={
                "Accept": "application/json",
                SESSION_TOKEN_HEADER: self._session_token,
            },
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Backend request failed with {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError(
                f"Backend request to {path} timed out after {self._timeout_seconds:.1f}s"
            ) from exc


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


def _eval_l2_status_payload() -> dict[str, Any]:
    return {
        "period_types": [],
        "generate_summaries": False,
        "flush_l2": False,
        "drain_l2_edge_embeddings": False,
    }


def _describe_l2_pending(stats: dict[str, Any]) -> dict[str, Any]:
    projection_backlog = dict(stats.get("projection_backlog") or {})
    extract_active = max(int(stats.get("extract_active", 0) or 0), 0)
    reconcile_active = max(int(stats.get("reconcile_active", 0) or 0), 0)
    snapshot_active = max(int(stats.get("snapshot_active", 0) or 0), 0)
    extract_pending = max(
        int(stats.get("extract_enqueued", 0) or 0)
        - int(stats.get("extract_completed", 0) or 0)
        - int(stats.get("extract_failed", 0) or 0)
        - int(stats.get("extract_skipped", 0) or 0),
        int(projection_backlog.get("pending", 0) or 0)
        + int(projection_backlog.get("claimed", 0) or 0),
        extract_active,
        0,
    )
    return {
        "is_running": bool(stats.get("is_running", False)),
        "extract_pending": extract_pending,
        "extract_active": extract_active,
        "reconcile_pending": max(
            int(stats.get("reconcile_enqueued", 0) or 0)
            - int(stats.get("reconcile_completed", 0) or 0)
            - int(stats.get("reconcile_failed", 0) or 0),
            reconcile_active,
            0,
        ),
        "reconcile_active": reconcile_active,
        "snapshot_pending": max(
            int(stats.get("snapshot_enqueued", 0) or 0)
            - int(stats.get("snapshot_completed", 0) or 0)
            - int(stats.get("snapshot_failed", 0) or 0),
            snapshot_active,
            0,
        ),
        "snapshot_active": snapshot_active,
        "projection_pending": max(int(projection_backlog.get("pending", 0) or 0), 0),
        "projection_claimed": max(int(projection_backlog.get("claimed", 0) or 0), 0),
        "projection_failed": max(int(projection_backlog.get("failed", 0) or 0), 0),
    }


def _is_background_pending_idle(stats: dict[str, Any]) -> bool:
    return (
        all(
            int(stats.get("l2", {}).get(key, 0)) == 0
            for key in (
                "extract_pending",
                "extract_active",
                "reconcile_pending",
                "reconcile_active",
                "snapshot_pending",
                "snapshot_active",
            )
        )
        and int(stats.get("l1_embeddings", {}).get("pending", 0)) == 0
        and int(stats.get("l2_edge_embeddings", {}).get("pending", 0)) == 0
        and int(stats.get("l3_embeddings", {}).get("pending", 0)) == 0
        and int(stats.get("l4_embeddings", {}).get("pending", 0)) == 0
    )
