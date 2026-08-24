"""Run-scoped plan read boundary for completion governance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from magi.control.run_plan import RunPlan


class RunPlanReader(Protocol):
    """Read the current plan bound to exactly one canonical run."""

    def current(self) -> RunPlan | None: ...


@dataclass(frozen=True, slots=True)
class BoundRunPlanReader:
    """Bind a control-session store to one session and run identity."""

    store: object
    session_id: str
    run_id: str

    def current(self) -> RunPlan | None:
        read = getattr(self.store, "current_run_plan", None)
        if not callable(read):
            raise RuntimeError("Run plan store does not provide current_run_plan")
        return read(self.session_id, run_id=self.run_id)


class NullRunPlanReader:
    """Explicitly disable plans for run presets that cannot author them."""

    def current(self) -> None:
        return None


__all__ = ["BoundRunPlanReader", "NullRunPlanReader", "RunPlanReader"]
