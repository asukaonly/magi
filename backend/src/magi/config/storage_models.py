"""Server-startup selection of structured persistence implementations."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator
from ..db.mysql import MysqlSettings


class StructuredStorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: Literal["sqlite", "mysql"] = "sqlite"
    memory_events: Literal["sqlite", "mysql"] = "sqlite"
    chat: Literal["sqlite", "mysql"] = "sqlite"
    mysql: MysqlSettings | None = None

    @model_validator(mode="after")
    def validate_mysql_binding(self) -> "StructuredStorageSettings":
        if "mysql" in {self.channels, self.memory_events, self.chat} and self.mysql is None:
            raise ValueError(
                "MySQL connection settings are required for external structured storage"
            )
        return self
