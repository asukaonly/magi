"""Tests for shared LLM concurrency limiting."""

from __future__ import annotations

import asyncio

import pytest

from magi.llm.concurrency_limiter import LLMConcurrencyLimiter, LLMRequestPriority


def test_build_limit_key_normalizes_base_url_host_and_request_family() -> None:
    limiter = LLMConcurrencyLimiter()

    first = limiter.build_key(
        provider_name="OpenAI",
        model_name="gpt-5.2",
        request_family="chat",
        base_url="https://api.openai.com/v1",
    )
    second = limiter.build_key(
        provider_name="openai",
        model_name="gpt-5.2",
        request_family="chat",
        base_url="https://api.openai.com/v1beta",
    )

    assert first == second
    assert first == "openai::openai::api::api.openai.com::gpt-5.2::chat"


def test_build_limit_key_separates_provider_instances_and_plans() -> None:
    limiter = LLMConcurrencyLimiter()

    first_account = limiter.build_key(
        provider_name="dashscope",
        provider_instance_id="dashscope-work",
        provider_plan="codeplan",
        model_name="qwen3.7-plus",
        request_family="chat",
        base_url="https://coding.dashscope.aliyuncs.com/v1",
    )
    second_account = limiter.build_key(
        provider_name="dashscope",
        provider_instance_id="dashscope-personal",
        provider_plan="codeplan",
        model_name="qwen3.7-plus",
        request_family="chat",
        base_url="https://coding.dashscope.aliyuncs.com/v1",
    )
    normal_api = limiter.build_key(
        provider_name="dashscope",
        provider_instance_id="dashscope-work",
        provider_plan=None,
        model_name="qwen3.7-plus",
        request_family="chat",
        base_url="https://coding.dashscope.aliyuncs.com/v1",
    )

    assert first_account != second_account
    assert first_account != normal_api


def test_build_limit_key_separates_embedding_family() -> None:
    limiter = LLMConcurrencyLimiter()

    chat_key = limiter.build_key(
        provider_name="openai",
        model_name="text-embedding-3-small",
        request_family="chat",
        base_url="https://api.openai.com/v1",
    )
    embedding_key = limiter.build_key(
        provider_name="openai",
        model_name="text-embedding-3-small",
        request_family="embedding",
        base_url="https://api.openai.com/v1",
    )

    assert chat_key != embedding_key
    assert embedding_key.endswith("::embedding")


@pytest.mark.asyncio
async def test_run_with_limit_serializes_same_key_requests() -> None:
    limiter = LLMConcurrencyLimiter(default_limit=1)
    key = limiter.build_key(
        provider_name="openai",
        model_name="gpt-5.2",
        request_family="chat",
        base_url="https://api.openai.com/v1",
    )

    entered: list[str] = []
    release_first = asyncio.Event()
    first_has_entered = asyncio.Event()

    async def first_operation() -> str:
        entered.append("first")
        first_has_entered.set()
        await release_first.wait()
        return "first"

    async def second_operation() -> str:
        entered.append("second")
        return "second"

    first_task = asyncio.create_task(
        limiter.run_with_limit(key, first_operation, limit=1)
    )
    await first_has_entered.wait()

    second_task = asyncio.create_task(
        limiter.run_with_limit(key, second_operation, limit=1)
    )
    await asyncio.sleep(0)

    assert entered == ["first"]
    assert limiter.get_stats(key).active == 1
    assert limiter.get_stats(key).waiting == 1

    release_first.set()

    assert await first_task == "first"
    assert await second_task == "second"
    assert entered == ["first", "second"]
    assert limiter.get_stats(key).active == 0
    assert limiter.get_stats(key).waiting == 0


@pytest.mark.asyncio
async def test_run_with_limit_releases_waiter_on_cancellation() -> None:
    limiter = LLMConcurrencyLimiter(default_limit=1)
    key = limiter.build_key(
        provider_name="openai",
        model_name="gpt-5.2",
        request_family="chat",
    )

    release_first = asyncio.Event()
    first_has_entered = asyncio.Event()

    async def first_operation() -> str:
        first_has_entered.set()
        await release_first.wait()
        return "first"

    async def second_operation() -> str:
        return "second"

    first_task = asyncio.create_task(limiter.run_with_limit(key, first_operation, limit=1))
    await first_has_entered.wait()

    second_task = asyncio.create_task(limiter.run_with_limit(key, second_operation, limit=1))
    await asyncio.sleep(0)
    assert limiter.get_stats(key).waiting == 1

    second_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second_task

    release_first.set()
    assert await first_task == "first"
    assert limiter.get_stats(key).active == 0
    assert limiter.get_stats(key).waiting == 0


@pytest.mark.asyncio
async def test_run_with_limit_updates_existing_key_limit_for_later_refresh() -> None:
    limiter = LLMConcurrencyLimiter(default_limit=1)
    key = limiter.build_key(
        provider_name="openai",
        model_name="gpt-5.2",
        request_family="chat",
        base_url="https://api.openai.com/v1",
    )

    release_first = asyncio.Event()
    first_has_entered = asyncio.Event()
    second_has_entered = asyncio.Event()
    release_second = asyncio.Event()

    async def first_operation() -> str:
        first_has_entered.set()
        await release_first.wait()
        return "first"

    async def second_operation() -> str:
        second_has_entered.set()
        await release_second.wait()
        return "second"

    first_task = asyncio.create_task(limiter.run_with_limit(key, first_operation, limit=1))
    await first_has_entered.wait()

    second_task = asyncio.create_task(limiter.run_with_limit(key, second_operation, limit=2))
    await asyncio.wait_for(second_has_entered.wait(), timeout=1.0)

    stats = limiter.get_stats(key)
    assert stats.limit == 2
    assert stats.active == 2

    release_second.set()

    release_first.set()

    assert await first_task == "first"
    assert await second_task == "second"
    assert limiter.get_stats(key).active == 0
    assert limiter.get_stats(key).waiting == 0


@pytest.mark.asyncio
async def test_low_priority_requests_leave_capacity_for_high_priority_work() -> None:
    limiter = LLMConcurrencyLimiter(default_limit=3)
    key = limiter.build_key(
        provider_name="openai",
        model_name="gpt-5.2",
        request_family="chat",
    )

    entered: list[str] = []
    release_low = asyncio.Event()
    low_started = [asyncio.Event(), asyncio.Event()]

    async def low_operation(index: int) -> str:
        entered.append(f"low-{index}")
        low_started[index].set()
        await release_low.wait()
        return f"low-{index}"

    first_low = asyncio.create_task(
        limiter.run_with_limit(
            key,
            lambda: low_operation(0),
            limit=3,
            priority=LLMRequestPriority.LOW,
        )
    )
    second_low = asyncio.create_task(
        limiter.run_with_limit(
            key,
            lambda: low_operation(1),
            limit=3,
            priority=LLMRequestPriority.LOW,
        )
    )

    await asyncio.wait_for(low_started[0].wait(), timeout=1.0)
    await asyncio.wait_for(low_started[1].wait(), timeout=1.0)

    third_low_started = asyncio.Event()

    async def third_low_operation() -> str:
        entered.append("low-2")
        third_low_started.set()
        return "low-2"

    third_low = asyncio.create_task(
        limiter.run_with_limit(
            key,
            third_low_operation,
            limit=3,
            priority=LLMRequestPriority.LOW,
        )
    )
    await asyncio.sleep(0)

    assert not third_low_started.is_set()
    assert limiter.get_stats(key).active == 2
    assert limiter.get_stats(key).waiting == 1

    high_started = asyncio.Event()

    async def high_operation() -> str:
        entered.append("high")
        high_started.set()
        return "high"

    high_task = asyncio.create_task(
        limiter.run_with_limit(
            key,
            high_operation,
            limit=3,
            priority=LLMRequestPriority.HIGH,
        )
    )

    assert await high_task == "high"
    assert high_started.is_set()
    assert not third_low_started.is_set()
    assert entered == ["low-0", "low-1", "high"]

    release_low.set()

    assert await first_low == "low-0"
    assert await second_low == "low-1"
    assert await third_low == "low-2"


@pytest.mark.asyncio
async def test_high_priority_waiter_runs_before_queued_low_priority_work() -> None:
    limiter = LLMConcurrencyLimiter(default_limit=1)
    key = limiter.build_key(
        provider_name="openai",
        model_name="gpt-5.2",
        request_family="chat",
    )

    entered: list[str] = []
    release_running = asyncio.Event()
    running_started = asyncio.Event()

    async def running_operation() -> str:
        entered.append("running")
        running_started.set()
        await release_running.wait()
        return "running"

    running_task = asyncio.create_task(
        limiter.run_with_limit(
            key,
            running_operation,
            limit=1,
            priority=LLMRequestPriority.LOW,
        )
    )
    await running_started.wait()

    async def low_operation() -> str:
        entered.append("low")
        return "low"

    async def high_operation() -> str:
        entered.append("high")
        return "high"

    low_task = asyncio.create_task(
        limiter.run_with_limit(
            key,
            low_operation,
            limit=1,
            priority=LLMRequestPriority.LOW,
        )
    )
    await asyncio.sleep(0)

    high_task = asyncio.create_task(
        limiter.run_with_limit(
            key,
            high_operation,
            limit=1,
            priority=LLMRequestPriority.HIGH,
        )
    )
    await asyncio.sleep(0)
    release_running.set()

    assert await running_task == "running"
    assert await high_task == "high"
    assert await low_task == "low"
    assert entered == ["running", "high", "low"]
