from __future__ import annotations
import asyncio
import pytest
from magi.events.tracing import (
    TraceContext,
    current_trace_context,
    start_span,
)


def test_no_span_returns_none():
    assert current_trace_context() is None


def test_start_span_root():
    with start_span() as ctx:
        assert isinstance(ctx, TraceContext)
        assert ctx.trace_id is not None
        assert ctx.span_id is not None
        assert ctx.parent_span_id is None
        assert current_trace_context() is ctx


def test_start_span_nested_inherits_trace_id():
    with start_span() as parent:
        with start_span() as child:
            assert child.trace_id == parent.trace_id
            assert child.parent_span_id == parent.span_id
            assert child.span_id != parent.span_id
        assert current_trace_context() is parent


def test_context_restored_after_exit():
    with start_span() as outer:
        assert current_trace_context() is outer
    assert current_trace_context() is None


@pytest.mark.asyncio
async def test_create_task_inherits_context():
    captured: list[TraceContext | None] = []

    async def child():
        captured.append(current_trace_context())

    with start_span() as ctx:
        task = asyncio.create_task(child())
        await task

    assert captured[0] is not None
    assert captured[0].trace_id == ctx.trace_id


@pytest.mark.asyncio
async def test_gather_siblings_same_trace_distinct_spans():
    captured: list[TraceContext | None] = []

    async def sibling():
        with start_span() as s:
            captured.append(s)

    with start_span() as parent:
        await asyncio.gather(sibling(), sibling(), sibling())

    assert all(c is not None for c in captured)
    assert all(c.trace_id == parent.trace_id for c in captured)
    span_ids = {c.span_id for c in captured}
    assert len(span_ids) == 3


@pytest.mark.asyncio
async def test_concurrent_tasks_isolated():
    captured_a: TraceContext | None = None
    captured_b: TraceContext | None = None

    async def task_a():
        nonlocal captured_a
        with start_span() as ctx:
            await asyncio.sleep(0.01)
            captured_a = ctx

    async def task_b():
        nonlocal captured_b
        with start_span() as ctx:
            await asyncio.sleep(0.01)
            captured_b = ctx

    await asyncio.gather(task_a(), task_b())
    assert captured_a is not None and captured_b is not None
    assert captured_a.trace_id != captured_b.trace_id


def test_sync_function_in_async_span_sees_context():
    seen: list[TraceContext | None] = []

    def sync_helper():
        seen.append(current_trace_context())

    async def runner():
        with start_span():
            sync_helper()

    asyncio.run(runner())
    assert seen[0] is not None


def test_explicit_trace_id_creates_root_with_that_id():
    with start_span(trace_id="custom-trace-id") as ctx:
        assert ctx.trace_id == "custom-trace-id"
        assert ctx.parent_span_id is None
