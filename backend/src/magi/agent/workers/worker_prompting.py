"""Prompt and capability helpers for child agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from ...config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from ...i18n import llm_language_label
from .child_preset import (
    ChildRunPreset,
    parse_child_preset,
    resolve_child_tools,
)


class _WorkerPromptHostProtocol(Protocol):
    _tool_registry: Any


@dataclass(frozen=True, slots=True)
class WorkerPromptLayers:
    """Stable and run-local prompt layers for one bounded child run."""

    system_prompt: str
    working_context: str


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

    def _build_worker_prompt_layers(
        self,
        worker_id: str,
        preset: str,
        description: str,
        selected_tools: list[str],
    ) -> WorkerPromptLayers:
        resolved_preset = parse_child_preset(preset)
        if resolved_preset is None:
            raise ValueError(f"Unsupported child preset: {preset}")
        base_rules = (
            "You are a bounded child agent and leaf executor. Stay inside the "
            "assigned objective and return "
            "only the requested structured JSON result. Do not create child agents "
            "or modify the parent run plan."
        )
        language_rules = (
            f"Response language: {llm_language_label()}. Write natural-language JSON "
            "values in this language unless preserving exact identifiers or sources."
        )
        system_prompt = "\n".join(
            (
                base_rules,
                self._build_preset_rules(resolved_preset),
                language_rules,
                "Use only capabilities exposed by the runtime. If no tool is exposed, "
                "reason directly from the supplied context.",
                SYSTEM_PROMPT_CACHE_BOUNDARY,
            )
        )
        selected_capabilities = ", ".join(selected_tools) if selected_tools else "none"
        working_context = "\n".join(
            (
                "# Child Run Assignment",
                f"* Worker ID: {worker_id}",
                f"* Task Summary: {description}",
                f"* Exposed Capabilities: {selected_capabilities}",
                "* Prefer paths under the Runtime World State working directory unless "
                "the objective explicitly requires another location.",
                "* Use current_time when exact wall-clock time matters.",
            )
        )
        return WorkerPromptLayers(
            system_prompt=system_prompt,
            working_context=working_context,
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

__all__ = ["WorkerPromptLayers", "WorkerPromptMixin"]
