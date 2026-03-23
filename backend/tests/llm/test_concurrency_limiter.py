"""Tests for shared LLM concurrency limiting."""

from __future__ import annotations

import asyncio

import pytest

from magi.llm.concurrency_limiter import LLMConcurrencyLimiter


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
    assert first == "openai::api.openai.com::gpt-5.2::chat"


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
