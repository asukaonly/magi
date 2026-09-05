"""Bounded protocol codec shared by the worker and supervisor.

Only explicitly listed SDK value types cross the boundary. A peer cannot name
an import, construct an arbitrary Python class, or serialize executable objects.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
import json
import math
from pathlib import Path
import struct
from typing import Any, BinaryIO

from pydantic import BaseModel
from .worker_values import WorkerIngressRecord
from . import (
    channels,
    contracts,
    control,
    conversation,
    delivery,
    history_imports,
    runtime,
    sensors,
    tools,
    user_content,
    providers,
    hooks,
)

MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 48
MAX_ITEMS = 100_000


class ProtocolError(ValueError):
    """The peer sent an invalid or oversized protocol value."""


@dataclass(frozen=True)
class WorkerRuntimePaths:
    """Connection-private path facade; bucket names never select another owner."""

    state_dir: Path

    def plugin_cache_dir(self, plugin_id: str) -> Path:
        return self.state_dir


# Keep this list explicit. Adding an SDK class requires boundary review.
_TYPE_NAMES = {
    contracts: "PluginManifest ExtensionFieldOption ExtensionFieldSpec ActivationFirstContextSpec ActivationFlowSpec SettingsUIBlockSpec PluginSettingsActionSpec PluginSettingsActionResult PluginSettingsResourceSpec PluginSettingsResourcePayload TemporalSummaryFeatureBudget TemporalSummarySourceFeatures DerivedAssertionRuleSpec ExtractionProfileSpec SummaryProfileSpec ContributionType PluginCapability PluginPermissions LocalizedText Triggers SuggestionSurfaceSpec SuggestionSurfacesSpec SuggestionDescriptor PluginDisplayGroupSpec LocalRequirementFileExists LocalRequirementExecutableInPath LocalRequirementAppInstalled",
    sensors: "SensorSpec ContentBlock ActivityFacet SensorActivity SensorNarration TimelinePresentation SensorMemoryPolicy SensorOutput SensorOutputMetadata SensorSyncContext L2BatchPolicy",
    tools: "ParameterType ToolErrorCode ToolParameter ToolSchema ToolExecutionContext ToolResult ToolConfigSpec",
    channels: "ChannelTarget ChannelInboundClearStrategy ChannelProviderTimeEvidence ChannelCursorClearProof ChannelInboundClearRequest InboundMessage ChannelInboundRejectionReason ChannelInboundContext OutboundContent ChannelSessionMapping ChannelConfig ChannelMessageDispatchOutcome ChannelControlCommandResult",
    delivery: "DeliveryReceipt DeliveryChunk DeliveryContent",
    history_imports: "HistoryImporterSpec HistoryImportRecord HistoryImportSource HistoryImportParseResult",
    user_content: "UserContentClearRequest UserContentClearContext",
    runtime: "PluginConnection CapabilityGrant InvocationIdentity ResourceRef SourceChange SourceChangeBatch CapabilityReadiness OperationSpec OperationResult PluginHandshake ConnectionStatus",
    control: "ControlRequest",
    conversation: "ContentBlock ConversationEvent",
    providers: "ProviderUsage ProviderToolCall ModelRequest ModelResult ModelEvent ExternalAgentRequest ExternalAgentResult ExternalAgentEvent",
    hooks: "HookContext HookDecision HookEventType HookOutcome",
}
TYPES = {
    f"{module.__name__}.{name}": getattr(module, name)
    for module, names in _TYPE_NAMES.items()
    for name in names.split()
}
TYPES["WorkerRuntimePaths"] = WorkerRuntimePaths
TYPES["WorkerIngressRecord"] = WorkerIngressRecord
TYPE_IDS = {cls: name for name, cls in TYPES.items()}


def encode(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise ProtocolError("Protocol nesting limit exceeded")

    def recur(item: Any) -> Any:
        return encode(item, depth + 1)

    if isinstance(value, Enum):
        if type(value) not in TYPE_IDS:
            raise ProtocolError("Unregistered enum type")
        return {"type": TYPE_IDS[type(value)], "value": recur(value.value)}
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolError("Non-finite protocol number")
        return value
    if isinstance(value, Path):
        return {"type": "path", "value": str(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if type(value) in (list, tuple, set, frozenset):
        if len(value) > MAX_ITEMS:
            raise ProtocolError("Protocol collection limit exceeded")
        return {
            "type": "tuple" if isinstance(value, tuple) else "list",
            "value": [recur(x) for x in value],
        }
    if isinstance(value, Mapping):
        if len(value) > MAX_ITEMS or any(not isinstance(k, str) for k in value):
            raise ProtocolError("Protocol maps require bounded string keys")
        return {"type": "map", "value": {k: recur(v) for k, v in value.items()}}
    type_id = TYPE_IDS.get(type(value))
    if type_id is None:
        raise ProtocolError(f"Unregistered protocol type: {type(value).__name__}")
    if isinstance(value, BaseModel):
        values = {name: getattr(value, name) for name in type(value).model_fields}
    elif is_dataclass(value):
        values = {f.name: getattr(value, f.name) for f in fields(value)}
    else:
        raise ProtocolError("Unsupported registered protocol type")
    return {"type": type_id, "value": recur(values)}


def decode(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise ProtocolError("Protocol nesting limit exceeded")

    def recur(item: Any) -> Any:
        return decode(item, depth + 1)

    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise ProtocolError("Invalid protocol value envelope")
    name, payload = value["type"], value["value"]
    if name in ("tuple", "list"):
        if not isinstance(payload, list) or len(payload) > MAX_ITEMS:
            raise ProtocolError("Invalid protocol collection")
        result = [recur(x) for x in payload]
        return tuple(result) if name == "tuple" else result
    if name == "map":
        if not isinstance(payload, dict) or len(payload) > MAX_ITEMS:
            raise ProtocolError("Invalid protocol map")
        return {k: recur(v) for k, v in payload.items()}
    if name == "path" and isinstance(payload, str):
        return Path(payload)
    if name == "datetime" and isinstance(payload, str):
        return datetime.fromisoformat(payload)
    if name == "bytes" and isinstance(payload, str):
        return base64.b64decode(payload, validate=True)
    cls = TYPES.get(name) if isinstance(name, str) else None
    if cls is None:
        raise ProtocolError("Unregistered protocol type tag")
    fields_value = recur(payload)
    if issubclass(cls, Enum):
        return cls(fields_value)
    if not isinstance(fields_value, dict):
        raise ProtocolError("Invalid typed protocol value")
    allowed = (
        set(cls.model_fields)
        if issubclass(cls, BaseModel)
        else {f.name for f in fields(cls)}
    )
    if not set(fields_value) <= allowed:
        raise ProtocolError("Unknown fields in typed protocol value")
    if issubclass(cls, BaseModel):
        # Manifest has an authoring alias; constructors receive the canonical field.
        if cls is contracts.PluginManifest:
            fields_value["id"] = fields_value.pop("plugin_id")
        return cls.model_validate(fields_value)
    return cls(**fields_value)


def pack(message: dict[str, Any], max_bytes: int = MAX_FRAME_BYTES) -> bytes:
    try:
        payload = json.dumps(
            encode(message), ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProtocolError("Cannot encode protocol frame") from exc
    if len(payload) > max_bytes:
        raise ProtocolError("Protocol frame exceeds byte limit")
    return struct.pack("!I", len(payload)) + payload


def write_frame(stream: BinaryIO, data: bytes) -> None:
    """Handle short pipe writes without losing protocol framing."""
    remaining = memoryview(data)
    while remaining:
        written = stream.write(remaining)
        if written is None or written <= 0:
            raise EOFError("Worker transport closed during write")
        remaining = remaining[written:]
    stream.flush()


def read_frame(stream: BinaryIO, max_bytes: int = MAX_FRAME_BYTES) -> dict[str, Any]:
    def exact(size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = stream.read(size - len(chunks))
            if not chunk:
                raise EOFError("Worker transport closed")
            chunks.extend(chunk)
        return bytes(chunks)

    size = struct.unpack("!I", exact(4))[0]
    if size == 0 or size > max_bytes:
        raise ProtocolError("Protocol frame exceeds byte limit")
    try:
        value = decode(json.loads(exact(size)))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ProtocolError("Invalid protocol frame") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Protocol frame must contain a map")
    return value
