"""Settings loader for code_agent.

User-level: ``~/.magi/code_agent.toml``.
Project-level override: ``<workspace>/.magi/code_agent.toml``.
Project values override user values (deep merge).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ._user_paths import code_agent_settings_path


DefaultAdapterName = Literal["auto", "claude_code", "codex"]


def _load_toml(text: str) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib
        return tomllib.loads(text)
    import tomli
    return tomli.loads(text)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class ClaudeCodeSettings(_Frozen):
    binary_path: str = ""
    default_model: str = ""
    extra_args: list[str] = Field(default_factory=list)
    max_budget_usd: float = 5.0
    allowed_tools: str = (
        "Read Edit Write Grep Glob Bash(git diff*) Bash(git status*) Bash(pytest*)"
    )
    disallowed_tools: str = "Bash(git push*) Bash(git commit*) Bash(rm*)"


class CodexSettings(_Frozen):
    binary_path: str = ""
    default_model: str = ""
    extra_args: list[str] = Field(default_factory=list)
    sandbox: str = "workspace-write"
    ask_for_approval: str = "never"


class ConstraintsSettings(_Frozen):
    forbid_paths: list[str] = Field(
        default_factory=lambda: [".env", ".env.*", "secrets/", "*.pem", "id_rsa*"]
    )
    forbid_git_commit: bool = True
    forbid_git_push: bool = True
    default_timeout_s: int = 600


class CodeAgentSettings(_Frozen):
    enabled: bool = True
    default_adapter: DefaultAdapterName = "auto"
    claude_code: ClaudeCodeSettings = Field(default_factory=ClaudeCodeSettings)
    codex: CodexSettings = Field(default_factory=CodexSettings)
    constraints: ConstraintsSettings = Field(default_factory=ConstraintsSettings)
    auto_apply: bool = False  # Automatically apply delegation changes without manual confirmation


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_optional_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _load_toml(path.read_text(encoding="utf-8"))


def load_settings(*, workspace_root: Path | str | None = None) -> CodeAgentSettings:
    user_data = _read_optional_toml(code_agent_settings_path())
    project_data: dict[str, Any] = {}
    if workspace_root is not None:
        ws = Path(workspace_root)
        project_data = _read_optional_toml(ws / ".magi" / "code_agent.toml")
    merged = _deep_merge(user_data, project_data)

    raw_default = str(merged.get("default_adapter", "")).strip()
    if raw_default not in ("auto", "claude_code", "codex"):
        merged["default_adapter"] = "auto"

    return CodeAgentSettings.model_validate(merged)


__all__ = [
    "CodeAgentSettings",
    "ClaudeCodeSettings",
    "CodexSettings",
    "ConstraintsSettings",
    "DefaultAdapterName",
    "load_settings",
]
