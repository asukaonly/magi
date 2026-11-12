"""Server-startup storage bindings to explicit plugin connections."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StorageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    connection_id: str | None = Field(default=None, pattern=r"^conn_[0-9a-f]{32}$")
    provider_id: str = Field(default="sqlite", pattern=r"^[a-z][a-z0-9_-]{0,63}$")

    @model_validator(mode="after")
    def explicit_external_connection(self) -> "StorageSelection":
        if self.connection_id is None and self.provider_id != "sqlite":
            raise ValueError("External storage requires an explicit plugin connection")
        return self


class StructuredStorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: StorageSelection = Field(default_factory=StorageSelection)
    memory_events: StorageSelection = Field(default_factory=StorageSelection)
    chat: StorageSelection = Field(default_factory=StorageSelection)
