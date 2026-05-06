"""delegate_to_external_coder - hand a coding task to an external CLI."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict

from ..code_agent.contracts import (
    AdapterName,
    DelegateConstraints,
    DelegateRequest,
)
from ..code_agent.service import CodeAgentService
from ..code_agent.settings import load_settings
from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


_VALID_ADAPTERS: tuple[str, ...] = ("auto", "claude_code", "codex")


class DelegateToExternalCoderTool(Tool):
    """Delegate a coding task to an external CLI (Claude Code or Codex)."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="delegate_to_external_coder",
            description=(
                "Delegate a coding task to an external coding CLI (Claude Code "
                "or Codex). Use for: multi-file refactors, new features, bug "
                "fixes that need iterative typecheck/test cycles. The external "
                "tool runs in an isolated git worktree under "
                ".magi/sessions/<sid>/worktrees/<delegation_id>/; the result "
                "returns as a unified diff and a summary. Do NOT use for: "
                "questions, single-line edits, exploration."
            ),
            category="agent",
            version="1.0.0",
            author="Magi Team",
            parameters=[
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
                        "Optional: relative paths the external agent should "
                        "look at first."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="adapter",
                    type=ParameterType.STRING,
                    description=(
                        "Which CLI to use. 'auto' picks the configured default."
                    ),
                    required=False,
                    default="auto",
                    enum=list(_VALID_ADAPTERS),
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
            ],
            timeout=3600,
            retry_on_failure=False,
            dangerous=True,
            tags=["agent", "delegate", "code"],
            metadata={
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
            },
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        prompt = str(parameters.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(
                success=False,
                error="prompt is required",
                error_code=ToolErrorCode.MISSING_VALUE.value,
            )

        adapter_param = str(parameters.get("adapter") or "auto").strip()
        if adapter_param not in _VALID_ADAPTERS:
            return ToolResult(
                success=False,
                error=f"adapter must be one of {_VALID_ADAPTERS}",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        sid = str((context.env_vars or {}).get("session_id") or "").strip()
        if not sid:
            return ToolResult(
                success=False,
                error="delegate_to_external_coder requires an active session",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        workspace = getattr(context, "workspace", None)
        if not workspace:
            return ToolResult(
                success=False,
                error="workspace is missing in context",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        settings = load_settings(workspace_root=workspace)
        if adapter_param == "auto":
            resolved_adapter: AdapterName = settings.default_adapter
        else:
            resolved_adapter = adapter_param  # type: ignore[assignment]

        timeout_s = int(parameters.get("timeout_s") or settings.constraints.default_timeout_s)
        timeout_s = max(60, min(3600, timeout_s))

        files_hint = parameters.get("files_hint")
        if files_hint is None:
            files_hint = []
        if not isinstance(files_hint, list):
            return ToolResult(
                success=False,
                error="files_hint must be a list of strings",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        constraints = DelegateConstraints(
            forbid_paths=list(settings.constraints.forbid_paths),
            forbid_git_commit=settings.constraints.forbid_git_commit,
            forbid_git_push=settings.constraints.forbid_git_push,
            max_budget_usd=(
                settings.claude_code.max_budget_usd if resolved_adapter == "claude_code" else None
            ),
        )

        req = DelegateRequest(
            delegation_id=uuid.uuid4().hex,
            session_id=sid,
            adapter=resolved_adapter,
            prompt=prompt,
            files_hint=[str(p) for p in files_hint],
            workspace_root=str(Path(workspace).resolve()),
            constraints=constraints,
            timeout_s=timeout_s,
            model=(str(parameters.get("model")) if parameters.get("model") else None),
        )

        service = CodeAgentService(cleanup_worktree=False)
        user_id = str((context.env_vars or {}).get("user_id") or "").strip() or None
        result = await service.delegate(
            req, dry_run=bool(parameters.get("dry_run")), user_id=user_id,
        )
        return ToolResult(
            success=result.success,
            data=result.model_dump(),
            error=result.error,
            error_code=(
                None if result.success else ToolErrorCode.EXECUTION_ERROR.value
            ),
        )


__all__ = ["DelegateToExternalCoderTool"]
