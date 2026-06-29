"""Service that ties probe + worktree + bundle + adapter + diff into one call."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from magi_plugin_sdk.fs import append_jsonl, atomic_write_text
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
from .workspace import create_worktree, remove_worktree


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
    delegation_dir: Path
    events_path: Path
    on_event: Optional[OnEvent]
    broadcaster_user_id: str
    delegation_events: Any | None

    @property
    def broadcast_enabled(self) -> bool:
        return bool(self.broadcaster_user_id) and self.delegation_events is not None

    def write_request(self) -> None:
        self.delegation_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.delegation_dir / "request.json", json.dumps(self.req.model_dump()))

    async def broadcast_event_safely(self, ev: RunEvent) -> None:
        if not self.broadcast_enabled:
            return
        try:
            await self.delegation_events.broadcast_event(
                user_id=self.broadcaster_user_id,
                session_id=self.req.session_id,
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
        if not self.broadcast_enabled:
            return
        try:
            await self.delegation_events.broadcast_state(
                user_id=self.broadcaster_user_id,
                session_id=self.req.session_id,
                delegation_id=self.req.delegation_id,
                state=state,  # type: ignore[arg-type]
                summary=summary or {},
            )
        except Exception:
            pass

    async def emit(self, ev: RunEvent) -> None:
        try:
            append_jsonl(self.events_path, ev.model_dump())
        except Exception:
            pass
        await self.broadcast_event_safely(ev)
        if self.on_event is not None:
            await self.on_event(ev)

    async def finalize(self, result: DelegateResult) -> DelegateResult:
        if result.error and not result.success:
            await self.broadcast_state_safely("failed", result.model_dump())
        else:
            await self.broadcast_state_safely("finished", result.model_dump())
        return result


@dataclass
class CodeAgentService:
    """Orchestrate a delegation end-to-end."""

    adapters_factory: Callable[[], dict[AdapterName, CodeAgentAdapter]] = _default_adapters_factory
    binary_paths: Optional[dict[AdapterName, Optional[str]]] = None
    cleanup_worktree: bool = False

    _ACTIVE_CANCEL_TOKENS: ClassVar[dict[str, CancelToken]] = {}

    @classmethod
    def cancel(cls, delegation_id: str) -> bool:
        """Signal an active delegation to cancel cooperatively.

        Returns ``True`` when the delegation_id was active and the token has
        been flipped, ``False`` when no active delegation matches.
        """
        token = cls._ACTIVE_CANCEL_TOKENS.get(delegation_id)
        if token is None:
            return False
        token.cancel()
        return True

    async def delegate(
        self,
        req: DelegateRequest,
        *,
        dry_run: bool = False,
        on_event: Optional[OnEvent] = None,
        user_id: Optional[str] = None,
        delegation_events=None,
    ) -> DelegateResult:
        context = self._build_run_context(
            req,
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

        self._write_context_bundle(req, context.delegation_dir / "_bundle")

        if dry_run:
            result = self._build_dry_run_result(req, context)
            self._cleanup_worktree_if_needed(req, worktree)
            return await context.finalize(result)

        adapter, binary_path, error = self._resolve_adapter(req)
        if error is not None:
            self._cleanup_worktree_if_needed(req, worktree)
            return await context.finalize(
                self._fail(req, context.delegation_dir, context.start, error)
            )
        assert adapter is not None and binary_path is not None

        outcome = await self._run_adapter(
            req,
            adapter=adapter,
            binary_path=binary_path,
            worktree=worktree,
            context=context,
        )
        result, snapshot = self._record_adapter_result(req, context, outcome, worktree)
        self._maybe_auto_apply_successful_result(req, context, result, snapshot)
        self._cleanup_worktree_if_needed(req, worktree)
        return await context.finalize(result)

    def _build_run_context(
        self,
        req: DelegateRequest,
        *,
        on_event: Optional[OnEvent],
        user_id: Optional[str],
        delegation_events: Any | None,
    ) -> _DelegationRunContext:
        delegation_dir = self._delegation_dir(req)
        return _DelegationRunContext(
            req=req,
            start=time.monotonic(),
            delegation_dir=delegation_dir,
            events_path=delegation_dir / "events.jsonl",
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
            return None, self._fail(req, context.delegation_dir, context.start, str(exc))
        except Exception as exc:
            return None, self._fail(
                req,
                context.delegation_dir,
                context.start,
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
        patch_path = context.delegation_dir / "changes.patch"
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
        )
        self._write_result(context, result)
        return result

    def _resolve_adapter(
        self,
        req: DelegateRequest,
    ) -> tuple[CodeAgentAdapter | None, str | None, str | None]:
        adapter = self.adapters_factory().get(req.adapter)
        if adapter is None:
            return None, None, f"adapter not configured: {req.adapter}"

        binary_paths = (
            self.binary_paths if self.binary_paths is not None else _default_binary_paths()
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
    ) -> AdapterRunOutcome:
        cancel_token = CancelToken()
        CodeAgentService._ACTIVE_CANCEL_TOKENS[req.delegation_id] = cancel_token
        try:
            return await adapter.run(
                req,
                cwd=worktree,
                bundle_dir=context.delegation_dir / "_bundle",
                stdout_path=context.delegation_dir / "stdout.log",
                stderr_path=context.delegation_dir / "stderr.log",
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

    def _record_adapter_result(
        self,
        req: DelegateRequest,
        context: _DelegationRunContext,
        outcome: AdapterRunOutcome,
        worktree: Path,
    ) -> tuple[DelegateResult, DiffSnapshot]:
        snapshot = collect_diff(worktree)
        patch_path = context.delegation_dir / "changes.patch"
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
        )
        self._write_result(context, result)
        return result, snapshot

    def _maybe_auto_apply_successful_result(
        self,
        req: DelegateRequest,
        context: _DelegationRunContext,
        result: DelegateResult,
        snapshot: DiffSnapshot,
    ) -> None:
        if not result.success or not snapshot.unified_diff.strip():
            return
        try:
            settings = load_settings(workspace_root=Path(req.workspace_root))
            if not settings.auto_apply:
                return
            apply_outcome = apply_delegation(
                workspace_root=Path(req.workspace_root),
                session_id=req.session_id,
                delegation_id=req.delegation_id,
            )
            if apply_outcome.applied:
                result.applied_at = apply_outcome.to_dict().get("applied_at")
                result.applied_files = apply_outcome.files_applied
                self._write_result(context, result)
        except Exception:
            pass

    def _cleanup_worktree_if_needed(self, req: DelegateRequest, worktree: Path) -> None:
        if self.cleanup_worktree:
            remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)

    @staticmethod
    def _duration_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    @staticmethod
    def _write_result(context: _DelegationRunContext, result: DelegateResult) -> None:
        atomic_write_text(
            context.delegation_dir / "result.json",
            json.dumps(result.model_dump()),
        )

    def _delegation_dir(self, req: DelegateRequest) -> Path:
        return (
            Path(req.workspace_root)
            / ".magi"
            / "sessions"
            / req.session_id
            / "delegations"
            / req.delegation_id
        )

    def _fail(
        self,
        req: DelegateRequest,
        delegation_dir: Path,
        start: float,
        error: str,
    ) -> DelegateResult:
        duration_ms = int((time.monotonic() - start) * 1000)
        events_path = delegation_dir / "events.jsonl"
        result = DelegateResult(
            delegation_id=req.delegation_id,
            success=False,
            exit_code=-1,
            duration_ms=duration_ms,
            adapter=req.adapter,
            diff_path=None,
            diff_stats=DiffStats(),
            files_changed=[],
            summary=None,
            logs_path=str(delegation_dir),
            events_path=str(events_path),
            error=error,
            cost=None,
        )
        try:
            atomic_write_text(delegation_dir / "result.json", json.dumps(result.model_dump()))
        except Exception:
            pass
        return result


__all__ = ["CodeAgentService"]
