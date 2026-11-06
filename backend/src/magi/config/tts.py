"""Speech model and voice preferences; credentials remain provider-owned."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LocalTTSModel = Literal[
    "voxcpm2-8bit", "moss-tts-nano", "qwen3-tts-customvoice-8bit",
    "moss-tts-local-1.5-4bit", "kokoro-multi-lang-v1_0", "vits-melo-tts-zh_en",
]


class TTSVoicePreset(BaseModel):
    """A named, model-specific voice recipe; never a portable speaker identity."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=80)
    model_id: LocalTTSModel
    voice: str = Field(default="", max_length=200)
    speed: float = Field(default=1, ge=0.5, le=2)
    description: str = Field(default="", max_length=500)
    reference_audio: str = Field(default="", pattern=r"^([a-f0-9]{64})?$")
    seed: int = Field(default=42, ge=0, le=2147483647)


class TTSSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["local", "remote"] = "local"
    provider_id: str | None = None
    local_model: LocalTTSModel = "voxcpm2-8bit"
    local_voice: str = Field(default="", max_length=200)
    local_speed: float = Field(default=1, ge=0.5, le=2)
    local_model_path: str = Field(default="", max_length=4096)
    local_codec_path: str = Field(default="", max_length=4096)
    voice_description: str = Field(default="", max_length=500)
    reference_audio: str = Field(default="", pattern=r"^([a-f0-9]{64})?$")
    voice_seed: int = Field(default=42, ge=0, le=2147483647)
    voice_presets: list[TTSVoicePreset] = Field(default_factory=list, max_length=32)
    remote_model: str = Field(default="", max_length=200)
    remote_voice: str = Field(default="", max_length=200)
    remote_speed: float = Field(default=1, ge=0.25, le=4)
    instructions: str = Field(default="", max_length=2000)
    emotion: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def unique_presets(self) -> "TTSSettings":
        if len({preset.id for preset in self.voice_presets}) != len(self.voice_presets):
            raise ValueError("Voice preset IDs must be unique")
        return self
