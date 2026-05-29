"""RunSnapshot: serialisable state for resuming a multi-node run.

Phase E scope: simple flat container.

* ``graph``: ordered tuple of node_type strings (e.g., ``("tool_loop", "validate")``).
  Tuples preferred for immutability; serialised as JSON lists via ``to_dict``.

* ``cursor``: index into ``graph`` of the node that should run next on
  resume. ``cursor == len(graph)`` means the run completed.

* ``node_states``: dict keyed by node_type holding each completed (or
  in-progress) node's snapshot state. Each value is a plain JSON-compatible
  dict — the Node knows how to interpret its own state via ``restore``.
  Phase E uses node_type as the key because sequences contain unique types
  (e.g., never two tool_loop nodes in one sequence). Phase F+ moves to a
  real node_id keying when multi-instance sequences appear.

* ``run_id``: identifies the AgentRun this snapshot belongs to. Used to
  match snapshots back to their owning run during background resume.

Phase F will extend this with ``trigger``, ``consumed_events``,
``deliveries`` for the full design-doc shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Serialisable RunSnapshot for resume after detach.

    Frozen so consumers cannot mutate a snapshot read from storage.
    Mutate via ``dataclasses.replace(snapshot, cursor=2, ...)``.
    """

    run_id: str
    graph: tuple[str, ...]
    cursor: int
    node_states: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly serialisation. ``graph`` becomes a list."""
        return {
            "run_id": self.run_id,
            "graph": list(self.graph),
            "cursor": int(self.cursor),
            "node_states": {
                node_type: dict(state) for node_type, state in self.node_states.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunSnapshot":
        return cls(
            run_id=str(payload["run_id"]),
            graph=tuple(payload.get("graph") or ()),
            cursor=int(payload.get("cursor") or 0),
            node_states={
                str(node_type): dict(state or {})
                for node_type, state in (payload.get("node_states") or {}).items()
            },
        )


__all__ = ["RunSnapshot"]
