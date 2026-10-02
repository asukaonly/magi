"""TTS selection; remote service parameters remain provider-owned."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TTSSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["local", "remote"] = "local"
    provider_id: str | None = None
    local_model: Literal["kokoro-multi-lang-v1_0"] = "kokoro-multi-lang-v1_0"
    local_voice: str = "zf_xiaobei"
    local_speed: float = Field(default=1, ge=0.5, le=2)
