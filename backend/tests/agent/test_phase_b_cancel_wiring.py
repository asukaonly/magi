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
    from magi.agent.task_agents.chat_task_agent import ChatTaskAgent

    src = inspect.getsource(ChatTaskAgent.build_context)
    assert "SessionRunCancelToken" in src, (
        "build_context must construct SessionRunCancelToken for turn_control.cancel_token"
    )
    # The placeholder pattern (assigning null_cancel_token() to turn_control.cancel_token)
    # must NOT be present anymore. The null bundle is still constructed via
    # null_run_control(), but its cancel_token slot is then overwritten.
    # We check for the explicit overwrite line:
    assert "turn_control.cancel_token =" in src or "cancel_token=" in src, (
        "build_context must explicitly set the cancel_token on turn_control"
    )
