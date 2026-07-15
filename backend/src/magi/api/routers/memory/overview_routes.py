"""Memory overview, statistics, and clear API routes."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, status

from .clear import build_clear_memory_response
from .dependencies import (
    _resolve_manual_entry_asset_store,
    _resolve_memory_integration,
    _resolve_orchestration_store,
    _resolve_runtime_command_queue,
    _resolve_sensor_hub,
    _resolve_task_agent_manager,
    _resolve_unified_memory,
    get_chat_read_service,
    logger,
)
from .helpers import memory_t
from .router import memory_router
from .statistics import build_layer_statistics


async def _resume_clear_dependencies(
    *,
    task_agent_manager,
    chat_pause_started: bool,
    rebuild_manager,
    rebuild_pause_started: bool,
) -> list[tuple[str, BaseException]]:
    """Attempt every recovery step and return failures without masking clear errors."""
    failures: list[tuple[str, BaseException]] = []
    if chat_pause_started and task_agent_manager is not None:
        try:
            await task_agent_manager.resume_chat_work()
        except BaseException as exc:
            failures.append(("chat", exc))
    if rebuild_pause_started:
        try:
            await rebuild_manager.resume_starts()
        except BaseException as exc:
            failures.append(("embedding_rebuild", exc))
    return failures


def _log_recovery_failures(failures: list[tuple[str, BaseException]]) -> None:
    for name, exc in failures:
        logger.error(
            "clear_memory: failed to resume %s work",
            name,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def _raise_recovery_failure(failures: list[tuple[str, BaseException]]) -> None:
    names = ", ".join(name for name, _ in failures)
    first_failure = failures[0][1]
    if isinstance(first_failure, asyncio.CancelledError):
        raise first_failure
    raise RuntimeError(
        f"Failed to resume work after memory clear: {names}"
    ) from first_failure


async def _clear_chat_runtime_state() -> int:
    """Clear chat truth, trace rows, and persisted orchestration payloads."""
    chat_count = 0
    failures: list[tuple[str, BaseException]] = []
    try:
        chat_count = await get_chat_read_service().aclear_all_sessions()
    except BaseException as exc:
        failures.append(("chat_state", exc))
    try:
        await _resolve_orchestration_store().clear_all()
    except BaseException as exc:
        failures.append(("orchestration_state", exc))
    if failures:
        for name, failure in failures[1:]:
            logger.error(
                "clear_memory: additional context cleanup failed: %s",
                name,
                exc_info=(type(failure), failure, failure.__traceback__),
            )
        first_failure = failures[0][1]
        raise first_failure.with_traceback(first_failure.__traceback__)
    return int(chat_count or 0)


@memory_router.get("/statistics")
async def get_memory_statistics():
    """Return per-layer memory statistics in L0-L4 format."""
    unified_memory = _resolve_unified_memory()
    memory_integration = _resolve_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )

    async def _zero() -> int:
        return 0

    l1_coro = unified_memory.l1.count_events() if unified_memory.l1 else _zero()
    l2_rel_coro = unified_memory.l2.count_relationships() if unified_memory.l2 else _zero()
    l2_tom_coro = unified_memory.l2.count_tom_assertions() if unified_memory.l2 else _zero()
    l3_coro = unified_memory.l3.count_summaries() if unified_memory.l3 else _zero()
    l4_coro = unified_memory.l4.count_skills() if unified_memory.l4 else _zero()

    l1_count, l2_rel_count, l2_tom_count, l3_count, l4_count = await asyncio.gather(
        l1_coro,
        l2_rel_coro,
        l2_tom_coro,
        l3_coro,
        l4_coro,
    )
    return build_layer_statistics(
        unified_memory=unified_memory,
        l1_count=l1_count,
        l2_relation_count=l2_rel_count,
        l2_assertion_count=l2_tom_count,
        l3_count=l3_count,
        l4_count=l4_count,
        integration_stats=memory_integration.get_statistics() if memory_integration else None,
    )


@memory_router.delete("/clear")
async def clear_memory_layers():
    """Clear all memory layers and chat session mappings."""
    logger.info("clear_memory: request received")
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        logger.warning("clear_memory: memory system not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )

    logger.info("clear_memory: quiescing writers and clearing all layers")
    from .embedding_routes import _embedding_rebuild_manager

    task_agent_manager = _resolve_task_agent_manager()
    runtime_command_queue = _resolve_runtime_command_queue()
    sensor_hub = _resolve_sensor_hub()
    rebuild_pause_started = False
    chat_pause_started = False
    counts: dict[str, int] | None = None
    primary_failure: BaseException | None = None
    primary_traceback = None
    recovery_failures: list[tuple[str, BaseException]] = []
    try:
        async with runtime_command_queue.user_message_clear_boundary():
            try:
                rebuild_pause_started = True
                await _embedding_rebuild_manager.pause_starts_and_cancel_all()
                if task_agent_manager is not None:
                    chat_pause_started = True
                    await task_agent_manager.pause_chat_work_and_cancel_all()

                generation, purged_commands = (
                    await runtime_command_queue.advance_user_message_generation_and_purge()
                )
                purged_sensor_events = 0
                sensor_cleanup_failure: Exception | None = None
                if sensor_hub is not None:
                    try:
                        purged_sensor_events = await sensor_hub.discard_stale_user_messages(
                            generation
                        )
                    except Exception as exc:
                        sensor_cleanup_failure = exc
                        logger.exception(
                            "clear_memory: failed to discard stale SensorHub messages"
                        )
                logger.info(
                    "clear_memory: advanced user-message boundary. "
                    "generation=%d commands=%d sensor_events=%d",
                    generation,
                    purged_commands,
                    purged_sensor_events,
                )

                manual_entry_asset_store = _resolve_manual_entry_asset_store()
                auxiliary_clearers = (
                    [manual_entry_asset_store.clear]
                    if manual_entry_asset_store is not None
                    else []
                )
                counts = await unified_memory.clear_all_memory(
                    auxiliary_clearers=auxiliary_clearers,
                    context_clearer=_clear_chat_runtime_state,
                )
                if sensor_cleanup_failure is not None:
                    raise sensor_cleanup_failure
            except BaseException as exc:
                primary_failure = exc
                primary_traceback = exc.__traceback__

            recovery_failures = await _resume_clear_dependencies(
                task_agent_manager=task_agent_manager,
                chat_pause_started=chat_pause_started,
                rebuild_manager=_embedding_rebuild_manager,
                rebuild_pause_started=rebuild_pause_started,
            )
    except BaseException as exc:
        if primary_failure is None:
            primary_failure = exc
            primary_traceback = exc.__traceback__
        else:
            logger.error(
                "clear_memory: user-message boundary failed after clear error",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
    if recovery_failures:
        _log_recovery_failures(recovery_failures)
    if primary_failure is not None:
        raise primary_failure.with_traceback(primary_traceback)
    if recovery_failures:
        _raise_recovery_failure(recovery_failures)
    if counts is None:
        raise RuntimeError("Memory clear completed without a result")
    l0_count = counts["l0"]
    l1_count = counts["l1"]
    l2_count = counts["l2"]
    l3_count = counts["l3"]
    l4_count = counts["l4"]
    chat_context_count = counts["chat_context"]
    logger.info(
        "clear_memory: complete. l0=%d l1=%d l2=%d l3=%d l4=%d chat=%d",
        l0_count,
        l1_count,
        l2_count,
        l3_count,
        l4_count,
        chat_context_count,
    )

    return build_clear_memory_response(
        l0_count=l0_count,
        l1_count=l1_count,
        l2_count=l2_count,
        l3_count=l3_count,
        l4_count=l4_count,
        chat_context_count=chat_context_count,
    )
