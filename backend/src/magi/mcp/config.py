from __future__ import annotations
import re
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, field_validator

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

class ServerSection(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    autostart: bool = False

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("server.id must match [a-z0-9][a-z0-9_-]{0,63}")
        return v

class StdioTransport(BaseModel):
    kind: Literal["stdio"] = "stdio"
    command: str = Field(..., min_length=1)
    args: list[str] = Field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = Field(default_factory=dict)

class HttpTransport(BaseModel):
    kind: Literal["http"] = "http"
    url: str = Field(..., min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)

Transport = Annotated[
    Union[StdioTransport, HttpTransport],
    Field(discriminator="kind"),
]

class RuntimeSection(BaseModel):
    call_timeout_ms: int = 60_000
    init_timeout_ms: int = 15_000
    max_restart_attempts: int = 5

class ToolOverride(BaseModel):
    dangerous: bool | None = None
    risk: Literal["low", "medium", "high", "destructive"] | None = None

class MCPServerConfig(BaseModel):
    server: ServerSection
    transport: Transport
    runtime: RuntimeSection = Field(default_factory=RuntimeSection)
    tool_overrides: dict[str, ToolOverride] = Field(default_factory=dict)
