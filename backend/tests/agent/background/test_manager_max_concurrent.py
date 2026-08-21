from magi.agent.background.manager import BackgroundTaskManager
from magi.config.models import BackgroundTasksSettings


def test_manager_exposes_max_concurrent():
    # __init__ only stores store/run_fn; constructing with stubs is safe.
    mgr = BackgroundTaskManager(store=object(), run_fn=lambda *a, **k: None, max_concurrent=5)
    assert mgr.max_concurrent == 5


def test_background_tasks_default_concurrency_is_2():
    assert BackgroundTasksSettings().max_concurrent == 2
