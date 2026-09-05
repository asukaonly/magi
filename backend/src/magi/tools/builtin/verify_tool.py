"""verify - run file-type-aware sanity checks and record results."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

from magi_plugin_sdk.workspace_cache import resolve_session_cache
from magi_plugin_sdk.fs import append_jsonl
from ...core.logger import get_logger
from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from ._file_validation import file_content_digest
from ._verifiers import VerifyOutcome, verify_file

logger = get_logger(__name__)


class VerifyTool(Tool):
    """Run a fast type-aware check against one or more files."""

    MODE_PATHS = "paths"
    MODE_CHANGED = "changed"
    _MODES = (MODE_PATHS, MODE_CHANGED)

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="verify",
            description=(
                "Run a fast file-type-aware sanity check (compile / parse / "
                "typecheck) on one or more files. Use after a file_edit or "
                "file_write to confirm the change still parses before "
                "claiming the task is done. mode=changed verifies every file "
                "edited in this session; mode=paths verifies an explicit list."
            ),
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=self._schema_parameters(),
            timeout=180,
            retry_on_failure=False,
            dangerous=False,
            effect_class="read_only",
            effect_replay_policy="read_only",
            tags=["file", "verify"],
            metadata=self._schema_metadata(),
        )

    def _schema_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="mode",
                type=ParameterType.STRING,
                description="One of: changed, paths",
                required=False,
                default="changed",
                enum=list(VerifyTool._MODES),
            ),
            ToolParameter(
                name="paths",
                type=ParameterType.ARRAY,
                array_item_type=ParameterType.STRING,
                description="Files to verify. Required when mode=paths.",
                required=False,
            ),
            ToolParameter(
                name="timeout_s",
                type=ParameterType.INTEGER,
                description="Per-file subprocess timeout in seconds. Default 30.",
                required=False,
                default=30,
                min_value=1,
                max_value=120,
            ),
        ]

    @staticmethod
    def _schema_metadata() -> dict[str, Any]:
        return {
            "task_intents": ["verify_change"],
            "domains": ["codebase", "config"],
            "operations": ["verify"],
            "requires_known_target": False,
            "cost": "medium",
            "tool_hint": (
                "Call after editing source files to confirm the change still "
                "compiles. Default mode=changed picks up everything you edited "
                "this session via file_edit / file_write."
            ),
        }

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        mode = str(parameters.get("mode") or "changed").strip()
        timeout_s = int(parameters.get("timeout_s", 30))

        if mode not in self._MODES:
            return ToolResult(
                success=False,
                error=f"Unknown mode {mode!r}; must be one of {self._MODES}",
                error_code=ToolErrorCode.INVALID_MODE.value,
            )

        sid = str((context.env_vars or {}).get("session_id") or "").strip()
        sc = self._resolve_cache(context, sid)
        paths_result = self._resolve_verify_paths(mode=mode, parameters=parameters, sc=sc)
        if isinstance(paths_result, ToolResult):
            return paths_result
        workspace_root = Path(context.workspace).resolve()
        outcomes = await self._verify_paths(
            paths=paths_result,
            workspace_root=workspace_root,
            timeout_s=timeout_s,
        )
        self._append_verify_log(sc=sc, outcomes=outcomes)
        return ToolResult(
            success=True,
            data={
                "mode": mode,
                "results": [o.to_dict() for o in outcomes],
                "summary": self._summary(outcomes),
                "validation_status": "inconclusive" if not outcomes else "checked",
            },
        )

    def _resolve_verify_paths(
        self,
        *,
        mode: str,
        parameters: Dict[str, Any],
        sc: Any,
    ) -> list[str] | ToolResult:
        if mode == self.MODE_PATHS:
            paths_param = parameters.get("paths")
            if not isinstance(paths_param, list) or not paths_param:
                return ToolResult(
                    success=False,
                    error="mode=paths requires a non-empty paths list",
                    error_code=ToolErrorCode.MISSING_PATH.value,
                )
            return [str(p) for p in paths_param]
        return self._collect_changed_paths(sc) if sc is not None else []

    async def _verify_paths(
        self,
        *,
        paths: list[str],
        workspace_root: Path,
        timeout_s: int,
    ) -> list[VerifyOutcome]:
        outcomes: list[VerifyOutcome] = []
        for raw in paths:
            absolute = self._resolve_absolute(raw, workspace_root)
            if absolute is None:
                outcomes.append(self._outside_workspace_outcome(raw))
                continue
            before_digest = file_content_digest(absolute)
            outcome = await verify_file(absolute, timeout_s=timeout_s)
            after_digest = file_content_digest(absolute)
            if before_digest is None or before_digest != after_digest:
                if outcome.status == "pass":
                    outcome = replace(
                        outcome,
                        status="skipped",
                        reason="File content changed or could not be identified during verification",
                    )
            else:
                outcome = replace(outcome, content_sha256=after_digest)
            outcomes.append(outcome)
        return outcomes

    @staticmethod
    def _outside_workspace_outcome(raw: str) -> VerifyOutcome:
        return VerifyOutcome(
            path=raw,
            verifier="(none)",
            status="skipped",
            exit_code=-1,
            stdout="",
            stderr="",
            reason="path is outside workspace",
            duration_ms=0,
        )

    @staticmethod
    def _append_verify_log(*, sc: Any, outcomes: list[VerifyOutcome]) -> None:
        if sc is None:
            return
        log_path = sc.session_dir / "verify.jsonl"
        for outcome in outcomes:
            try:
                append_jsonl(log_path, outcome.to_dict())
            except Exception:
                logger.debug("verify.log_append_failed", exc_info=True)

    @staticmethod
    def _summary(outcomes: list[VerifyOutcome]) -> dict[str, int]:
        return {
            "pass": sum(1 for o in outcomes if o.status == "pass"),
            "fail": sum(1 for o in outcomes if o.status == "fail"),
            "skipped": sum(1 for o in outcomes if o.status == "skipped"),
            "timeout": sum(1 for o in outcomes if o.status == "timeout"),
        }

    @staticmethod
    def _resolve_cache(context: ToolExecutionContext, sid: str):
        if not sid or not getattr(context, "workspace", None):
            return None
        try:
            return resolve_session_cache(context.workspace, sid)
        except Exception:
            logger.warning("verify.cache_init_failed", exc_info=True)
            return None

    @staticmethod
    def _collect_changed_paths(sc) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for rec in sc.iter_edits():
            if rec.path not in seen:
                seen.add(rec.path)
                ordered.append(str(sc.root.workspace_root / rec.path))
        return ordered

    @staticmethod
    def _resolve_absolute(raw: str, workspace_root: Path) -> Path | None:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        try:
            resolved = candidate.resolve()
        except Exception:
            return None
        try:
            resolved.relative_to(workspace_root)
        except ValueError:
            return None
        return resolved


__all__ = ["VerifyTool"]
