"""Production TTS request and response contracts."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from magi.config.tts import TTSSettings
from magi.utils.model_download import DownloadProgress


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
    preview_settings: TTSSettings | None = None

    @model_validator(mode="after")
    def preview_is_text_only(self) -> Self:
        if self.preview_settings is not None and self.source.kind != "text":
            raise ValueError("Preview settings require a text source")
        return self

    def identity(self) -> dict:
        return self.model_dump(mode="json", exclude={"request_id"})


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
    name: str = ""


class TTSModelStatus(BaseModel):
    model_id: str = "kokoro-multi-lang-v1_0"
    state: Literal["missing", "downloading", "ready", "failed", "cancelled"] = "missing"
    download: DownloadProgress | None = None
    error: str | None = None
    runtime_available: bool = False
    recommended: bool = False


class TTSModelChoice(BaseModel):
    engine: Literal["local", "remote"]
    model_id: str
    name: str
    provider_id: str | None = None
    provider_name: str = ""
    voices: list[VoiceInfo]
    custom_voice: bool = False
    custom_model: bool = False
    speed_min: float | None = None
    speed_max: float | None = None
    instructions: bool = False
    emotions: list[str] = Field(default_factory=list)
    download_bytes: int = 0
    status: TTSModelStatus | None = None


class TTSConfiguration(BaseModel):
    settings: TTSSettings
    revision: str
    models: list[TTSModelChoice]


class TTSConfigurationUpdate(BaseModel):
    settings: TTSSettings
    revision: str
