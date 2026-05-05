"""Verifies the public recorder surface used by RuntimeTraceSubscriber."""
import inspect
from magi.runtime_trace import recorder


def test_recorder_module_exports():
    for name in (
        "record_tool_invocation",
        "record_task_started",
        "record_task_completed",
        "record_task_failed",
    ):
        assert hasattr(recorder, name), f"recorder missing {name}"
        fn = getattr(recorder, name)
        assert inspect.iscoroutinefunction(fn), f"{name} must be async"
        sig = inspect.signature(fn)
        assert "correlation_id" in sig.parameters, f"{name} missing correlation_id kwarg"
