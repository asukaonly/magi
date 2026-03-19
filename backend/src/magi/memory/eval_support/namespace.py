"""Namespace helpers for isolated benchmark memory evaluation runs."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

Cleaner = Callable[[str], Awaitable[int]]


def sanitize_eval_namespace_component(value: str) -> str:
    """Normalize a benchmark namespace component for safe reuse."""
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("._-")
    return normalized or "unknown"


def build_eval_namespace(*, benchmark_name: str, run_id: str, question_id: str) -> str:
    """Build a deterministic namespace identifier for one benchmark question."""
    return "/".join(
        [
            "benchmark",
            sanitize_eval_namespace_component(benchmark_name),
            sanitize_eval_namespace_component(run_id),
            sanitize_eval_namespace_component(question_id),
        ]
    )


class EvalNamespaceManager:
    """Tracks eval namespaces and performs scoped cleanup when supported."""

    def __init__(self, *, cleaner: Cleaner | None = None) -> None:
        self._cleaner = cleaner
        self._namespaces: set[str] = set()

    def create_namespace(self, *, benchmark_name: str, run_id: str, question_id: str) -> str:
        namespace = build_eval_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=question_id,
        )
        self._namespaces.add(namespace)
        return namespace

    def register_namespace(self, namespace: str) -> str:
        normalized = str(namespace).strip()
        if not normalized:
            raise ValueError("namespace must not be empty")
        self._namespaces.add(normalized)
        return normalized

    def is_registered(self, namespace: str) -> bool:
        return str(namespace).strip() in self._namespaces

    async def reset_namespace(self, namespace: str) -> int:
        normalized = str(namespace).strip()
        removed = 0
        if self._cleaner is not None:
            removed = int(await self._cleaner(normalized))
        self._namespaces.discard(normalized)
        return removed
