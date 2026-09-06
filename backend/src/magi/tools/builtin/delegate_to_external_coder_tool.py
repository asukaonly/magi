"""delegate_to_external_coder - hand a coding task to an external CLI."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, cast

from ...core.code_agent_artifacts import CodeAgentArtifactPathError
from ..code_agent.contracts import (
    AdapterName,
    DelegateConstraints,
    DelegateRequest,
)
from ..code_agent.probe import probe_all
from ..code_agent.service import CodeAgentService
from ..code_agent.settings import CodeAgentSettings, load_settings
from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

_ADAPTER_ORDER: tuple[AdapterName, ...] = ("claude_code", "codex")
_VALID_ADAPTERS: tuple[str, ...] = ("auto", *_ADAPTER_ORDER)


@dataclass(frozen=True)
class _DelegateInput:
    prompt: str
    adapter_param: str
    session_id: str
    workspace: str


def _binary_paths_from_settings(
    settings: CodeAgentSettings,
) -> dict[AdapterName, str | None]:
    probes = probe_all(force=False)
    return {
        "claude_code": settings.claude_code.binary_path.strip()
        or probes["claude_code"].binary_path,
        "codex": settings.codex.binary_path.strip() or probes["codex"].binary_path,
    }


def _resolve_adapter(
    adapter_param: str,
    settings: CodeAgentSettings,
    binary_paths: dict[AdapterName, str | None],
) -> AdapterName:
    if adapter_param != "auto":
        return cast(AdapterName, adapter_param)
    if settings.default_adapter != "auto":
        return settings.default_adapter
    for candidate in _ADAPTER_ORDER:
        if binary_paths.get(candidate):
            return candidate
    return "claude_code"


def _delegate_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="prompt",
            type=ParameterType.STRING,
            description=(
                "Natural-language task description. Include the "
                "acceptance criterion explicitly."
            ),
            required=True,
        ),
        ToolParameter(
            name="files_hint",
            type=ParameterType.ARRAY,
            array_item_type=ParameterType.STRING,
            description=(
                "Optional: relative paths the external agent should " "look at first."
            ),
            required=False,
        ),
        ToolParameter(
            name="adapter",
            type=ParameterType.STRING,
            description=(
                "Which built-in CLI or connected external-agent provider to use. "
                "'auto' picks the configured default."
            ),
            required=False,
            default="auto",
        ),
        ToolParameter(
            name="model",
            type=ParameterType.STRING,
            description="Optional model override passed to the adapter.",
            required=False,
        ),
        ToolParameter(
            name="timeout_s",
            type=ParameterType.INTEGER,
            description="Hard timeout for the delegation (60-3600 seconds).",
            required=False,
            default=600,
            min_value=60,
            max_value=3600,
        ),
        ToolParameter(
            name="dry_run",
            type=ParameterType.BOOLEAN,
            description=(
                "If true: run the probe/worktree/bundle pipeline without "
                "actually spawning the external CLI."
            ),
            required=False,
            default=False,
        ),
    ]


def _delegate_metadata() -> dict[str, Any]:
    return {
        "task_intents": ["implement_feature", "apply_change"],
        "domains": ["codebase"],
        "operations": ["edit"],
        "requires_known_target": False,
        "cost": "high",
        "tool_hint": (
            "Use when a change touches multiple files, needs iterative "
            "verify cycles, or when two failed in-line attempts already "
            "happened."
        ),
    }


def _missing_value_result(error: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=error,
        error_code=ToolErrorCode.MISSING_VALUE.value,
    )


def _invalid_parameters_result(error: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=error,
        error_code=ToolErrorCode.INVALID_PARAMETERS.value,
    )


def _delegate_input(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
    plugin_adapters: tuple[str, ...] = (),
) -> _DelegateInput | ToolResult:
    prompt = str(parameters.get("prompt") or "").strip()
    if not prompt:
        return _missing_value_result("prompt is required")

    adapter_param = str(parameters.get("adapter") or "auto").strip()
    available_adapters = tuple(dict.fromkeys((*_VALID_ADAPTERS, *plugin_adapters)))
    if adapter_param not in available_adapters:
        return _invalid_parameters_result(
            f"adapter must be one of {available_adapters}"
        )

    sid = str((context.env_vars or {}).get("session_id") or "").strip()
    if not sid:
        return _invalid_parameters_result(
            "delegate_to_external_coder requires an active session"
        )

    workspace = getattr(context, "workspace", None)
    if not workspace:
        return _invalid_parameters_result("workspace is missing in context")

    return _DelegateInput(
        prompt=prompt,
        adapter_param=adapter_param,
        session_id=sid,
        workspace=workspace,
    )


def _files_hint(parameters: Dict[str, Any]) -> list[str] | ToolResult:
    raw_files_hint = parameters.get("files_hint")
    if raw_files_hint is None:
        return []
    if not isinstance(raw_files_hint, list):
        return _invalid_parameters_result("files_hint must be a list of strings")
    return [str(path) for path in raw_files_hint]


class DelegateToExternalCoderTool(Tool):
    """Delegate coding tasks to built-in CLIs or live external-agent providers."""

    @property
    def schema(self) -> ToolSchema | None:
        """Give every exporter and validator an independent, current schema."""
        if self._schema is None:
            return None
        schema = self._schema.model_copy(deep=True)
        providers = getattr(self, "_provider_registry", None)
        names = providers.names("external_agent") if providers is not None else ()
        for parameter in schema.parameters:
            if parameter.name == "adapter":
                parameter.enum = list(dict.fromkeys((*_VALID_ADAPTERS, *names)))
        return schema

    @schema.setter
    def schema(self, value: ToolSchema | None) -> None:
        self._schema = value

    def bind_provider_registry(self, registry: Any, *, kind: str) -> Callable[[], None]:
        """Bind external adapter selection to the shared provider registry."""
        token = object()
        self._provider_binding = token
        self._provider_registry = registry

        def dispose() -> None:
            if self._provider_binding is token:
                self._provider_registry = None

        return dispose

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="delegate_to_external_coder",
            description=(
                "Delegate a coding task to Claude Code, Codex, or a connected "
                "external-agent provider. Use for: multi-file refactors, new features, bug "
                "fixes that need iterative typecheck/test cycles. The external "
                "tool runs in an isolated git worktree under "
                ".magi/sessions/<sid>/worktrees/<delegation_id>/; the result "
                "returns as a unified diff and a summary. Do NOT use for: "
                "questions, single-line edits, exploration."
            ),
            category="agent",
            version="1.0.0",
            author="Magi Team",
            parameters=_delegate_parameters(),
            timeout=3600,
            retry_on_failure=False,
            dangerous=False,  # Runs in isolated worktree, safer than direct file edits
            effect_class="external_write",
            effect_replay_policy="reconcilable",
            tags=["agent", "delegate", "code"],
            metadata=_delegate_metadata(),
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        providers = getattr(self, "_provider_registry", None)
        delegate_input = _delegate_input(
            parameters,
            context,
            tuple(providers.names("external_agent")) if providers is not None else (),
        )
        if isinstance(delegate_input, ToolResult):
            return delegate_input

        artifact_registry = (
            getattr(context.capabilities, "delegation_artifacts", None)
            if context.capabilities
            else None
        )
        if artifact_registry is None:
            return _invalid_parameters_result(
                "Code delegation artifact registry is unavailable"
            )

        settings = load_settings(workspace_root=delegate_input.workspace)
        if not settings.enabled:
            return _invalid_parameters_result(
                "External code tools are disabled in settings"
            )

        binary_paths = _binary_paths_from_settings(settings)
        resolved_adapter = _resolve_adapter(
            delegate_input.adapter_param,
            settings,
            binary_paths,
        )

        timeout_s = int(
            parameters.get("timeout_s") or settings.constraints.default_timeout_s
        )
        timeout_s = max(60, min(3600, timeout_s))

        files_hint = _files_hint(parameters)
        if isinstance(files_hint, ToolResult):
            return files_hint

        constraints = DelegateConstraints(
            forbid_paths=list(settings.constraints.forbid_paths),
            forbid_git_commit=settings.constraints.forbid_git_commit,
            forbid_git_push=settings.constraints.forbid_git_push,
            max_budget_usd=(
                settings.claude_code.max_budget_usd
                if resolved_adapter == "claude_code"
                else None
            ),
        )

        try:
            req = DelegateRequest(
                delegation_id=uuid.uuid4().hex,
                session_id=delegate_input.session_id,
                turn_id=str((context.env_vars or {}).get("turn_id") or "").strip(),
                adapter=resolved_adapter,
                prompt=delegate_input.prompt,
                files_hint=files_hint,
                workspace_root=str(
                    Path(delegate_input.workspace).expanduser().absolute()
                ),
                constraints=constraints,
                timeout_s=timeout_s,
                model=(
                    str(parameters.get("model")) if parameters.get("model") else None
                ),
            )
        except ValueError as exc:
            return _invalid_parameters_result(str(exc))

        service = CodeAgentService(
            binary_paths=binary_paths,
            cleanup_worktree=False,
            provider_registry=getattr(self, "_provider_registry", None),
        )
        user_id = str((context.env_vars or {}).get("user_id") or "").strip() or None
        try:
            result = await service.delegate(
                req,
                dry_run=bool(parameters.get("dry_run")),
                user_id=user_id,
                delegation_events=(
                    context.capabilities.delegation_events
                    if context.capabilities
                    else None
                ),
                artifact_registry=artifact_registry,
                cancellation=context.cancellation,
            )
        except CodeAgentArtifactPathError as exc:
            return _invalid_parameters_result(str(exc))
        result_data = result.model_dump()
        if result.artifact_registered:
            result_data["assistant_payload"] = {
                "code_agent_delegations": [
                    {
                        "delegation_id": result.delegation_id,
                        "turn_id": req.turn_id,
                        "workspace_path": req.workspace_root,
                    }
                ],
            }
        return ToolResult(
            success=result.success,
            data=result_data,
            error=result.error,
            error_code=None if result.success else ToolErrorCode.EXECUTION_ERROR.value,
        )


__all__ = ["DelegateToExternalCoderTool"]
