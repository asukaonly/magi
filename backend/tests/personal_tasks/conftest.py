import pytest

from magi.personal_tasks.service import PersonalTaskService, bind_personal_task_service
from magi.personal_tasks.store import PersonalTaskStore


@pytest.fixture
def personal_service(tmp_path, ensure_db_schema):
    path = tmp_path / "personal.db"
    ensure_db_schema("personal_tasks", path)
    service = PersonalTaskService(PersonalTaskStore(str(path)))
    bind_personal_task_service(service)
    yield service
    bind_personal_task_service(None)
