"""Stable addresses and input provenance, independent of transport clients."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


def _identifier(value: object, name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError(f"{name} must be a non-empty identifier of at most 1024 characters")


@dataclass(frozen=True, slots=True)
class EndpointRef:
    """Address one contribution target without conflating it with a user/session."""

    connection_id: str | None
    contribution_id: str
    target_id: str
    thread_id: str | None = None
    device_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.connection_id, "connection_id", optional=True)
        _identifier(self.contribution_id, "contribution_id")
        _identifier(self.target_id, "target_id")
        _identifier(self.thread_id, "thread_id", optional=True)
        _identifier(self.device_id, "device_id", optional=True)
        if ":" in self.contribution_id or (self.connection_id and ":" in self.connection_id):
            raise ValueError("Connection and contribution identifiers cannot contain a colon")

    @property
    def registry_key(self) -> str:
        return f"{self.connection_id}:{self.contribution_id}" if self.connection_id else self.contribution_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EndpointRef:
        if not isinstance(value, dict):
            raise ValueError("Endpoint must be an object")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class IngressContext:
    """Host-validated provenance captured with the admitted input."""

    kind: Literal["message", "observation", "command"]
    event_id: str
    origin: EndpointRef
    reply_to: EndpointRef | None
    channel_clear_generation: int | None = None
    data_epoch: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"message", "observation", "command"}:
            raise ValueError("Unknown ingress kind")
        _identifier(self.event_id, "event_id")
        _identifier(self.data_epoch, "data_epoch", optional=True)
        if not isinstance(self.origin, EndpointRef) or (
            self.reply_to is not None and not isinstance(self.reply_to, EndpointRef)
        ):
            raise ValueError("Ingress addresses must be endpoint references")
        generation = self.channel_clear_generation
        if generation is not None and (type(generation) is not int or generation < 0):
            raise ValueError("Channel clear generation must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> IngressContext:
        if not isinstance(value, dict):
            raise ValueError("Ingress context must be an object")
        payload = dict(value)
        payload["origin"] = EndpointRef.from_dict(payload["origin"])
        reply = payload.get("reply_to")
        payload["reply_to"] = EndpointRef.from_dict(reply) if reply is not None else None
        return cls(**payload)


__all__ = ["EndpointRef", "IngressContext"]
