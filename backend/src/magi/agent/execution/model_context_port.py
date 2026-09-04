"""Runtime port for committing the model-visible context surface."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ModelContextRunClosedError(RuntimeError):
    """Signal that another terminal owner already closed this run surface."""


class ModelContextPort(Protocol):
    """Commit provider-neutral messages before the next model boundary."""

    async def commit(
        self,
        *,
        messages: list[dict[str, Any]],
        turn_id: str | None,
        run_id: str,
        step_index: int,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        boundary_kind: str | None = None,
        request_options: Mapping[str, Any] | None = None,
    ) -> None: ...


__all__ = ["ModelContextPort", "ModelContextRunClosedError"]
