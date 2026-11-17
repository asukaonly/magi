"""Connect quiet reflection to existing memory, chat and scheduling owners."""

from ..identity.defaults import CANONICAL_LOCAL_USER
from ..memory.reflection_evidence import ReflectionEvidenceReader
from ..personality.persona_journal_service import PersonaJournalService, bind_persona_journal_service
from ..personality.persona_repository import PersonaRepository
from ..personality.reflection_store import ReflectionStore
from ..personal_tasks.store import PersonalTaskStore
from ..scheduler.contracts import ScheduledExecutionContext, ScheduledExecutionResult, ScheduledTargetType
from .context import RuntimeBootstrapContext, require_initialized
from .lifecycle import LifecycleModule


async def forget_proactive_derivatives(context: RuntimeBootstrapContext, event_ids: list[str]) -> None:
    paths = require_initialized(context.core.runtime_paths, "runtime paths")
    await ReflectionStore(str(paths.growth_db_path)).forget_events(event_ids)
    await PersonalTaskStore(str(paths.personal_tasks_db_path)).forget_watch_events(event_ids)


class PersonaReflectionModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(name="runtime_persona_reflection", dependencies=(
            "runtime_personality", "runtime_chat_store", "runtime_scheduler", "runtime_agent_core",
        ))
        self._context = context

    async def init(self) -> None:
        paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        memory = require_initialized(self._context.memory.unified_memory, "memory")
        self._personas = PersonaRepository(str(paths.persona_registry_db_path))
        self._service = PersonaJournalService(
            store=ReflectionStore(str(paths.growth_db_path)), evidence=ReflectionEvidenceReader(memory),
            personas=self._personas, allow_event=self._allow_event,
        )
        bind_persona_journal_service(self._service)
        scheduler = require_initialized(self._context.scheduler.scheduler_service, "scheduler")
        scheduler.register_handler(ScheduledTargetType.PERSONA_REFLECTION, self._run)
        if not self._context.runtime_commands.full_clear_recovery_pending:
            await scheduler.schedule_interval(
                schedule_id="persona-reflection", target_type=ScheduledTargetType.PERSONA_REFLECTION,
                target_key="persona-reflection", seconds=900, target_payload={},
                metadata={"owner_kind": "system"},
            )

    async def _allow_event(self, event: dict, persona_id: str) -> bool:
        if event["source"] != "chat":
            return event.get("author_type") != "assistant"
        store = require_initialized(self._context.chat.store, "chat store")
        turn = await store.get_turn(event.get("turn_id") or "")
        if turn is None or turn.status != "completed" or turn.user_id != event["user_id"]:
            return False
        message = await store.get_message(event.get("source_item_id") or "")
        return bool(message and message.persona_id == persona_id
                    and message.user_id == event["user_id"] and message.is_visible
                    and not message.replaced_by_message_id)

    async def _run(self, context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        manager = self._context.agent_runtime.task_agent_manager
        if manager and any(instance.get("busy") for instance in manager.get_stats()["instances"].values()):
            return ScheduledExecutionResult(success=True, message="foreground_busy")
        identity = await self._personas.get_active_id()
        if not identity:
            return ScheduledExecutionResult(success=True, message="no_active_persona")
        result = await self._service.reflect(str(CANONICAL_LOCAL_USER), identity)
        return ScheduledExecutionResult(success=True, message=result)

    async def shutdown(self) -> None:
        bind_persona_journal_service(None)
