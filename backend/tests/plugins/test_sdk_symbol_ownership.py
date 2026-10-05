from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("host_module", "host_name", "sdk_module", "sdk_name"),
    [
        ("magi.channels", "Channel", "magi_plugin_sdk.channels", "Channel"),
        ("magi.channels", "ChannelConfig", "magi_plugin_sdk.channels", "ChannelConfig"),
        (
            "magi.channels",
            "ChannelAttachmentStoreProtocol",
            "magi_plugin_sdk.channels",
            "ChannelAttachmentStoreProtocol",
        ),
        (
            "magi.channels",
            "ChannelCursorClearProof",
            "magi_plugin_sdk.channels",
            "ChannelCursorClearProof",
        ),
        (
            "magi.channels",
            "ChannelInboundClearRequest",
            "magi_plugin_sdk.channels",
            "ChannelInboundClearRequest",
        ),
        (
            "magi.channels",
            "ChannelInboundClearStrategy",
            "magi_plugin_sdk.channels",
            "ChannelInboundClearStrategy",
        ),
        (
            "magi.channels",
            "ChannelInboundContext",
            "magi_plugin_sdk.channels",
            "ChannelInboundContext",
        ),
        (
            "magi.channels",
            "ChannelInboundRejectedError",
            "magi_plugin_sdk.channels",
            "ChannelInboundRejectedError",
        ),
        (
            "magi.channels",
            "ChannelInboundRejectionReason",
            "magi_plugin_sdk.channels",
            "ChannelInboundRejectionReason",
        ),
        (
            "magi.channels",
            "ChannelMessageDispatcherProtocol",
            "magi_plugin_sdk.channels",
            "ChannelMessageDispatcherProtocol",
        ),
        (
            "magi.channels",
            "ChannelMessageDispatchOutcome",
            "magi_plugin_sdk.channels",
            "ChannelMessageDispatchOutcome",
        ),
        (
            "magi.channels",
            "ChannelProviderTimeEvidence",
            "magi_plugin_sdk.channels",
            "ChannelProviderTimeEvidence",
        ),
        (
            "magi.channels.contracts",
            "ChannelMessageDispatcherProtocol",
            "magi_plugin_sdk.channels",
            "ChannelMessageDispatcherProtocol",
        ),
        (
            "magi.channels.contracts",
            "ChannelMessageDispatchOutcome",
            "magi_plugin_sdk.channels",
            "ChannelMessageDispatchOutcome",
        ),
        (
            "magi.channels",
            "ChannelSessionMapperProtocol",
            "magi_plugin_sdk.channels",
            "ChannelSessionMapperProtocol",
        ),
        (
            "magi.channels",
            "ChannelSessionMapping",
            "magi_plugin_sdk.channels",
            "ChannelSessionMapping",
        ),
        ("magi.channels", "ChannelTarget", "magi_plugin_sdk.channels", "ChannelTarget"),
        ("magi.channels", "InboundMessage", "magi_plugin_sdk.channels", "InboundMessage"),
        ("magi.channels", "OutboundContent", "magi_plugin_sdk.channels", "OutboundContent"),
        (
            "magi.channels",
            "ChannelControlCommandResult",
            "magi_plugin_sdk.channels",
            "ChannelControlCommandResult",
        ),
        (
            "magi.channels",
            "ChannelControlPortProtocol",
            "magi_plugin_sdk.channels",
            "ChannelControlPortProtocol",
        ),
        (
            "magi.channels.contracts",
            "ChannelControlPortProtocol",
            "magi_plugin_sdk.channels",
            "ChannelControlPortProtocol",
        ),
        ("magi.awareness", "ContentBlock", "magi_plugin_sdk.sources", "ContentBlock"),
        ("magi.awareness", "L2BatchPolicy", "magi_plugin_sdk.sources", "L2BatchPolicy"),
        ("magi.awareness", "PluginRuntimePaths", "magi_plugin_sdk.sources", "PluginRuntimePaths"),
        ("magi.awareness", "Source", "magi_plugin_sdk.sources", "Source"),
        ("magi.awareness", "SourceMemoryPolicy", "magi_plugin_sdk.sources", "SourceMemoryPolicy"),
        ("magi.awareness", "SourceOutput", "magi_plugin_sdk.sources", "SourceOutput"),
        (
            "magi.awareness",
            "SourceOutputMetadata",
            "magi_plugin_sdk.sources",
            "SourceOutputMetadata",
        ),
        ("magi.awareness", "SourceSyncContext", "magi_plugin_sdk.sources", "SourceSyncContext"),
        ("magi.awareness", "SourceChangeBatch", "magi_plugin_sdk.runtime", "SourceChangeBatch"),
        (
            "magi.events.plugin_ingress",
            "PluginIngressEventHandler",
            "magi_plugin_sdk.ingress",
            "PluginIngressEventHandler",
        ),
        (
            "magi.events.plugin_ingress",
            "PluginIngressEventRecord",
            "magi_plugin_sdk.ingress",
            "PluginIngressEventRecord",
        ),
        (
            "magi.events.plugin_ingress",
            "PluginIngressHandlerRegistration",
            "magi_plugin_sdk.ingress",
            "PluginIngressHandlerRegistration",
        ),
        ("magi_plugin_sdk", "get_logger", "magi_plugin_sdk.logging", "get_logger"),
        (
            "magi_plugin_sdk",
            "configure_basic_logging",
            "magi_plugin_sdk.logging",
            "configure_basic_logging",
        ),
        ("magi.plugins", "get_logger", "magi_plugin_sdk.logging", "get_logger"),
        (
            "magi.plugins",
            "configure_basic_logging",
            "magi_plugin_sdk.logging",
            "configure_basic_logging",
        ),
        ("magi.tools", "Tool", "magi_plugin_sdk.tools", "Tool"),
        ("magi.tools", "ToolSchema", "magi_plugin_sdk.tools", "ToolSchema"),
        ("magi.tools", "ToolResult", "magi_plugin_sdk.tools", "ToolResult"),
        ("magi.tools.schema", "MultiProviderTool", "magi_plugin_sdk.tools", "MultiProviderTool"),
    ],
)
def test_backend_and_sdk_exports_have_one_symbol_owner(
    host_module, host_name, sdk_module, sdk_name
):
    assert getattr(import_module(host_module), host_name) is getattr(
        import_module(sdk_module), sdk_name
    )


def test_host_tool_context_extends_sdk_context():
    from magi.tools import ToolExecutionContext as HostContext
    from magi_plugin_sdk.tools import ToolExecutionContext as SdkContext

    assert HostContext is not SdkContext
    assert issubclass(HostContext, SdkContext)
