from __future__ import annotations
import asyncio
import pytest
from magi.events.tracing import (
    TraceContext,
    current_trace_context,
    start_span,
)


def test_start_span_root():
    with start_span() as ctx:
        assert isinstance(ctx, TraceContext)
        assert ctx.trace_id is not None
        assert ctx.span_id is not None
        assert ctx.parent_span_id is None
        assert current_trace_context() is ctx


def test_start_span_nested_inherits_trace_id():
    assert current_trace_context() is None
    with start_span() as parent:
        with start_span() as child:
            assert current_trace_context() is child
            assert child.trace_id == parent.trace_id
            assert child.parent_span_id == parent.span_id
            assert child.span_id != parent.span_id
        assert current_trace_context() is parent

    assert current_trace_context() is None


@pytest.mark.asyncio
async def test_create_task_inherits_context():
    captured: list[TraceContext | None] = []

    def sync_helper():
        return current_trace_context()

    async def child():
        captured.append(sync_helper())

    with start_span() as ctx:
        task = asyncio.create_task(child())
        await task

    assert captured == [ctx]
    assert captured[0] is ctx
    assert current_trace_context() is None


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
async def test_overlapping_tasks_read_their_own_context_until_and_after_sibling_exit():
    a_entered, b_entered, a_exited = asyncio.Event(), asyncio.Event(), asyncio.Event()
    contexts = {}

    async def task_a():
        with start_span() as ctx:
            contexts["a"] = ctx
            assert current_trace_context() is ctx
            a_entered.set()
            await b_entered.wait()
            assert current_trace_context() is ctx
        assert current_trace_context() is None
        a_exited.set()

    async def task_b():
        await a_entered.wait()
        with start_span() as ctx:
            contexts["b"] = ctx
            assert current_trace_context() is ctx
            b_entered.set()
            await a_exited.wait()
            assert current_trace_context() is ctx
        assert current_trace_context() is None

    await asyncio.wait_for(asyncio.gather(task_a(), task_b()), timeout=2)
    assert contexts["a"].trace_id != contexts["b"].trace_id
    assert current_trace_context() is None


def test_explicit_trace_id_creates_root_with_that_id():
    with start_span(trace_id="custom-trace-id") as ctx:
        assert ctx.trace_id == "custom-trace-id"
        assert ctx.parent_span_id is None
