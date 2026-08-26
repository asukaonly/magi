"""Prompt and capability helpers for child agent runs."""

from __future__ import annotations

import os
import platform
from datetime import datetime
from typing import Any, Optional, Protocol, cast

from ...i18n import llm_language_label
from ...utils.calendar_timezone import local_calendar_timezone_id
from ...utils.runtime import get_default_chat_workspace_path
from .child_preset import (
    ChildRunPreset,
    parse_child_preset,
    resolve_child_tools,
)


class _WorkerPromptHostProtocol(Protocol):
    _tool_registry: Any


class WorkerPromptMixin:
    """Build child prompts and resolve preset capability scopes."""

    def _normalize_preset(self, value: str) -> str:
        preset = parse_child_preset(value)
        return preset.value if preset is not None else ""

    def _resolve_tools_for_preset(self, value: str) -> list[str]:
        host = cast(_WorkerPromptHostProtocol, self)
        preset = parse_child_preset(value)
        if preset is None:
            return []
        return resolve_child_tools(host._tool_registry, preset)

    def _build_worker_system_prompt(
        self,
        worker_id: str,
        preset: str,
        description: str,
        selected_tools: list[str],
        execution_workspace: Optional[str] = None,
    ) -> str:
        resolved_preset = parse_child_preset(preset)
        if resolved_preset is None:
            raise ValueError(f"Unsupported child preset: {preset}")
        base_rules = (
            f"You are bounded child agent {worker_id}. "
            f"Task summary: {description}. "
            "You are a leaf executor. Stay inside the given objective and return "
            "only the requested structured JSON result. Do not create child agents "
            "or modify the parent run plan."
        )
        environment_rules = self._build_worker_environment_rules(execution_workspace)
        tool_rules = (
            "Only use these tools: " + ", ".join(selected_tools)
            if selected_tools
            else "No tools are available. Reason directly from the supplied context."
        )
        language_rules = (
            f"Response language: {llm_language_label()}. Write natural-language JSON "
            "values in this language unless preserving exact identifiers or sources."
        )
        return "\n".join(
            [
                base_rules,
                environment_rules,
                self._build_preset_rules(resolved_preset),
                language_rules,
                tool_rules,
            ]
        )

    def _build_preset_rules(self, preset: ChildRunPreset) -> str:
        if preset is ChildRunPreset.WORKSPACE_WRITE:
            return self._workspace_write_rules()
        if preset is ChildRunPreset.REVIEW:
            return self._review_rules()
        return self._read_only_rules()

    @staticmethod
    def _read_only_rules() -> str:
        return (
            "Use only read-only evidence gathering. Verify concrete paths, symbols, "
            "URLs, or records before claiming them. Stop once the bounded objective has "
            "enough evidence. Return ONLY one JSON object with fields: "
            '{"result_status":"success|partial|failed","summary":"string",'
            '"findings":[{"title":"string","detail":"string"}],'
            '"evidence":[{"path":"string","detail":"string"}],'
            '"records":[{"field":"value"}],"gaps":["string"],'
            '"next_steps":["string"],"failure_reason":"string|null"}.'
        )

    @staticmethod
    def _review_rules() -> str:
        return (
            "Review the supplied implementation or evidence without modifying it. "
            "Prioritize correctness, security, lifecycle, and missing validation. "
            "Every actionable finding must identify concrete evidence. "
            + WorkerPromptMixin._read_only_rules()
        )

    @staticmethod
    def _workspace_write_rules() -> str:
        return (
            "Make only the bounded workspace change requested. Read before editing, "
            "preserve unrelated work, and verify the changed behavior. Never perform "
            "destructive or external writes. Return ONLY one JSON object with fields: "
            '{"result_status":"success|partial|failed","summary":"string",'
            '"findings":[{"title":"string","detail":"string"}],'
            '"evidence":[{"path":"string","detail":"string"}],'
            '"artifacts":[{"path":"string","operation":"created|modified|deleted"}],'
            '"verification":[{"command":"string","status":"passed|failed",'
            '"detail":"string"}],"records":[{"field":"value"}],'
            '"gaps":["string"],"next_steps":["string"],'
            '"failure_reason":"string|null"}. Success requires at least one artifact '
            "and passing verification evidence."
        )

    def _build_worker_environment_rules(self, execution_workspace: Optional[str]) -> str:
        workspace_root = self._resolve_execution_workspace(execution_workspace)
        home_dir = os.path.realpath(os.path.expanduser("~"))
        now = datetime.now().astimezone()
        return "\n".join(
            [
                "Execution environment:",
                f"- Workspace root: {workspace_root}",
                f"- Home directory: {home_dir}",
                f"- Operating system: {platform.system()} {platform.release()}",
                f"- Local date: {now.date().isoformat()}",
                f"- Timezone: {local_calendar_timezone_id() or str(now.tzinfo or 'unknown')}",
                "- Use the current_time tool when exact wall-clock time matters.",
                "- Prefer paths under the workspace root unless the objective explicitly requires another location.",
            ]
        )

    def _resolve_execution_workspace(self, execution_workspace: Optional[str]) -> str:
        raw_workspace = (
            str(execution_workspace or "").strip()
            or get_default_chat_workspace_path()
        )
        return os.path.realpath(os.path.expandvars(os.path.expanduser(raw_workspace)))


__all__ = ["WorkerPromptMixin"]
