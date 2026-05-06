"""Service that ties probe + worktree + bundle + adapter + diff into one call."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ...agent.workspace_cache.atomic_io import append_jsonl, atomic_write_text
from .adapters.base import AdapterRunOutcome, CancelToken, CodeAgentAdapter, OnEvent
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter
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

    async def delegate(
        self,
        req: DelegateRequest,
        *,
        dry_run: bool = False,
        on_event: Optional[OnEvent] = None,
    ) -> DelegateResult:
        start = time.monotonic()
        delegation_dir = self._delegation_dir(req)
        delegation_dir.mkdir(parents=True, exist_ok=True)
        events_path = delegation_dir / "events.jsonl"
        atomic_write_text(delegation_dir / "request.json", json.dumps(req.model_dump()))

        async def _emit(ev: RunEvent) -> None:
            try:
                append_jsonl(events_path, ev.model_dump())
            except Exception:
                pass
            if on_event is not None:
                await on_event(ev)

        try:
            worktree = create_worktree(
                workspace_root=Path(req.workspace_root),
                session_id=req.session_id,
                delegation_id=req.delegation_id,
            )
        except NotAGitRepoError as exc:
            return self._fail(req, delegation_dir, start, str(exc))
        except Exception as exc:
            return self._fail(req, delegation_dir, start, f"worktree creation failed: {exc}")

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
            return result

        adapters = self.adapters_factory()
        adapter = adapters.get(req.adapter)
        if adapter is None:
            if self.cleanup_worktree:
                remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)
            return self._fail(
                req, delegation_dir, start,
                f"adapter not configured: {req.adapter}",
            )

        binary_paths = (
            self.binary_paths if self.binary_paths is not None else _default_binary_paths()
        )
        binary_path = binary_paths.get(req.adapter)
        if not binary_path:
            if self.cleanup_worktree:
                remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)
            return self._fail(
                req, delegation_dir, start,
                f"adapter binary not found: {req.adapter}",
            )

        cancel_token = CancelToken()
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
        if self.cleanup_worktree:
            remove_worktree(workspace_root=Path(req.workspace_root), worktree_path=worktree)
        return result

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
