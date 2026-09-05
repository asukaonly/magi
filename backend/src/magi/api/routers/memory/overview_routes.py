"""Memory overview, statistics, and clear API routes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Any

from fastapi import Header, HTTPException, status

from ....core.log_history import clear_diagnostic_log_history
from ....memory.portability.errors import MemoryPortabilityError
from ....memory.portability.service import get_memory_portability_service
from ....memory.store_lifecycle import MemoryClearCompletedWithRecoveryError
from ....plugins.user_content_clear import PluginUserContentClearRecoveryError
from magi_plugin_sdk import UserContentClearRequest

from .clear import ClearMemoryResponseModel, build_clear_memory_response
from .dependencies import (
    _resolve_manual_entry_asset_store,
    _resolve_manual_entry_weather_fetcher,
    _resolve_history_import_service,
    _resolve_legacy_user_content_clearer,
    _resolve_llm_usage_store,
    _resolve_llm_usage_subscriber,
    _resolve_mcp_resource_cache,
    _resolve_memory_integration,
    _resolve_channels_module,
    _resolve_channel_session_mapper,
    _resolve_chat_memory_projection_clear,
    _resolve_control_user_content_clear,
    _resolve_plugin_user_content_clear,
    _resolve_chat_portrait_service,
    _resolve_background_task_manager,
    _resolve_batch_store,
    _resolve_outreach_service,
    _resolve_runtime_command_queue,
    _resolve_scheduler_service,
    _resolve_runtime_trace_subscriber,
    _resolve_runtime_trace_store,
    _resolve_source_hub,
    _resolve_self_memory,
    _resolve_task_agent_manager,
    _resolve_tool_registry,
    _resolve_unified_memory,
    get_chat_read_service,
    logger,
)
from .helpers import memory_t
from .router import memory_router
from .statistics import build_layer_statistics


class _FullClearResidualError(RuntimeError):
    """Report local user content that remained after all clearers were attempted."""

    def __init__(self, failures: tuple[Exception, ...]) -> None:
        self.failures = failures
        super().__init__("Full user-content clear left local content pending")


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


async def _collect_post_clear_diagnostics(
    *,
    unified_memory,
    history_import_service,
) -> tuple[int | None, int | None, int | None]:
    """Read non-content counters after log erasure so the clear remains auditable."""

    l1_remaining_count: int | None = None
    history_job_count: int | None = None
    history_ledger_count: int | None = None
    l1 = getattr(unified_memory, "l1", None)
    count_events = getattr(l1, "count_events", None)
    if callable(count_events):
        try:
            l1_remaining_count = int(await count_events())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "clear_memory: post-clear L1 audit unavailable. error_type=%s",
                type(exc).__name__,
            )
    list_jobs = getattr(history_import_service, "list_jobs", None)
    if callable(list_jobs):
        try:
            jobs = await list_jobs(limit=100)
            history_job_count = len(jobs)
            history_ledger_count = sum(int(job.imported_count) for job in jobs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "clear_memory: post-clear history-import audit unavailable. error_type=%s",
                type(exc).__name__,
            )
    return l1_remaining_count, history_job_count, history_ledger_count


def _raise_recovery_failure(failures: list[tuple[str, BaseException]]) -> None:
    names = ", ".join(name for name, _ in failures)
    first_failure = failures[0][1]
    if isinstance(first_failure, asyncio.CancelledError):
        raise first_failure
    raise RuntimeError(f"Failed to resume work after memory clear: {names}") from first_failure


async def _clear_chat_runtime_state(
    *,
    background_task_manager,
    warnings: list[str],
    mark_chat_clear_committed: Callable[[int], None],
) -> int:
    """Clear chat truth, trace rows, and persisted orchestration payloads."""
    chat_read_service = get_chat_read_service()
    chat_failure: BaseException | None = None
    try:
        chat_count = await chat_read_service.aclear_all_sessions()
    except BaseException as exc:
        try:
            pending_count = await chat_read_service.aget_interrupted_global_clear_count()
        except BaseException:
            pending_count = None
        if pending_count is None:
            chat_failure = exc
            chat_count = 0
        else:
            chat_count = pending_count
            warnings.append("chat_asset_cleanup_pending")
            logger.error(
                "clear_memory: chat truth was cleared but physical asset cleanup is pending",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
    if chat_failure is None:
        mark_chat_clear_committed(chat_count)
    channel_session_mapper = _resolve_channel_session_mapper()
    channel_cleanup_succeeded = channel_session_mapper is not None
    if channel_session_mapper is not None:
        try:
            await channel_session_mapper.clear_conversation_state()
        except BaseException as exc:
            channel_cleanup_succeeded = False
            if chat_failure is None:
                warnings.append("channel_conversation_cleanup_failed")
            logger.error(
                "clear_memory: channel conversation cleanup failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
    elif chat_failure is None:
        warnings.append("channel_conversation_cleanup_pending")
        logger.warning("clear_memory: channel conversation cleanup will resume at channel startup")
    background_cleanup_succeeded = background_task_manager is not None
    if background_task_manager is not None:
        try:
            await background_task_manager.clear_all_history()
        except BaseException as exc:
            background_cleanup_succeeded = False
            if chat_failure is None:
                warnings.append("background_task_history_cleanup_failed")
            logger.error(
                "clear_memory: background task history cleanup failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
    elif chat_failure is None:
        warnings.append("background_task_history_cleanup_pending")
        logger.warning("clear_memory: background task history cleanup will resume at startup")
    batch_cleanup_succeeded = True
    try:
        await _resolve_batch_store().clear_all()
    except BaseException as exc:
        batch_cleanup_succeeded = False
        if chat_failure is not None:
            logger.error(
                "clear_memory: batch cleanup also failed after chat clear failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        else:
            warnings.append("batch_cleanup_failed")
            logger.error(
                "clear_memory: batch cleanup failed after chat truth was cleared",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
    if (
        chat_failure is None
        and channel_cleanup_succeeded
        and background_cleanup_succeeded
        and batch_cleanup_succeeded
    ):
        finalize = getattr(chat_read_service, "acomplete_global_clear", None)
        if callable(finalize):
            try:
                completed = await finalize()
                if completed is not True:
                    warnings.append("conversation_clear_finalization_failed")
                    logger.error(
                        "clear_memory: global conversation clear finalization was declined"
                    )
            except BaseException as exc:
                warnings.append("conversation_clear_finalization_failed")
                logger.error(
                    "clear_memory: global conversation clear remains pending",
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
    if chat_failure is not None:
        raise chat_failure.with_traceback(chat_failure.__traceback__)
    return int(chat_count or 0)


@asynccontextmanager
async def _conversation_delivery_clear_boundary():
    async with AsyncExitStack() as stack:
        service = _resolve_outreach_service()
        if service is not None:
            await stack.enter_async_context(service.conversation_clear_boundary())
        channels_module = _resolve_channels_module()
        if channels_module is not None:
            await stack.enter_async_context(channels_module.conversation_clear_boundary())
        yield


async def _reset_chat_delivery_after_failed_clear() -> int:
    """Best-effort compensation after the runtime queue was already purged."""
    reset = getattr(
        get_chat_read_service(),
        "areset_user_turn_delivery_after_failed_clear",
        None,
    )
    if not callable(reset):
        return 0
    return int(await reset() or 0)


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


@memory_router.delete("/clear", response_model=ClearMemoryResponseModel)
async def clear_memory_layers(
    full_clear_transaction_id: Annotated[
        str,
        Header(
            alias="X-Magi-Full-Clear-Transaction",
            min_length=16,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]+$",
        ),
    ],
) -> dict[str, Any]:
    """Clear user data plus every queued or active command that can recreate it."""
    try:
        async with get_memory_portability_service().user_content_clear_boundary() as clearer:
            return await _clear_memory_layers_with_portability_boundary(
                full_clear_transaction_id,
                clear_portability_private_data=clearer,
            )
    except MemoryPortabilityError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error_code": exc.code, "message": str(exc)},
        ) from exc


async def _clear_memory_layers_with_portability_boundary(
    full_clear_transaction_id: str,
    *,
    clear_portability_private_data: Callable[[], Awaitable[dict[str, int]]],
) -> dict[str, Any]:
    """Run full clear while the caller holds the portability maintenance boundary."""

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
    from ...services.personality_generation import (
        personality_generation_user_content_clear_boundary,
    )

    task_agent_manager = _resolve_task_agent_manager()
    background_task_manager = _resolve_background_task_manager()
    runtime_command_queue = _resolve_runtime_command_queue()
    if runtime_command_queue is None:
        logger.warning("clear_memory: runtime command queue not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.runtime_queue_uninitialized",
                "Runtime command queue not initialized",
            ),
        )
    scheduler_service = _resolve_scheduler_service()
    if scheduler_service is None:
        logger.warning("clear_memory: scheduler service not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.scheduler_uninitialized",
                "Scheduler service not initialized",
            ),
        )
    control_user_content_clear = _resolve_control_user_content_clear()
    if control_user_content_clear is None:
        logger.warning("clear_memory: control clear boundary not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.control_uninitialized",
                "Control plane not initialized",
            ),
        )
    plugin_user_content_clear = _resolve_plugin_user_content_clear()
    if plugin_user_content_clear is None:
        logger.warning("clear_memory: plugin clear boundary not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.plugin_runtime_uninitialized",
                "Plugin runtime not initialized",
            ),
        )
    chat_memory_projection_clear = _resolve_chat_memory_projection_clear()
    if chat_memory_projection_clear is None:
        logger.warning("clear_memory: chat memory recovery boundary not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.chat_recovery_uninitialized",
                "Chat recovery service not initialized",
            ),
        )
    source_hub = _resolve_source_hub()
    rebuild_pause_started = False
    chat_pause_started = False
    counts: dict[str, int] | None = None
    primary_failure: BaseException | None = None
    primary_traceback = None
    recovery_failures: list[tuple[str, BaseException]] = []
    queue_purged = False
    chat_clear_committed = False
    plugin_clear_failure: Exception | None = None
    residual_clear_failure: Exception | None = None
    plugin_clear_session = None
    history_import_service = None
    warnings: list[str] = []
    generation: int | None = None

    def mark_chat_clear_committed(chat_count: int) -> None:
        nonlocal chat_clear_committed
        chat_clear_committed = True

    async def clear_chat_runtime_state() -> int:
        return await _clear_chat_runtime_state(
            background_task_manager=background_task_manager,
            warnings=warnings,
            mark_chat_clear_committed=mark_chat_clear_committed,
        )

    try:
        async with AsyncExitStack() as clear_scope:
            await runtime_command_queue.begin_full_user_content_clear(full_clear_transaction_id)
            await clear_scope.enter_async_context(
                chat_memory_projection_clear.user_content_clear_boundary()
            )
            await clear_scope.enter_async_context(
                runtime_command_queue.user_message_global_clear_boundary()
            )
            async with AsyncExitStack() as background_scope:
                try:
                    await background_scope.enter_async_context(
                        scheduler_service.user_data_clear_boundary()
                    )
                    rebuild_pause_started = True
                    await _embedding_rebuild_manager.pause_starts_and_cancel_all()
                    if task_agent_manager is not None:
                        chat_pause_started = True
                        await task_agent_manager.pause_chat_work_and_cancel_all()
                    if background_task_manager is not None:
                        await background_scope.enter_async_context(
                            background_task_manager.conversation_scope_boundary(
                                reason="user_clear_all_memory",
                            )
                        )
                    await background_scope.enter_async_context(
                        personality_generation_user_content_clear_boundary()
                    )
                    await background_scope.enter_async_context(
                        control_user_content_clear.user_content_clear_boundary()
                    )
                    plugin_clear_session = await background_scope.enter_async_context(
                        plugin_user_content_clear.user_content_clear_boundary()
                    )
                    await background_scope.enter_async_context(
                        _resolve_tool_registry().user_content_clear_boundary()
                    )

                    (
                        generation,
                        purged_commands,
                    ) = await runtime_command_queue.advance_user_message_generation_and_purge()
                    queue_purged = True
                    purged_source_events = 0
                    source_cleanup_failure: Exception | None = None
                    if source_hub is not None:
                        try:
                            purged_source_events = await source_hub.discard_stale_user_messages(
                                generation
                            )
                        except Exception as exc:
                            source_cleanup_failure = exc
                            logger.exception(
                                "clear_memory: failed to discard stale SourceHub messages"
                            )
                    logger.info(
                        "clear_memory: advanced full-clear command boundary. "
                        "generation=%d commands=%d source_events=%d",
                        generation,
                        purged_commands,
                        purged_source_events,
                    )

                    manual_entry_asset_store = _resolve_manual_entry_asset_store()
                    manual_entry_weather_fetcher = _resolve_manual_entry_weather_fetcher()
                    auxiliary_clearers = []
                    if manual_entry_asset_store is not None:
                        auxiliary_clearers.append(manual_entry_asset_store.clear)
                    if manual_entry_weather_fetcher is not None:
                        auxiliary_clearers.append(manual_entry_weather_fetcher.clear)
                    self_memory = _resolve_self_memory()
                    if self_memory is not None:
                        auxiliary_clearers.append(self_memory.clear_learned_state)
                    legacy_user_content_clearer = _resolve_legacy_user_content_clearer()
                    if legacy_user_content_clearer is not None:
                        auxiliary_clearers.append(legacy_user_content_clearer)
                    llm_usage_store = _resolve_llm_usage_store()
                    if llm_usage_store is not None:
                        auxiliary_clearers.append(llm_usage_store.clear_user_content)
                    auxiliary_clearers.append(clear_portability_private_data)
                    plugin_clear_request = UserContentClearRequest(
                        clear_generation=generation,
                    )

                    async def clear_plugin_user_content():
                        nonlocal plugin_clear_failure
                        try:
                            return await plugin_clear_session.clear_user_content(
                                plugin_clear_request
                            )
                        except Exception as exc:
                            plugin_clear_failure = exc
                            logger.error(
                                "clear_memory: plugin user-content clear remains pending",
                                exc_info=(type(exc), exc, exc.__traceback__),
                            )
                            return None

                    auxiliary_clearers.append(clear_plugin_user_content)
                    auxiliary_clearers.append(scheduler_service.clear_user_data)
                    async with _conversation_delivery_clear_boundary():
                        async with AsyncExitStack() as content_cache_scope:
                            for subscriber in (
                                _resolve_runtime_trace_subscriber(),
                                _resolve_llm_usage_subscriber(),
                            ):
                                if subscriber is not None:
                                    await content_cache_scope.enter_async_context(
                                        subscriber.user_content_clear_boundary()
                                    )
                            await content_cache_scope.enter_async_context(
                                _resolve_mcp_resource_cache().global_data_clear_boundary()
                            )
                            portrait_service = _resolve_chat_portrait_service()
                            if portrait_service is not None:
                                await content_cache_scope.enter_async_context(
                                    portrait_service.global_data_clear_boundary()
                                )
                            runtime_trace_store = _resolve_runtime_trace_store()
                            if runtime_trace_store is not None:
                                await content_cache_scope.enter_async_context(
                                    runtime_trace_store.plugin_ingress_global_clear_boundary()
                                )
                            history_import_service = _resolve_history_import_service()
                            history_import_boundaries = (
                                (history_import_service.user_content_clear_boundary,)
                                if history_import_service is not None
                                else ()
                            )
                            try:
                                counts = await unified_memory.clear_all_memory(
                                    auxiliary_clearers=auxiliary_clearers,
                                    context_clearer=clear_chat_runtime_state,
                                    user_content_clear_boundaries=history_import_boundaries,
                                )
                            except MemoryClearCompletedWithRecoveryError as exc:
                                counts = exc.counts
                                warnings.append("memory_writer_resume_failed")
                                logger.error(
                                    "clear_memory: memory data was cleared but writers did not resume",
                                    exc_info=(
                                        type(exc.recovery_error),
                                        exc.recovery_error,
                                        exc.recovery_error.__traceback__,
                                    ),
                                )
                    if source_cleanup_failure is not None:
                        warnings.append("source_cleanup_failed")
                        logger.error(
                            "clear_memory: stale source message cleanup failed after clear",
                            exc_info=(
                                type(source_cleanup_failure),
                                source_cleanup_failure,
                                source_cleanup_failure.__traceback__,
                            ),
                        )
                    diagnostic_log_failure: Exception | None = None
                    try:
                        log_clear_result = await clear_diagnostic_log_history()
                    except Exception as exc:
                        diagnostic_log_failure = exc
                    else:
                        if log_clear_result.failed_entries:
                            diagnostic_log_failure = RuntimeError(
                                "Diagnostic log cleanup left "
                                f"{log_clear_result.failed_entries} entries uncleared"
                            )
                    residual_failures = tuple(
                        failure
                        for failure in (
                            plugin_clear_failure,
                            diagnostic_log_failure,
                        )
                        if failure is not None
                    )
                    if residual_failures:
                        residual_clear_failure = _FullClearResidualError(residual_failures)
                        raise residual_clear_failure from residual_failures[0]
                except BaseException as exc:
                    if plugin_clear_session is not None:
                        plugin_clear_session.mark_surrounding_clear_failed(exc)
                    primary_failure = exc
                    primary_traceback = exc.__traceback__

                if primary_failure is not None and queue_purged and not chat_clear_committed:
                    try:
                        reset_count = await _reset_chat_delivery_after_failed_clear()
                        logger.warning(
                            "clear_memory: reset %d surviving chat deliveries after clear failure",
                            reset_count,
                        )
                    except BaseException as exc:
                        recovery_failures.append(("chat_delivery_compensation", exc))

                recovery_failures.extend(
                    await _resume_clear_dependencies(
                        task_agent_manager=task_agent_manager,
                        chat_pause_started=chat_pause_started,
                        rebuild_manager=_embedding_rebuild_manager,
                        rebuild_pause_started=rebuild_pause_started,
                    )
                )
    except BaseException as exc:
        if isinstance(exc, PluginUserContentClearRecoveryError):
            residual_clear_failure = exc
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
    if (
        primary_failure is not None
        and chat_clear_committed
        and counts is not None
        and residual_clear_failure is None
        and not isinstance(primary_failure, asyncio.CancelledError)
    ):
        warnings.append("clear_boundary_recovery_failed")
        logger.error(
            "clear_memory: post-clear boundary recovery failed after data was cleared",
            exc_info=(
                type(primary_failure),
                primary_failure,
                primary_traceback,
            ),
        )
        primary_failure = None
        primary_traceback = None
    deferred_residual_failure = (
        residual_clear_failure is not None and chat_clear_committed and counts is not None
    )
    if primary_failure is not None and not deferred_residual_failure:
        if isinstance(primary_failure, MemoryPortabilityError):
            raise HTTPException(
                status_code=primary_failure.status_code,
                detail={
                    "error_code": primary_failure.code,
                    "message": str(primary_failure),
                },
            ) from primary_failure
        raise primary_failure.with_traceback(primary_traceback)
    if recovery_failures:
        if chat_clear_committed and counts is not None:
            warnings.extend(f"{name}_resume_failed" for name, _ in recovery_failures)
        else:
            _raise_recovery_failure(recovery_failures)
    if counts is None:
        raise RuntimeError("Memory clear completed without a result")
    l0_count = counts["l0"]
    l1_count = counts["l1"]
    l2_count = counts["l2"]
    l3_count = counts["l3"]
    l4_count = counts["l4"]
    chat_context_count = counts["chat_context"]
    (
        l1_remaining_count,
        history_import_job_count,
        history_import_ledger_count,
    ) = await _collect_post_clear_diagnostics(
        unified_memory=unified_memory,
        history_import_service=history_import_service,
    )
    logger.info(
        "clear_memory: complete. l0=%d l1=%d l2=%d l3=%d l4=%d chat=%d "
        "l1_remaining=%s history_jobs_remaining=%s history_records_remaining=%s "
        "generation=%s transaction_id=%s",
        l0_count,
        l1_count,
        l2_count,
        l3_count,
        l4_count,
        chat_context_count,
        l1_remaining_count,
        history_import_job_count,
        history_import_ledger_count,
        generation,
        full_clear_transaction_id,
    )

    if deferred_residual_failure:
        raise residual_clear_failure

    if warnings:
        raise RuntimeError(
            "Full user-content clear remains incomplete: " + ", ".join(dict.fromkeys(warnings))
        )
    if generation is None:
        raise RuntimeError("Memory clear completed without a clear generation")
    response = build_clear_memory_response(
        l0_count=l0_count,
        l1_count=l1_count,
        l2_count=l2_count,
        l3_count=l3_count,
        l4_count=l4_count,
        chat_context_count=chat_context_count,
        warnings=warnings,
    )
    await runtime_command_queue.complete_full_user_content_clear(
        transaction_id=full_clear_transaction_id,
    )
    return response
