"""Phase B Task 1: verify chat_task_agent.build_context constructs a
SessionRunCancelToken on turn_control.cancel_token instead of the
null_cancel_token placeholder from Phase A."""
from __future__ import annotations

import inspect


def test_build_context_uses_session_run_cancel_token_not_null() -> None:
    """Source inspection: build_context must construct SessionRunCancelToken
    (not null_cancel_token()) for the turn's RunControl bundle. Phase A
    left this as null because Task 10 didn't wire it; Phase B Task 1 fixes
    it so external cancel calls flow through the bundle to all three
    execution paths."""
    from magi.chat.task_agent.chat_task_agent import ChatTaskAgent

    src = inspect.getsource(ChatTaskAgent.build_context)
    assert "turn_control.cancel_token = SessionRunCancelToken(" in src, (
        "build_context must overwrite turn_control.cancel_token with a "
        "SessionRunCancelToken instance, not leave it as null_cancel_token()"
    )
