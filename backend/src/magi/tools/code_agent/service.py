"""Service that ties probe + worktree + bundle + adapter + diff into one call."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from magi_plugin_sdk.capabilities import (
    DelegationArtifactPort,
    DelegationEventPort,
)
from magi_plugin_sdk.fs import append_jsonl, atomic_write_text

from ...core.code_agent_artifacts import (
    CodeAgentArtifactLocator,
    CodeAgentArtifactPathError,
    normalize_code_agent_delegation_id,
)
from .adapters.base import AdapterRunOutcome, CancelToken, CodeAgentAdapter, OnEvent
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter
from .apply_diff import apply_delegation
from .context_bundle import ContextBundle
from .contracts import (
    AdapterName,
    DelegateRequest,
    DelegateResult,
    DiffSnapshot,
    DiffStats,
    RunEvent,
)
from .diff_collector import collect_diff
from .errors import NotAGitRepoError
from .probe import probe_all
from .settings import load_settings
from .workspace import assert_git_repo, create_worktree, remove_worktree


def _default_adapters_factory() -> dict[AdapterName, CodeAgentAdapter]:
    return {
        "claude_code": ClaudeCodeAdapter(),
        "codex": CodexAdapter(),
    }


def _default_binary_paths() -> dict[AdapterName, Optional[str]]:
    probes = probe_all(force=False)
    return {
        "claude_code": probes["claude_code"].binary_path,
        "codex": probes["codex"].binary_path,
    }


@dataclass
class _DelegationRunContext:
    req: DelegateRequest
    start: float
    paths: CodeAgentArtifactLocator
    delegation_dir: Path
    events_path: Path
    on_event: Optional[OnEvent]
    broadcaster_user_id: str
    delegation_events: DelegationEventPort | None

    def write_request(self) -> None:
        request_path = self.paths.artifact_file(
            "request.json",
            require_delegation=True,
        )
        atomic_write_text(request_path, json.dumps(self.req.model_dump()))

    async def broadcast_event_safely(self, ev: RunEvent) -> None:
        port = self.delegation_events
        if not self.broadcaster_user_id or port is None:
            return
        try:
            await port.broadcast_event(
                user_id=self.broadcaster_user_id,
                session_id=self.req.session_id,
                turn_id=self.req.turn_id,
                delegation_id=self.req.delegation_id,
                event=ev,
            )
        except Exception:
            pass

    async def broadcast_state_safely(
        self,
        state: str,
        summary: dict | None = None,
    ) -> None:
        port = self.delegation_events
        if not self.broadcaster_user_id or port is None:
            return
        try:
            await port.broadcast_state(
                user_id=self.broadcaster_user_id,
                session_id=self.req.session_id,
                turn_id=self.req.turn_id,
                delegation_id=self.req.delegation_id,
                state=state,  # type: ignore[arg-type]
                summary=summary or {},
            )
        except Exception:
            pass

    async def emit(self, ev: RunEvent) -> None:
        try:
            events_path = self.paths.artifact_file(
                "events.jsonl",
                require_delegation=True,
            )
            append_jsonl(events_path, ev.model_dump())
        except Exception:
            pass
        await self.broadcast_event_safely(ev)
        if self.on_event is not None:
            await self.on_event(ev)

    async def finalize(self, result: DelegateResult) -> DelegateResult:
        if result.cancelled:
            await self.broadcast_state_safely("cancelled", result.model_dump())
        elif result.error and not result.success:
            await self.broadcast_state_safely("failed", result.model_dump())
        else:
            await self.broadcast_state_safely("finished", result.model_dump())
        return result


@dataclass
class CodeAgentService:
    """Orchestrate a delegation end-to-end."""

    adapters_factory: Callable[[], dict[AdapterName, CodeAgentAdapter]] = (
        _default_adapters_factory
    )
    binary_paths: Optional[dict[AdapterName, Optional[str]]] = None
    cleanup_worktree: bool = False
    provider_registry: Any = None

    _ACTIVE_CANCEL_TOKENS: ClassVar[dict[str, CancelToken]] = {}

    @classmethod
    def cancel(cls, delegation_id: str) -> bool:
        """Signal an active delegation to cancel cooperatively.

        Returns ``True`` when the delegation_id was active and the token has
        been flipped, ``False`` when no active delegation matches.
        """
        try:
            normalized_id = normalize_code_agent_delegation_id(delegation_id)
        except CodeAgentArtifactPathError:
            return False
        token = cls._ACTIVE_CANCEL_TOKENS.get(normalized_id)
        if token is None:
            return False
        token.cancel()
        return True

    async def delegate(
        self,
        req: DelegateRequest,
        *,
        artifact_registry: DelegationArtifactPort | None,
        dry_run: bool = False,
        on_event: Optional[OnEvent] = None,
        user_id: Optional[str] = None,
        delegation_events: DelegationEventPort | None = None,
        cancellation: Any | None = None,
    ) -> DelegateResult:
        start = time.monotonic()
        paths = CodeAgentArtifactLocator.resolve(
            workspace_root=req.workspace_root,
            session_id=req.session_id,
            delegation_id=req.delegation_id,
        )
        try:
            assert_git_repo(paths.workspace_root)
        except NotAGitRepoError as exc:
            return self._unpersisted_failure(
                req,
                paths,
                start,
                str(exc),
            )
        paths.validate_existing_scopes()
        if artifact_registry is None:
            raise RuntimeError("code-agent artifact registry is required")
        await artifact_registry.register(
            session_id=paths.session_id,
            turn_id=req.turn_id,
            delegation_id=paths.delegation_id,
            workspace_path=str(paths.workspace_root),
        )
        paths.ensure_delegation_dir()
        context = self._build_run_context(
            req,
            paths=paths,
            on_event=on_event,
            user_id=user_id,
            delegation_events=delegation_events,
        )
        context.write_request()
        await context.broadcast_state_safely("started")

        worktree, failure = self._create_worktree_or_failure(req, context)
        if failure is not None:
            return await context.finalize(failure)
        assert worktree is not None

        self._write_context_bundle(
            req,
            context.paths.ensure_delegation_child_dir("_bundle"),
        )

        if dry_run:
            result = self._build_dry_run_result(req, context)
            self._cleanup_worktree_if_needed(req, worktree)
            return await context.finalize(result)

        adapter, binary_path, error = self._resolve_adapter(req)
        if error is not None:
            self._cleanup_worktree_if_needed(req, worktree)
            return await context.finalize(self._fail(req, context, error))
        assert adapter is not None and binary_path is not None

        outcome = await self._run_adapter(
            req,
            adapter=adapter,
            binary_path=binary_path,
            worktree=worktree,
            context=context,
            cancellation=cancellation,
        )
        result, snapshot = self._record_adapter_result(req, context, outcome, worktree)
        result = self._maybe_auto_apply_successful_result(
            req,
            result,
            snapshot,
        )
        self._cleanup_worktree_if_needed(req, worktree)
        return await context.finalize(result)

    def _build_run_context(
        self,
        req: DelegateRequest,
        *,
        paths: CodeAgentArtifactLocator,
        on_event: Optional[OnEvent],
        user_id: Optional[str],
        delegation_events: DelegationEventPort | None,
    ) -> _DelegationRunContext:
        delegation_dir = paths.existing_delegation_dir()
        if delegation_dir is None:  # pragma: no cover - created by delegate
            raise RuntimeError("delegation directory is missing")
        events_path = paths.artifact_file(
            "events.jsonl",
            require_delegation=True,
        )
        return _DelegationRunContext(
            req=req,
            start=time.monotonic(),
            paths=paths,
            delegation_dir=delegation_dir,
            events_path=events_path,
            on_event=on_event,
            broadcaster_user_id=(user_id or "").strip(),
            delegation_events=delegation_events,
        )

    def _create_worktree_or_failure(
        self,
        req: DelegateRequest,
        context: _DelegationRunContext,
    ) -> tuple[Path | None, DelegateResult | None]:
        try:
            worktree = create_worktree(
                workspace_root=Path(req.workspace_root),
                session_id=req.session_id,
                delegation_id=req.delegation_id,
            )
        except NotAGitRepoError as exc:
            return None, self._fail(req, context, str(exc))
        except Exception as exc:
            return None, self._fail(
                req,
                context,
                f"worktree creation failed: {exc}",
            )
        return worktree, None

    @staticmethod
    def _write_context_bundle(req: DelegateRequest, bundle_dir: Path) -> None:
        ContextBundle(
            bundle_dir=bundle_dir,
            prompt=req.prompt,
            files_hint=list(req.files_hint),
            constraints=req.constraints,
        ).write()

    def _build_dry_run_result(
        self,
        req: DelegateRequest,
        context: _DelegationRunContext,
    ) -> DelegateResult:
        patch_path = context.paths.artifact_file(
            "changes.patch",
            require_delegation=True,
        )
        atomic_write_text(patch_path, "")
        result = DelegateResult(
            delegation_id=req.delegation_id,
            success=True,
            exit_code=0,
            duration_ms=self._duration_ms(context.start),
            adapter=req.adapter,
            diff_path=str(patch_path),
            diff_stats=DiffStats(),
            files_changed=[],
            summary="dry run",
            logs_path=str(context.delegation_dir),
            events_path=str(context.events_path),
            error=None,
            cost=None,
            artifact_registered=True,
        )
        self._write_result(context, result)
        return result

    def _resolve_adapter(
        self,
        req: DelegateRequest,
    ) -> tuple[CodeAgentAdapter | None, str | None, str | None]:
        adapter = self.adapters_factory().get(req.adapter)
        if self.provider_registry is not None:
            replacement = self.provider_registry.get("external_agent", req.adapter)
            if replacement is not None:
                from .adapters.plugin import PluginExternalAgentAdapter

                adapter = PluginExternalAgentAdapter(
                    replacement,
                    connection=self.provider_registry.connection_for(
                        "external_agent", req.adapter
                    ),
                    valid=lambda: self.provider_registry.get(
                        "external_agent", req.adapter
                    )
                    is replacement,
                )
                return adapter, "plugin", None
        if adapter is None:
            return None, None, f"adapter not configured: {req.adapter}"

        binary_paths = (
            self.binary_paths
            if self.binary_paths is not None
            else _default_binary_paths()
        )
        binary_path = binary_paths.get(req.adapter)
        if not binary_path:
            return None, None, f"adapter binary not found: {req.adapter}"
        return adapter, binary_path, None

    async def _run_adapter(
        self,
        req: DelegateRequest,
        *,
        adapter: CodeAgentAdapter,
        binary_path: str,
        worktree: Path,
        context: _DelegationRunContext,
        cancellation: Any | None,
    ) -> AdapterRunOutcome:
        cancel_token = CancelToken()
        cancellation_bridge: asyncio.Task[None] | None = None
        if cancellation is not None:
            cancellation_bridge = asyncio.create_task(
                self._bridge_external_cancellation(
                    cancellation,
                    cancel_token,
                ),
                name=f"code-agent-cancellation-{req.delegation_id}",
            )
        CodeAgentService._ACTIVE_CANCEL_TOKENS[req.delegation_id] = cancel_token
        try:
            return await adapter.run(
                req,
                cwd=worktree,
                bundle_dir=context.paths.ensure_delegation_child_dir("_bundle"),
                stdout_path=context.paths.artifact_file(
                    "stdout.log",
                    require_delegation=True,
                ),
                stderr_path=context.paths.artifact_file(
                    "stderr.log",
                    require_delegation=True,
                ),
                on_event=context.emit,
                cancel_token=cancel_token,
                binary_path=binary_path,
            )
        except Exception as exc:
            return AdapterRunOutcome(
                exit_code=-1,
                summary=None,
                cost=None,
                error=f"adapter raised: {exc}",
            )
        finally:
            CodeAgentService._ACTIVE_CANCEL_TOKENS.pop(req.delegation_id, None)
            if cancellation_bridge is not None:
                cancellation_bridge.cancel()
                with suppress(asyncio.CancelledError):
                    await cancellation_bridge

    @staticmethod
    async def _bridge_external_cancellation(
        cancellation: Any,
        cancel_token: CancelToken,
    ) -> None:
        try:
            wait = getattr(cancellation, "wait", None)
            if callable(wait):
                await wait()
            else:
                is_cancelled = getattr(cancellation, "is_cancelled", None)
                if not callable(is_cancelled):
                    return
                while not await is_cancelled():
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        reason = getattr(cancellation, "reason", None)
        cancel_token.cancel(str(reason or "runtime_cancelled"))

    def _record_adapter_result(
        self,
        req: DelegateRequest,
        context: _DelegationRunContext,
        outcome: AdapterRunOutcome,
        worktree: Path,
    ) -> tuple[DelegateResult, DiffSnapshot]:
        snapshot = collect_diff(worktree)
        patch_path = context.paths.artifact_file(
            "changes.patch",
            require_delegation=True,
        )
        atomic_write_text(patch_path, snapshot.unified_diff)

        result = DelegateResult(
            delegation_id=req.delegation_id,
            success=outcome.exit_code == 0 and outcome.error is None,
            exit_code=outcome.exit_code,
            duration_ms=self._duration_ms(context.start),
            adapter=req.adapter,
            diff_path=str(patch_path),
            diff_stats=snapshot.stats,
            files_changed=list(snapshot.files_changed),
            summary=outcome.summary,
            logs_path=str(context.delegation_dir),
            events_path=str(context.events_path),
            error=outcome.error,
            cost=outcome.cost,
            artifact_registered=True,
            cancelled=outcome.cancelled,
        )
        self._write_result(context, result)
        return result, snapshot

    def _maybe_auto_apply_successful_result(
        self,
        req: DelegateRequest,
        result: DelegateResult,
        snapshot: DiffSnapshot,
    ) -> DelegateResult:
        if not result.success or not snapshot.unified_diff.strip():
            return result
        try:
            settings = load_settings(workspace_root=Path(req.workspace_root))
        except Exception:
            return result
        if not settings.auto_apply:
            return result
        apply_outcome = apply_delegation(
            workspace_root=Path(req.workspace_root),
            session_id=req.session_id,
            delegation_id=req.delegation_id,
        )
        if not apply_outcome.applied:
            return result
        if apply_outcome.applied_at is None:
            raise RuntimeError("applied delegation is missing its timestamp")
        final_result = result.model_copy(
            update={
                "applied": True,
                "applied_at": apply_outcome.applied_at,
                "applied_files": list(apply_outcome.files_applied),
            },
        )
        return final_result

    def _cleanup_worktree_if_needed(self, req: DelegateRequest, worktree: Path) -> None:
        if self.cleanup_worktree:
            remove_worktree(
                workspace_root=Path(req.workspace_root), worktree_path=worktree
            )

    @staticmethod
    def _duration_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    @staticmethod
    def _write_result(context: _DelegationRunContext, result: DelegateResult) -> None:
        result_path = context.paths.artifact_file(
            "result.json",
            require_delegation=True,
        )
        atomic_write_text(
            result_path,
            json.dumps(result.model_dump()),
        )

    def _fail(
        self,
        req: DelegateRequest,
        context: _DelegationRunContext,
        error: str,
    ) -> DelegateResult:
        result = DelegateResult(
            delegation_id=req.delegation_id,
            success=False,
            exit_code=-1,
            duration_ms=self._duration_ms(context.start),
            adapter=req.adapter,
            diff_path=None,
            diff_stats=DiffStats(),
            files_changed=[],
            summary=None,
            logs_path=str(context.delegation_dir),
            events_path=str(context.events_path),
            error=error,
            cost=None,
            artifact_registered=True,
        )
        try:
            self._write_result(context, result)
        except Exception:
            pass
        return result

    def _unpersisted_failure(
        self,
        req: DelegateRequest,
        paths: CodeAgentArtifactLocator,
        start: float,
        error: str,
    ) -> DelegateResult:
        return DelegateResult(
            delegation_id=req.delegation_id,
            success=False,
            exit_code=-1,
            duration_ms=self._duration_ms(start),
            adapter=req.adapter,
            diff_path=None,
            diff_stats=DiffStats(),
            files_changed=[],
            summary=None,
            logs_path=str(paths.delegation_dir),
            events_path=str(paths.delegation_dir / "events.jsonl"),
            error=error,
            cost=None,
        )


__all__ = ["CodeAgentService"]
