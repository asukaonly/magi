"""Public contracts for explicit, previewed entity identity decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..entity_types import EXTRACTABLE_ENTITY_TYPES


class EntityChangeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["type_correction", "merge"]
    entity_id: str = Field(min_length=1, max_length=512)
    target_entity_id: str | None = Field(default=None, min_length=1, max_length=512)
    new_type: str | None = None
    review_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_operation(self) -> EntityChangeCommand:
        if self.kind == "type_correction":
            if self.new_type not in EXTRACTABLE_ENTITY_TYPES or self.target_entity_id is not None:
                raise ValueError(
                    "Type correction requires a registered extractable type and no merge target"
                )
        elif (
            not self.target_entity_id
            or self.target_entity_id == self.entity_id
            or self.new_type
            or self.review_id
        ):
            raise ValueError("Merge requires two distinct identities and no type correction")
        return self


class EntityChangeApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: EntityChangeCommand
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=1, max_length=128)


class IdentityEntity(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str


class EntityChangeImpact(BaseModel):
    relationships: int
    assertions: int
    mentions: int
    claims: int
    corrections: int
    source_bindings: int
    affected_subjects: int


class EntityChangePreview(BaseModel):
    command: EntityChangeCommand
    entity: IdentityEntity
    target: IdentityEntity | None = None
    fingerprint: str
    impact: EntityChangeImpact
    correction_history_may_block_revert: bool


class EntityChangeResult(BaseModel):
    operation_id: str
    kind: Literal["type_correction", "merge"]
    entity_id: str
    current_type: str
    impact: EntityChangeImpact
    derivation_state: Literal["pending"] = "pending"


class EntityTypeReview(BaseModel):
    review_id: str
    entity: IdentityEntity
    proposed_type: str
    evidence_event_ids: list[str]
    version: int


class EntityTypeReviewList(BaseModel):
    items: list[EntityTypeReview]
    total: int


class EntityReviewRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class EntityReviewRejectResult(BaseModel):
    review_id: str
    status: Literal["rejected"] = "rejected"


class EntityIdentityAuditGroup(BaseModel):
    name: str
    entities: list[IdentityEntity]


class EntityIdentityAudit(BaseModel):
    groups: list[EntityIdentityAuditGroup]
    total: int
