"""Application cleanup preserves transactional receipts across owner failures."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from magi.chat.cleanup_plan import ChatCleanupPlan
from magi.chat.service import ChatService
from magi.core.chat_cleanup import ChatSurfaceCleanupPendingError


@pytest.mark.parametrize("failure", [False, True])
def test_cleanup_orders_committed_plan_external_cleanup_and_acknowledgement(failure):
    events = []
    plan = ChatCleanupPlan("session", "u", "s", ["m"], ["t"], whole_session=True)
    def prepare(*_):
        events.append("redaction committed")
        return plan
    def delete(*_):
        events.append("assets")
        if failure:
            raise OSError("Unavailable asset store")
    repository = SimpleNamespace(workspace_preferences=None,
        prepare_session_cleanup=prepare,
        finish_session_cleanup=Mock(side_effect=lambda _: events.append("acknowledged")))
    service = ChatService(repository=repository, runtime_paths=None,
        trace_content=SimpleNamespace(delete_session=lambda **_: events.append("traces")),
        asset_gc=SimpleNamespace(delete_message_assets=delete),
        code_gc=SimpleNamespace(delete_references=lambda _: events.append("code artifacts")),
        workspace_gc=SimpleNamespace(delete_references=lambda _: events.append("workspace artifacts")))
    if failure:
        with pytest.raises(ChatSurfaceCleanupPendingError):
            service.delete_session("u", "s")
        repository.finish_session_cleanup.assert_not_called()
        assert events == ["redaction committed", "traces", "assets"]
    else:
        service.delete_session("u", "s")
        assert events == ["redaction committed", "traces", "assets", "code artifacts", "workspace artifacts", "acknowledged"]
