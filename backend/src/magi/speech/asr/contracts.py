"""Bounded, ephemeral transcription contracts."""

from typing import Literal
from pydantic import BaseModel, Field


class ASRError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        self.code, self.status = code, status
        super().__init__(code)


class TranscriptResult(BaseModel):
    text: str = Field(max_length=16000)
    language: str | None = None
    no_speech: bool
    engine: Literal["local", "remote"]
    model: str


class ASRJob(BaseModel):
    request_id: str
    runtime_id: str
    state: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    result: TranscriptResult | None = None
    error: str | None = None
    expires_at: float


class ASRStatus(BaseModel):
    config_revision: str
    runtime_id: str
    enabled: bool
    mode: Literal["local", "remote"]
    ready: bool
    error: str | None = None
    provider_name: str | None = None
    model: str | None = None


class ASRModel(BaseModel):
    id: str
    label: str
    size_bytes: int
    license: str
    license_url: str
    source_url: str
    recommended: bool = False
    state: Literal["missing", "downloading", "ready", "failed", "cancelled"]
    progress: float = 0
    error: str | None = None


class ASRModels(BaseModel):
    models: list[ASRModel]
