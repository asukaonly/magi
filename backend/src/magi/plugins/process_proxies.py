"""Host-side SDK contribution adapters; never import external plugin modules."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any
import uuid

from magi_plugin_sdk.channels import Channel
from magi_plugin_sdk.sources import Source
from magi_plugin_sdk.tools import Tool, ToolExecutionContext, ToolResult
from magi_plugin_sdk.runtime import InvocationIdentity
from magi_plugin_sdk.worker_catalog import SOURCE_METHODS


class AsyncObjectProxy:
    def __init__(self, owner: Any, target: str, methods: set[str]) -> None:
        self.owner, self.target, self.methods = owner, target, methods

    def __getattr__(self, name: str) -> Any:
        if name not in self.methods:
            raise AttributeError(name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            return await self.owner.invoke(self.target, name, *args, **kwargs)

        return call

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if "__call__" not in self.methods:
            raise TypeError("Proxy is not callable")
        return await self.owner.invoke(self.target, "__call__", *args, **kwargs)


class SourceProxy(Source):
    def __init__(self, owner: Any, descriptor: dict[str, Any]) -> None:
        super().__init__()
        self.owner, self.target = owner, descriptor["target"]
        self._methods = set(descriptor["methods"])
        self.source_id = descriptor["id"]
        for name, value in descriptor["attributes"].items():
            setattr(self, name, value)
        self.bind_plugin_context(
            plugin_id=owner.plugin_id,
            plugin_dir=owner.manifest.plugin_dir,
            connection=owner.connection,
            context=owner.context,
        )

    async def collect_items(self, context: Any) -> Any:
        return await self.owner.invoke(self.target, "collect_items", context)

    async def discover_changes(self, *args: Any, **kwargs: Any) -> Any:
        return await self.owner.invoke(self.target, "discover_changes", *args, **kwargs)

    async def fetch_item(self, item: dict[str, Any]) -> Any:
        return await self.owner.invoke(self.target, "fetch_item", item)

    async def build_output(self, item: dict[str, Any]) -> Any:
        return await self.owner.invoke(self.target, "build_output", item)

    async def extract_metadata(self, item: dict[str, Any]) -> Any:
        return await self.owner.invoke(self.target, "extract_metadata", item)

    async def clear_user_content(self, context: Any) -> None:
        await self.owner.invoke(self.target, "clear_user_content", context)

    def source_item_identity(self, item: dict[str, Any]) -> str:
        return self.owner.invoke_sync(self.target, "source_item_identity", item)

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        return self.owner.invoke_sync(self.target, "source_item_version_fingerprint", item)

    def idempotency_key(self, output: Any) -> str | None:
        return self.owner.invoke_sync(self.target, "idempotency_key", output)

    def l2_batch_policy(self, output: Any) -> Any:
        return self.owner.invoke_sync(self.target, "l2_batch_policy", output)

    def t(self, key: str, *args: Any, **kwargs: Any) -> str:
        return self.owner.invoke_sync(self.target, "t", key, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name not in SOURCE_METHODS or name not in self._methods:
            raise AttributeError(name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            return await self.owner.invoke(self.target, name, *args, **kwargs)

        return call


def tool_proxy_type(owner: Any, descriptor: dict[str, Any]) -> type[Tool]:
    class ProcessTool(Tool):
        def _init_schema(self) -> None:
            self.schema = descriptor["schema"].model_copy(deep=True)

        def _identity(self, context: ToolExecutionContext) -> InvocationIdentity:
            if context.invocation is not None:
                return context.invocation
            return InvocationIdentity(
                invocation_id=uuid.uuid4().hex,
                plugin_id=owner.plugin_id,
                connection_id=owner.connection.connection_id,
                principal_id=context.agent_id,
                task_id=context.task_id,
                trigger="model",
            )

        async def execute(
            self, parameters: dict[str, Any], context: ToolExecutionContext
        ) -> ToolResult:
            return await owner.invoke(
                descriptor["target"],
                "execute",
                parameters,
                context,
                identity=self._identity(context),
            )

        async def validate_parameters(self, parameters: dict[str, Any]) -> Any:
            return await owner.invoke(descriptor["target"], "validate_parameters", parameters)

        async def before_execution(
            self, parameters: dict[str, Any], context: ToolExecutionContext
        ) -> Any:
            return await owner.invoke(
                descriptor["target"],
                "before_execution",
                parameters,
                context,
                identity=self._identity(context),
            )

        async def after_execution(
            self, result: ToolResult, context: ToolExecutionContext
        ) -> ToolResult:
            return await owner.invoke(
                descriptor["target"],
                "after_execution",
                result,
                context,
                identity=self._identity(context),
            )

        async def clear_user_content(self) -> None:
            await owner.invoke(descriptor["target"], "clear_user_content")

    ProcessTool.__name__ = "ProcessTool_" + descriptor["schema"].name
    return ProcessTool


class ChannelProxy(Channel):
    def __init__(self, owner: Any, descriptor: dict[str, Any]) -> None:
        self.owner, self.descriptor = owner, descriptor
        for name, value in descriptor.items():
            if name != "channel_type":
                setattr(self, name, value)

    @property
    def channel_type(self) -> str:
        return f"{self.owner.connection.connection_id}:{self.descriptor['channel_type']}"

    def _worker_value(self, value: Any, field: str = "channel_type") -> Any:
        if getattr(value, field) != self.channel_type:
            raise PermissionError("Outbound channel value belongs to another connection")
        return replace(value, **{field: self.descriptor["channel_type"]})

    async def start(self) -> None:
        await self.owner.start_channel()

    async def stop(self) -> None:
        self.owner._channel_active = False
        await self.owner.invoke("channel", "stop")

    async def send_message(self, target: Any, content: Any) -> None:
        await self.owner.invoke("channel", "send_message", self._worker_value(target), content)

    async def send_typing_indicator(self, target: Any) -> None:
        await self.owner.invoke("channel", "send_typing_indicator", self._worker_value(target))

    async def deliver(self, target: Any, content: Any) -> Any:
        receipt = await self.owner.invoke("channel", "deliver", self._worker_value(target), content)
        return replace(receipt, channel_id=self.channel_type)

    async def deliver_chunk(self, target: Any, chunk: Any) -> None:
        await self.owner.invoke("channel", "deliver_chunk", self._worker_value(target), chunk)

    async def revise(self, receipt: Any, new_content: Any) -> Any:
        result = await self.owner.invoke(
            "channel", "revise", self._worker_value(receipt, "channel_id"), new_content
        )
        return replace(result, channel_id=self.channel_type)

    async def retract(self, receipt: Any) -> None:
        await self.owner.invoke("channel", "retract", self._worker_value(receipt, "channel_id"))

    async def deliver_control_request(self, target: Any, request: Any) -> None:
        await self.owner.invoke(
            "channel", "deliver_control_request", self._worker_value(target), request
        )

    def bind_session_mapper(self, session_mapper: Any) -> None:
        self.owner.bind_channel_port("session_mapper", session_mapper)

    def bind_message_dispatcher(self, dispatcher: Any) -> None:
        self.owner.bind_channel_port("message_dispatcher", dispatcher)

    def bind_attachment_store(self, attachment_store: Any) -> None:
        self.owner.bind_channel_port("attachment_store", attachment_store)

    def bind_control_port(self, control_port: Any) -> None:
        self.owner.bind_channel_port("control_port", control_port)

    @asynccontextmanager
    async def inbound_clear_boundary(self, request: Any) -> Any:
        boundary_id = uuid.uuid4().hex
        await self.owner.request(
            "channel_boundary",
            {"enter": True, "boundary_id": boundary_id, "request": self._worker_value(request)},
        )
        try:
            yield
        finally:
            await self.owner.request(
                "channel_boundary", {"enter": False, "boundary_id": boundary_id}
            )


class IngressProxy:
    def __init__(self, owner: Any, target: str) -> None:
        self.owner, self.target = owner, target

    async def handle_event(self, event: Any, payload: dict[str, Any]) -> None:
        from magi_plugin_sdk.worker_values import WorkerIngressRecord

        record = WorkerIngressRecord(
            **{name: getattr(event, name) for name in WorkerIngressRecord.__dataclass_fields__}
        )
        await self.owner.invoke(self.target, "handle_event", record, payload)


class WebSearchProviderProxy:
    def __init__(self, owner: Any, descriptor: dict[str, Any]) -> None:
        self.owner, self.descriptor = owner, descriptor
        self.name = descriptor["id"]
        self.display_name = descriptor["display_name"]

    def is_ready(self, config: Any) -> bool:
        return self.descriptor["ready"] and self.owner.diagnostics["healthy"]

    async def execute(self, parameters: dict[str, Any], config: Any) -> dict[str, Any]:
        value = config.model_dump(mode="json") if hasattr(config, "model_dump") else dict(config)
        return await self.owner.invoke(self.descriptor["target"], "execute", parameters, value)


class ProtocolProviderProxy:
    def __init__(self, owner: Any, descriptor: dict[str, Any]) -> None:
        self.owner, self.descriptor = owner, descriptor

    async def invoke(self, request: Any) -> Any:
        return await self.owner.invoke(
            self.descriptor["target"], "invoke", request, identity=request.identity
        )

    def stream(self, request: Any) -> Any:
        timeout = getattr(request, "timeout_seconds", None)
        return self.owner.iter_stream(
            self.descriptor["target"], request, identity=request.identity, timeout=timeout
        )
