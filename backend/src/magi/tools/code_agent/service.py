"""Service that ties probe + worktree + bundle + adapter + diff into one call."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ClassVar, Optional

from ...agent.workspace_cache.atomic_io import append_jsonl, atomic_write_text
from .adapters.base import AdapterRunOutcome, CancelToken, CodeAgentAdapter, OnEvent
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter
from .apply_diff import apply_delegation
from .context_bundle import ContextBundle
from .contracts import (
    AdapterName,
    DelegateRequest,
    DelegateResult,
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
    ) -> DelegateResult:
        start = time.monotonic()
        delegation_dir = self._delegation_dir(req)
        delegation_dir.mkdir(parents=True, exist_ok=True)
        events_path = delegation_dir / "events.jsonl"
        atomic_write_text(delegation_dir / "request.json", json.dumps(req.model_dump()))

        broadcaster_user_id = (user_id or "").strip()
        broadcast_enabled = bool(broadcaster_user_id)

        async def _broadcast_event_safely(ev: RunEvent) -> None:
            if not broadcast_enabled:
                return
            try:
                from ...transport.code_agent_events import broadcast_delegation_event
                await broadcast_delegation_event(
                    user_id=broadcaster_user_id,
                    session_id=req.session_id,
                    delegation_id=req.delegation_id,
                    event=ev,
                )
            except Exception:
                pass

        async def _broadcast_state_safely(state: str, summary: dict | None = None) -> None:
            if not broadcast_enabled:
                return
            try:
                from ...transport.code_agent_events import broadcast_delegation_state
                await broadcast_delegation_state(
                    user_id=broadcaster_user_id,
                    session_id=req.session_id,
                    delegation_id=req.delegation_id,
                    state=state,  # type: ignore[arg-type]
                    summary=summary or {},
                )
            except Exception:
                pass

        async def _emit(ev: RunEvent) -> None:
            try:
                append_jsonl(events_path, ev.model_dump())
            except Exception:
                pass
            await _broadcast_event_safely(ev)
            if on_event is not None:
                await on_event(ev)

        await _broadcast_state_safely("started")

        async def _finalize(result: DelegateResult) -> DelegateResult:
            if result.error and not result.success:
                await _broadcast_state_safely("failed", result.model_dump())
            else:
                await _broadcast_state_safely("finished", result.model_dump())
            return result

        try:
            worktree = create_worktree(
                workspace_root=Path(req.workspace_root),
                session_id=req.session_id,
                delegation_id=req.delegation_id,
            )
        except NotAGitRepoError as exc:
            return await _finalize(self._fail(req, delegation_dir, start, str(exc)))
        except Exception as exc:
            return await _finalize(
                self._fail(req, delegation_dir, start, f"worktree creation failed: {exc}")
            )

        bundle_dir = delegation_dir / "_bundle"
        ContextBundle(
            bundle_dir=bundle_dir,
            prompt=req.prompt,
            files_hint=list(req.files_hint),
            constraints=req.constraints,
        ).write()

        if dry_run:
            duration_ms = int((time.monotonic() - start) * 1000)
            patch_path = delegation_dir / "changes.patch"
            atomic_write_text(patch_path, "")
            result = DelegateResult(
                delegation_id=req.delegation_id,
                success=True,
                exit_code=0,
                duration_ms=duration_ms,
                adapter=req.adapter,
                diff_path=str(patch_path),
                diff_stats=DiffStats(),
                files_changed=[],
                summary="dry run",
                logs_path=str(delegation_dir),
                events_path=str(events_path),
                error=None,
                cost=None,
            )
            atomic_write_text(delegation_dir / "result.json", json.dumps(result.model_dump()))
            if self.cleanup_worktree:
                remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)
            return await _finalize(result)

        adapters = self.adapters_factory()
        adapter = adapters.get(req.adapter)
        if adapter is None:
            if self.cleanup_worktree:
                remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)
            return await _finalize(self._fail(
                req, delegation_dir, start,
                f"adapter not configured: {req.adapter}",
            ))

        binary_paths = (
            self.binary_paths if self.binary_paths is not None else _default_binary_paths()
        )
        binary_path = binary_paths.get(req.adapter)
        if not binary_path:
            if self.cleanup_worktree:
                remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)
            return await _finalize(self._fail(
                req, delegation_dir, start,
                f"adapter binary not found: {req.adapter}",
            ))

        cancel_token = CancelToken()
        CodeAgentService._ACTIVE_CANCEL_TOKENS[req.delegation_id] = cancel_token
        outcome: AdapterRunOutcome
        try:
            outcome = await adapter.run(
                req,
                cwd=worktree,
                bundle_dir=bundle_dir,
                stdout_path=delegation_dir / "stdout.log",
                stderr_path=delegation_dir / "stderr.log",
                on_event=_emit,
                cancel_token=cancel_token,
                binary_path=binary_path,
            )
        except Exception as exc:
            outcome = AdapterRunOutcome(
                exit_code=-1, summary=None, cost=None,
                error=f"adapter raised: {exc}",
            )
        finally:
            CodeAgentService._ACTIVE_CANCEL_TOKENS.pop(req.delegation_id, None)

        snapshot = collect_diff(worktree)
        patch_path = delegation_dir / "changes.patch"
        atomic_write_text(patch_path, snapshot.unified_diff)

        duration_ms = int((time.monotonic() - start) * 1000)
        success = outcome.exit_code == 0 and outcome.error is None
        result = DelegateResult(
            delegation_id=req.delegation_id,
            success=success,
            exit_code=outcome.exit_code,
            duration_ms=duration_ms,
            adapter=req.adapter,
            diff_path=str(patch_path),
            diff_stats=snapshot.stats,
            files_changed=list(snapshot.files_changed),
            summary=outcome.summary,
            logs_path=str(delegation_dir),
            events_path=str(events_path),
            error=outcome.error,
            cost=outcome.cost,
        )
        atomic_write_text(delegation_dir / "result.json", json.dumps(result.model_dump()))

        # Auto-apply if enabled and delegation succeeded
        if success and snapshot.unified_diff.strip():
            try:
                settings = load_settings(workspace_root=Path(req.workspace_root))
                if settings.auto_apply:
                    apply_outcome = apply_delegation(
                        workspace_root=Path(req.workspace_root),
                        session_id=req.session_id,
                        delegation_id=req.delegation_id,
                    )
                    if apply_outcome.applied:
                        result.applied_at = apply_outcome.to_dict().get("applied_at")
                        result.applied_files = apply_outcome.files_applied
                        # Re-write result.json with apply info
                        atomic_write_text(
                            delegation_dir / "result.json",
                            json.dumps(result.model_dump()),
                        )
            except Exception:
                # Silently ignore auto-apply failures to not break the delegation
                pass

        if self.cleanup_worktree:
            remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)
        return await _finalize(result)

    def _delegation_dir(self, req: DelegateRequest) -> Path:
        return (
            Path(req.workspace_root) / ".magi" / "sessions" / req.session_id
            / "delegations" / req.delegation_id
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
