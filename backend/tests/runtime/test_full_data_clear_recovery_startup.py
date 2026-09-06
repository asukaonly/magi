from __future__ import annotations

from dependency_injector import providers
import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStore,
)
from magi.agent.background.full_clear import BackgroundTaskFullClearOwner
from magi.api.routers.memory.overview_routes import clear_memory_layers
from magi.bootstrap.builder import build_runtime_modules
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.lifecycle import ModuleLifecycleOrchestrator
from magi.chat.contracts import ChatSessionRecord
from magi.config.models import AppConfig
from magi.core.container import get_container
from magi.events.contracts import RuntimeCommandType, SourceSyncCommand
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

FULL_CLEAR_TRANSACTION_ID = "clear-recovery-startup-test"


def _install_test_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime_paths: object,
    config: AppConfig,
) -> None:
    import magi.config.lifecycle as config_lifecycle
    import magi.memory.lifecycle as memory_lifecycle
    import magi.plugins.discovery as plugin_discovery
    import magi.plugins.manager as plugin_manager
    import magi.utils.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_runtime_paths", runtime_paths)
    monkeypatch.setattr(config_lifecycle, "get_config", lambda: config)
    monkeypatch.setattr(memory_lifecycle, "get_config", lambda: config)
    monkeypatch.setattr(plugin_discovery, "get_config", lambda: config)
    monkeypatch.setattr(plugin_manager, "get_config", lambda: config)


async def _seed_interrupted_runtime(
    *,
    runtime_paths: object,
) -> tuple[int, str]:
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths.message_queue_db_path),
    )
    await queue.start()
    command_id = await queue.enqueue_source_sync(
        SourceSyncCommand(
            source="test",
            source_name="history",
        )
    )
    claimed = await queue.claim_next(
        consumer_name="crashed-worker",
        command_types=(RuntimeCommandType.SOURCE_SYNC,),
    )
    assert claimed is not None
    assert claimed.command_id == command_id
    await queue.begin_full_user_content_clear(FULL_CLEAR_TRANSACTION_ID)
    await queue.stop()

    background_store = BackgroundTaskStore(
        db_path=str(runtime_paths.background_tasks_db_path),
    )
    task = BackgroundTask.new(
        BackgroundTaskSpec(
            user_id="local-user",
            session_id="recovery-session",
            origin_turn_id="turn-before-crash",
            title="Old background work",
            goal="This must never resume",
        )
    )
    await background_store.create_task(task)
    return command_id, task.task_id


@pytest.mark.asyncio
async def test_pending_startup_is_clear_only_and_completes_the_real_clear(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths_with_schema,
) -> None:
    config = AppConfig()
    config.plugins.scan_paths = []
    _install_test_runtime(
        monkeypatch,
        runtime_paths=runtime_paths_with_schema,
        config=config,
    )
    monkeypatch.setenv(
        "MAGI_FULL_DATA_CLEAR_TRANSACTION_ID",
        FULL_CLEAR_TRANSACTION_ID,
    )
    command_id, background_task_id = await _seed_interrupted_runtime(
        runtime_paths=runtime_paths_with_schema,
    )

    context = RuntimeBootstrapContext()
    orchestrator = ModuleLifecycleOrchestrator(build_runtime_modules(context))
    container = get_container()
    container.runtime_bootstrap_context.override(providers.Object(context))

    try:
        await orchestrator.startup()

        chat_store = context.chat.store
        assert chat_store is not None
        await chat_store.upsert_session(
            ChatSessionRecord(
                session_id="recovery-session",
                user_id="local-user",
                title="Sensitive chat",
                title_overridden=False,
                summary="Private summary",
                created_at_ms=1,
                updated_at_ms=1,
                last_message_at_ms=None,
                last_user_message_at_ms=None,
                last_message_preview="",
                last_user_message_preview="",
                message_count=0,
                archived_at_ms=None,
                deleted_at_ms=None,
            )
        )
        assert await chat_store.is_empty() is False

        queue = context.runtime_commands.runtime_command_queue
        assert queue is not None
        claimed_before_clear = await queue.claim_next(
            consumer_name="must-not-recover",
            command_types=(RuntimeCommandType.SOURCE_SYNC,),
        )
        assert claimed_before_clear is None

        assert context.runtime_commands.full_clear_recovery_pending is True
        assert context.llm.scenario_llm_pool is None
        assert context.llm.llm_adapter is None
        assert context.agent_runtime.agent_runtime is None
        assert context.agent_runtime.task_agent_manager is None
        assert isinstance(
            context.agent_runtime.background_task_manager,
            BackgroundTaskFullClearOwner,
        )
        assert context.agent_runtime.source_sync_executor is None
        assert context.memory.unified_memory is not None
        assert context.memory.memory_integration is not None
        assert context.memory.memory_integration._running is False
        assert context.memory.hybrid_retrieval_service is None
        assert context.chat.memory_projection_clear_lifecycle is not None
        assert context.plugins.user_content_clear_coordinator is not None
        assert context.scheduler.scheduler_service is not None
        assert context.scheduler.scheduler_service._active is False
        assert context.control_plane.module is not None
        assert context.channels.module is not None
        assert context.channels.module.session_mapper is not None

        processors = {
            module.name: module
            for module in orchestrator._modules
            if module.name
            in {
                "runtime_command_processor",
                "runtime_plugin_ingress_processor",
            }
        }
        assert processors["runtime_command_processor"]._task is None
        assert processors["runtime_plugin_ingress_processor"]._task is None
        assert context.message_bus.message_bus is not None
        assert context.message_bus.message_bus._running is False

        response = await clear_memory_layers(FULL_CLEAR_TRANSACTION_ID)

        assert response["success"] is True
        assert await chat_store.is_empty() is True
        assert (
            await context.agent_runtime.background_task_manager.store.get_task(background_task_id)
        ) is None
        completed_state = await queue.read_full_user_content_clear_state()
        assert completed_state.status == "idle"
        assert completed_state.transaction_id is None
        assert (
            await queue.claim_next(
                consumer_name="after-clear",
                command_types=(RuntimeCommandType.SOURCE_SYNC,),
            )
            is None
        )
        assert command_id > 0
    finally:
        await orchestrator.shutdown()
        container.runtime_bootstrap_context.reset_override()


@pytest.mark.asyncio
async def test_clear_only_background_owner_shutdown_is_idempotent(
    runtime_paths_with_schema,
) -> None:
    owner = BackgroundTaskFullClearOwner(
        store=BackgroundTaskStore(
            db_path=str(runtime_paths_with_schema.background_tasks_db_path),
        )
    )
    await owner.start()
    await owner.stop()
    await owner.stop()

    with pytest.raises(RuntimeError, match="global admission seal"):
        await owner.clear_all_history()

    async with owner.conversation_scope_boundary(reason="test"):
        result = await owner.clear_all_history()
    assert result["background_tasks"] == 0
