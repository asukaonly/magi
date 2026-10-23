"""Initialize the personal-task owner after database migrations."""

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from .service import PersonalTaskService, bind_personal_task_service
from .store import PersonalTaskStore


class PersonalTasksModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_personal_tasks", dependencies=("runtime_database_migrations",)
        )
        self._context = context

    async def init(self) -> None:
        paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        bind_personal_task_service(
            PersonalTaskService(PersonalTaskStore(str(paths.personal_tasks_db_path)))
        )

    async def shutdown(self) -> None:
        bind_personal_task_service(None)
