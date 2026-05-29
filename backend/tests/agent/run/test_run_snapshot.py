"""Unit tests for RunSnapshot and NodeSnapshot tagged-union state container."""
from __future__ import annotations

import pytest

from magi.agent.run.snapshot import RunSnapshot


def test_run_snapshot_constructs_with_required_fields() -> None:
    snapshot = RunSnapshot(
        run_id="r1",
        graph=("tool_loop", "validate"),
        cursor=1,
        node_states={"tool_loop": {"messages": [], "iterations": 3}},
    )
    assert snapshot.run_id == "r1"
    assert snapshot.graph == ("tool_loop", "validate")
    assert snapshot.cursor == 1
    assert snapshot.node_states == {"tool_loop": {"messages": [], "iterations": 3}}


def test_run_snapshot_is_frozen() -> None:
    snapshot = RunSnapshot(run_id="r1", graph=("reply",), cursor=0, node_states={})
    with pytest.raises(Exception):
        snapshot.cursor = 5  # type: ignore[misc]


def test_run_snapshot_round_trips_through_to_dict_from_dict() -> None:
    original = RunSnapshot(
        run_id="r2",
        graph=("tool_loop", "validate"),
        cursor=1,
        node_states={
            "tool_loop": {"messages": [{"role": "user", "content": "hi"}], "iterations": 2},
            "validate": {},
        },
    )
    payload = original.to_dict()
    restored = RunSnapshot.from_dict(payload)
    assert restored == original


def test_run_snapshot_to_dict_uses_list_not_tuple_for_graph() -> None:
    """JSON-friendly: tuples don't survive json.dumps round-trip; emit list."""
    snapshot = RunSnapshot(run_id="r1", graph=("a", "b"), cursor=0, node_states={})
    payload = snapshot.to_dict()
    assert isinstance(payload["graph"], list)
    assert payload["graph"] == ["a", "b"]


def test_run_snapshot_from_dict_accepts_list_for_graph() -> None:
    """from_dict must accept the list form to round-trip through JSON."""
    payload = {"run_id": "r1", "graph": ["reply"], "cursor": 0, "node_states": {}}
    snapshot = RunSnapshot.from_dict(payload)
    assert snapshot.graph == ("reply",)


def test_run_snapshot_empty_node_states_is_valid() -> None:
    """Initial snapshot before any node has executed — empty node_states is fine."""
    snapshot = RunSnapshot(run_id="r1", graph=("reply",), cursor=0, node_states={})
    assert snapshot.cursor == 0
    assert snapshot.node_states == {}
