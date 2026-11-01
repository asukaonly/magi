"""Device observations are versioned data capabilities, not remote plugin execution."""

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from jsonschema import Draft202012Validator, SchemaError
from magi_plugin_sdk.runtime import ResourceRef, SourceChange
from pydantic import Field, JsonValue, model_validator

from .client_models import ClientModel

CapabilityKey = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
SchemaVersion = Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)]


class CapabilityIdentity(ClientModel):
    capability_id: CapabilityKey
    protocol: Literal["source.change.v1"]
    schema_id: CapabilityKey
    schema_version: SchemaVersion

    def identity(self) -> "CapabilityIdentity":
        return CapabilityIdentity(**{key: getattr(self, key) for key in CapabilityIdentity.model_fields})


class CollectorClaim(CapabilityIdentity):
    connection_epoch: UUID


class CollectionCapability(CapabilityIdentity):
    direction: Literal["observe"] = "observe"
    supports_resources: Literal[False] = False
    payload_schema: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_schema(self) -> "CollectionCapability":
        if len(json.dumps(self.payload_schema).encode()) > 65536:
            raise ValueError("Observation schema exceeds size limit")

        def check_refs(value: JsonValue) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"$ref", "$dynamicRef"} and (not isinstance(child, str) or not child.startswith("#")):
                        raise ValueError("Observation schemas must not resolve external references")
                    check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)

        check_refs(self.payload_schema)
        try:
            Draft202012Validator.check_schema(self.payload_schema)
        except SchemaError as exc:
            raise ValueError("Invalid observation JSON schema") from exc
        return self

class CollectorScope(ClientModel):
    connection_id: str
    connection_epoch: UUID
    source_type: CapabilityKey
    capability: CollectionCapability
    claimed_by: str | None


class ObservationChange(SourceChange):
    resources: list[ResourceRef] = Field(default_factory=list, max_length=0)


class SourceObservation(CapabilityIdentity):
    kind: Literal["source_observation"]
    connection_id: Annotated[str, Field(pattern=r"^conn_[0-9a-f]{32}$")]
    connection_epoch: UUID
    source_type: CapabilityKey
    change: ObservationChange


def collection_capability(metadata: dict[str, Any]) -> CollectionCapability | None:
    """An absent declaration means the source cannot accept device observations."""
    value = metadata.get("remote_collection")
    return None if value is None else CollectionCapability.model_validate(value)


def validate_observation(capability: CollectionCapability, identity: CapabilityIdentity, change: SourceChange) -> None:
    if capability.identity() != identity or change.resources:
        raise ValueError("Observation capability or schema does not match")
    if change.operation == "upsert":
        Draft202012Validator(capability.payload_schema).validate(change.payload)
