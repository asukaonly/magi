"""Speech model and voice preferences; credentials remain provider-owned."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TTSSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["local", "remote"] = "local"
    provider_id: str | None = None
    local_model: Literal["kokoro-multi-lang-v1_0", "vits-melo-tts-zh_en"] = "kokoro-multi-lang-v1_0"
    local_voice: str = "zf_xiaobei"
    local_speed: float = Field(default=1, ge=0.5, le=2)
    remote_model: str = Field(default="", max_length=200)
    remote_voice: str = Field(default="", max_length=200)
    remote_speed: float = Field(default=1, ge=0.25, le=4)
    instructions: str = Field(default="", max_length=2000)
    emotion: str = Field(default="", max_length=30)
