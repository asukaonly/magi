"""Pydantic schemas for the personality configuration API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ...config.models import LLMSettings


class BasicProfileModel(BaseModel):
    name: str = Field(default="AI Assistant")
    age: str = Field(default="Unknown")
    gender: str = Field(default="Unknown")
    description: str = Field(default="")
    avatar: str = Field(default="")
    occupation: str = Field(default="Assistant")


class CoreIdentityModel(BaseModel):
    inner_narrative: str = Field(default="")
    language_fingerprint: str = Field(default="")
    attention_bias: str = Field(default="")


class PersonaEntityModel(BaseModel):
    basic_profile: BasicProfileModel = Field(default_factory=BasicProfileModel)
    core_identity: CoreIdentityModel = Field(default_factory=CoreIdentityModel)


class StateTransitionProtocolItemModel(BaseModel):
    trigger_type: str = Field(default="")
    trigger_condition: str = Field(default="")
    target_state_name: str = Field(default="")
    behavior_shift: str = Field(default="")


class BootstrapConfigModel(BaseModel):
    style_instruction: str = Field(default="")
    opening_line: str = Field(default="")
    max_rounds: int = Field(default=3)


class PersonalityConfigModel(BaseModel):
    persona_entity: PersonaEntityModel = Field(default_factory=PersonaEntityModel)
    appearance_prompt: str = Field(default="")
    state_transition_protocol: List[StateTransitionProtocolItemModel] = Field(default_factory=list)
    bootstrap: Optional[BootstrapConfigModel] = Field(default=None)


class AIGenerateRequest(BaseModel):
    description: str = Field(..., description="One-sentence description of AI personality")
    target_language: str = Field(default="Auto", description="Target language: Auto/Chinese/English etc.")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="Current configuration (optional)")
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")


class PersonalityResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class BootstrapInitRequest(BaseModel):
    session_id: str = Field(..., description="Chat session to inject the opening into")
    user_id: str = Field(default="default_user")


class JournalReflectRequest(BaseModel):
    persona_name: Optional[str] = Field(None, description="Persona to reflect as; defaults to current")
    emotional_state: Optional[Dict[str, Any]] = None
    relationship: Optional[Dict[str, Any]] = None
    recent_milestones: Optional[List[Dict[str, Any]]] = None


class PersonalityDiff(BaseModel):
    field: str = Field(..., description="Field path")
    field_label: str = Field(..., description="Field display label")
    old_value: Any = Field(None, description="Old value")
    new_value: Any = Field(None, description="New value")


class PersonalityCompareResponse(BaseModel):
    success: bool
    message: str
    from_personality: str
    to_personality: str
    diffs: List[PersonalityDiff]
    from_config: Optional[PersonalityConfigModel] = None
    to_config: Optional[PersonalityConfigModel] = None
