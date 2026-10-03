"""Speech input configuration, independent of conversational model selection."""

from typing import Literal
from pydantic import BaseModel, Field

from .tts import TTSSettings


class ASRSettings(BaseModel):
    enabled: bool = False
    mode: Literal["local", "remote"] = "local"
    local_model_id: str = "paraformer-zh-en-int8"
    provider_id: str = ""
    language: Literal["auto", "zh", "en"] = "auto"


class SpeechSettings(BaseModel):
    tts: TTSSettings = Field(default_factory=TTSSettings)
    asr: ASRSettings = Field(default_factory=ASRSettings)
