from magi.tools import Tool as BackendTool
from magi.tools import ToolExecutionContext as BackendToolExecutionContext
from magi.tools import ToolResult as BackendToolResult
from magi.tools import ToolSchema as BackendToolSchema
from magi.tools.schema import MultiProviderTool as BackendMultiProviderTool
from magi_plugin_sdk.tools import MultiProviderTool as SdkMultiProviderTool
from magi_plugin_sdk.tools import Tool as SdkTool
from magi_plugin_sdk.tools import ToolExecutionContext as SdkToolExecutionContext
from magi_plugin_sdk.tools import ToolResult as SdkToolResult
from magi_plugin_sdk.tools import ToolSchema as SdkToolSchema


def test_backend_tool_contracts_reexport_sdk_symbols() -> None:
    assert BackendTool is SdkTool
    assert BackendToolSchema is SdkToolSchema
    assert BackendToolExecutionContext is SdkToolExecutionContext
    assert BackendToolResult is SdkToolResult
    assert BackendMultiProviderTool is SdkMultiProviderTool