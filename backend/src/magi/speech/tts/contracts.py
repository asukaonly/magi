"""Production TTS request and response contracts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from magi.config.tts import TTSSettings


class TextSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text"]
    text: str = Field(min_length=1, max_length=4096)


class MessageSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["message"]
    session_id: str = Field(min_length=1, max_length=200)
    message_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    source: Annotated[TextSource | MessageSource, Field(discriminator="kind")]


class SynthesisJob(BaseModel):
    job_id: str
    request_id: str
    state: Literal["ready", "running", "completed", "cancelling", "cancelled", "failed", "unknown"]
    engine: str
    model: str
    voice: str
    speed: float
    content_hash: str
    cleaner_version: str = "1"
    total_segments: int
    ready_segments: int = 0
    expires_at: float
    error: str | None = None


class VoiceInfo(BaseModel):
    id: str
    language: str


class TTSModelStatus(BaseModel):
    model_id: str = "kokoro-multi-lang-v1_0"
    state: Literal["missing", "downloading", "ready", "failed", "cancelled"] = "missing"
    progress: float = 0
    error: str | None = None
    runtime_available: bool = False
    recommended: bool = False


class TTSConfiguration(BaseModel):
    settings: TTSSettings
    revision: str
    voices: list[VoiceInfo]
    local_voices: list[VoiceInfo]
    model: TTSModelStatus


class TTSConfigurationUpdate(BaseModel):
    settings: TTSSettings
    revision: str
