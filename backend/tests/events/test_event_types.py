from magi.events.events import EventTypes


def test_new_constants_present():
    assert EventTypes.TOOL_INVOCATION_COMPLETED == "ToolInvocationCompleted"
    assert EventTypes.USER_MESSAGE_RECEIVED == "UserMessageReceived"
    assert EventTypes.ASSISTANT_RESPONSE_PRODUCED == "AssistantResponseProduced"
    assert EventTypes.SOURCE_EVENT_EMITTED == "SourceEventEmitted"


def test_legacy_constants_still_present():
    assert EventTypes.ACTION_EXECUTED == "ActionExecuted"
    assert EventTypes.TASK_STARTED == "TaskStarted"
    assert EventTypes.USER_MESSAGE == "UserMessage"


def test_span_completed_constant():
    assert EventTypes.SPAN_COMPLETED == "SpanCompleted"
