"""Tool-history compaction hysteresis (#100/P2b).

Compaction must be append-only between triggers so the request prefix stays
byte-stable and the provider prompt-cache keeps hitting through a tool loop.
It should only rewrite the history when raw tool blocks reach the high-water
mark (_COMPACT_TRIGGER), then reduce to the floor (_RAW_TOOL_HISTORY_LIMIT).
"""

from magi.agent.execution.function_calling.messages import (
    FunctionCallingMessageHistoryMixin,
)


class _History(FunctionCallingMessageHistoryMixin):
    _RAW_TOOL_HISTORY_LIMIT = 2
    _COMPACT_TRIGGER = 4


def _tool_block(i: int) -> list[dict]:
    return [
        {"role": "assistant", "content": "", "tool_calls": [{"id": f"t{i}", "function": {"name": "bash"}}]},
        {"role": "tool", "tool_call_id": f"t{i}", "content": '{"success": true}'},
    ]


def _build(n: int) -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": "hi"}]
    for i in range(n):
        msgs.extend(_tool_block(i))
    return msgs


def _summary_count(msgs: list[dict]) -> int:
    return sum(
        1 for m in msgs if str(m.get("content", "")).startswith("Previous tool activity summary:")
    )


def test_no_compaction_below_trigger() -> None:
    host = _History()
    msgs = _build(3)  # 3 raw blocks, below trigger (4)
    host._compact_message_history(msgs)
    # Append-only: nothing summarized, all raw blocks retained, prefix unchanged.
    assert _summary_count(msgs) == 0
    assert len(host._collect_completed_tool_blocks(msgs)) == 3


def test_compaction_fires_at_trigger_and_reduces_to_floor() -> None:
    host = _History()
    msgs = _build(4)  # reaches trigger
    host._compact_message_history(msgs)
    assert _summary_count(msgs) == 1
    assert len(host._collect_completed_tool_blocks(msgs)) <= host._RAW_TOOL_HISTORY_LIMIT


def test_append_only_between_triggers() -> None:
    host = _History()
    msgs = _build(4)
    host._compact_message_history(msgs)  # -> summary + 2 raw blocks
    # Add one more completed block via the real append path (now 3 raw < trigger).
    for m in _tool_block(99):
        host._append_message(msgs, m)
    # No re-compaction: still a single summary, raw blocks just grew by one.
    assert _summary_count(msgs) == 1
    assert len(host._collect_completed_tool_blocks(msgs)) == 3


def test_compaction_invalidates_provider_usage_snapshot() -> None:
    class _UsageTracker:
        def __init__(self) -> None:
            self.calls = 0

        def invalidate_recorded_usage(self) -> None:
            self.calls += 1

    host = _History()
    usage_tracker = _UsageTracker()
    host._context_compactor = usage_tracker  # type: ignore[attr-defined]
    msgs = _build(3)

    for message in _tool_block(99):
        host._append_message(msgs, message)

    assert _summary_count(msgs) == 1
    assert usage_tracker.calls == 1
