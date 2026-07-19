"""Tests for CodeAgentService."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from magi.control.cancel import EventCancelToken
from magi.tools.code_agent.adapters.base import (
    AdapterRunOutcome,
    CancelToken,
    OnEvent,
)
from magi.tools.code_agent.contracts import (
    AdapterName,
    DelegateConstraints,
    DelegateRequest,
    ProbeResult,
    RunEvent,
)
from magi.tools.code_agent.service import CodeAgentService


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, check=True)
    (path / "src").mkdir()
    (path / "src" / "net.py").write_text("def connect():\n    return 1\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


class _FakeAdapter:
    """A configurable fake that mutates the worktree and reports a fixed outcome."""

    def __init__(self, *, name: AdapterName, edit: Optional[tuple[str, str]] = None,
                 outcome_kwargs: Optional[dict[str, Any]] = None):
        self.name = name
        self.display_name = f"Fake {name}"
        self._edit = edit
        self._outcome_kwargs = outcome_kwargs or {}

    @classmethod
    async def detect(cls) -> ProbeResult:
        raise NotImplementedError

    async def run(
        self,
        req: DelegateRequest,
        *,
        cwd: Path,
        bundle_dir: Path,
        stdout_path: Path,
        stderr_path: Path,
        on_event: OnEvent,
        cancel_token: CancelToken,
        binary_path: str,
    ) -> AdapterRunOutcome:
        if self._edit is not None:
            rel, contents = self._edit
            target = cwd / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("fake adapter ran\n")
        stderr_path.write_text("")
        await on_event(RunEvent(kind="status", ts_ms=1, payload={"event": "fake"}))
        kwargs: dict[str, Any] = dict(
            exit_code=0, summary="fake summary", cost=None, error=None,
        )
        kwargs.update(self._outcome_kwargs)
        return AdapterRunOutcome(**kwargs)


class _NoopArtifactRegistry:
    async def register(self, **_kwargs) -> None:
        return None


async def _delegate(
    service: CodeAgentService,
    req: DelegateRequest,
    **kwargs: Any,
):
    return await service.delegate(
        req,
        artifact_registry=_NoopArtifactRegistry(),
        **kwargs,
    )


@pytest.fixture
def isolated_magi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "magi_home"
    home.mkdir()
    monkeypatch.setenv("MAGI_HOME", str(home))
    return home


def _request(repo: Path, *, adapter: AdapterName = "claude_code") -> DelegateRequest:
    return DelegateRequest(
        delegation_id="c" * 32,
        session_id="s1",
        turn_id="turn-1",
        adapter=adapter,
        prompt="add max_retries to connect()",
        files_hint=["src/net.py"],
        workspace_root=str(repo),
        constraints=DelegateConstraints(),
        timeout_s=30,
        model=None,
    )


@pytest.mark.asyncio
async def test_service_dry_run_succeeds_without_running_adapter(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = _request(repo)
    result = await _delegate(service, req, dry_run=True)
    assert result.success is True
    assert result.summary == "dry run"
    assert result.diff_stats.files_changed == 0
    delegation_dir = repo / ".magi" / "sessions" / "s1" / "delegations" / req.delegation_id
    assert (delegation_dir / "_bundle" / "TASK.md").is_file()


@pytest.mark.asyncio
async def test_service_full_path_records_diff(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    fake = _FakeAdapter(
        name="claude_code",
        edit=("src/net.py", "def connect(max_retries=3):\n    return 1\n"),
    )
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": fake},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    result = await _delegate(service, _request(repo))
    assert result.success is True, result.error
    assert result.diff_stats.files_changed == 1
    assert result.files_changed == ["src/net.py"]
    assert result.summary == "fake summary"
    delegation_dir = repo / ".magi" / "sessions" / "s1" / "delegations" / ("c" * 32)
    assert (delegation_dir / "changes.patch").is_file()
    diff_text = (delegation_dir / "changes.patch").read_text()
    assert "max_retries" in diff_text
    assert (delegation_dir / "result.json").is_file()


@pytest.mark.asyncio
async def test_service_auto_apply_returns_persists_and_broadcasts_final_result(
    isolated_magi_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    fake = _FakeAdapter(
        name="claude_code",
        edit=("src/net.py", "def connect(max_retries=3):\n    return 1\n"),
    )
    port = _FakeDelegationEventPort()
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": fake},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    monkeypatch.setattr(
        "magi.tools.code_agent.service.load_settings",
        lambda workspace_root: SimpleNamespace(auto_apply=True),
    )

    req = _request(repo)
    result = await _delegate(
        service,
        req,
        user_id="local_user",
        delegation_events=port,
    )

    assert result.success is True
    assert result.applied is True
    assert result.applied_at is not None
    assert result.applied_files == ["src/net.py"]
    assert "max_retries" in (repo / "src" / "net.py").read_text()
    result_path = (
        repo
        / ".magi"
        / "sessions"
        / req.session_id
        / "delegations"
        / req.delegation_id
        / "result.json"
    )
    assert json.loads(result_path.read_text()) == result.model_dump()
    assert port.state_summaries[-1] == ("finished", result.model_dump())


@pytest.mark.asyncio
async def test_service_unknown_adapter_returns_error(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = DelegateRequest(
        delegation_id="d" * 32, session_id="s1", turn_id="turn-1",
        adapter="codex",
        prompt="x", files_hint=[], workspace_root=str(repo),
        constraints=DelegateConstraints(), timeout_s=30, model=None,
    )
    result = await _delegate(service, req)
    assert result.success is False
    assert result.error and "not configured" in result.error.lower()


@pytest.mark.asyncio
async def test_service_non_repo_workspace_returns_error(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = DelegateRequest(
        delegation_id="e" * 32, session_id="s1", turn_id="turn-1",
        adapter="claude_code",
        prompt="x", files_hint=[], workspace_root=str(plain),
        constraints=DelegateConstraints(), timeout_s=30, model=None,
    )
    result = await _delegate(service, req)
    assert result.success is False
    assert "git repository" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_service_cleans_worktree_after_run(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
        cleanup_worktree=True,
    )
    req = _request(repo)
    await _delegate(service, req)
    wt = repo / ".magi" / "sessions" / "s1" / "worktrees" / req.delegation_id
    assert not wt.exists()


class _FakeDelegationEventPort:
    """Fake DelegationEventPort that records calls for assertions."""

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []
        self.state_summaries: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_event(
        self,
        *,
        user_id,
        session_id,
        turn_id,
        delegation_id,
        event,
    ):
        self.calls.append((delegation_id, turn_id, "event"))

    async def broadcast_state(
        self,
        *,
        user_id,
        session_id,
        turn_id,
        delegation_id,
        state,
        summary=None,
    ):
        self.calls.append((delegation_id, turn_id, state))
        self.state_summaries.append((state, dict(summary or {})))


class _RecordingArtifactRegistry:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.calls: list[dict[str, str]] = []

    async def register(
        self,
        *,
        session_id,
        turn_id,
        delegation_id,
        workspace_path,
    ):
        assert not (self.workspace / ".magi").exists()
        self.calls.append(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "delegation_id": delegation_id,
                "workspace_path": workspace_path,
            }
        )


@pytest.mark.asyncio
async def test_service_registers_artifact_before_first_workspace_write(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    registry = _RecordingArtifactRegistry(repo)
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = _request(repo)

    result = await service.delegate(
        req,
        dry_run=True,
        artifact_registry=registry,
    )

    assert result.success is True
    assert registry.calls == [
        {
            "session_id": "s1",
            "turn_id": "turn-1",
            "delegation_id": req.delegation_id,
            "workspace_path": str(repo),
        }
    ]
    assert (
        repo
        / ".magi"
        / "sessions"
        / req.session_id
        / "delegations"
        / req.delegation_id
        / "request.json"
    ).is_file()


@pytest.mark.asyncio
async def test_service_registration_failure_writes_no_artifact(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")

    class _FailingArtifactRegistry:
        async def register(self, **_kwargs):
            raise RuntimeError("registry unavailable")

    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )

    with pytest.raises(RuntimeError, match="registry unavailable"):
        await service.delegate(
            _request(repo),
            dry_run=True,
            artifact_registry=_FailingArtifactRegistry(),
        )
    assert not (repo / ".magi").exists()


@pytest.mark.asyncio
async def test_service_missing_registry_writes_no_artifact(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )

    with pytest.raises(RuntimeError, match="artifact registry is required"):
        await service.delegate(
            _request(repo),
            artifact_registry=None,
            dry_run=True,
        )
    assert not (repo / ".magi").exists()


@pytest.mark.asyncio
async def test_service_checks_git_before_registering_artifact(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "plain"
    workspace.mkdir()
    calls: list[dict[str, Any]] = []

    class _ArtifactRegistry:
        async def register(self, **kwargs):
            calls.append(kwargs)

    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = _request(workspace)

    result = await service.delegate(
        req,
        dry_run=True,
        artifact_registry=_ArtifactRegistry(),
    )

    assert result.success is False
    assert "git repository" in (result.error or "").lower()
    assert calls == []
    assert not (workspace / ".magi").exists()


@pytest.mark.asyncio
async def test_service_rejects_symlink_workspace_before_writing(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    alias = tmp_path / "repo-alias"
    alias.symlink_to(repo, target_is_directory=True)
    req = _request(repo).model_copy(update={"workspace_root": str(alias)})
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )

    with pytest.raises(ValueError):
        await _delegate(service, req, dry_run=True)
    assert not (repo / ".magi").exists()


@pytest.mark.asyncio
async def test_service_rejects_symlinked_artifact_scope_without_writing_target(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".magi").symlink_to(outside, target_is_directory=True)
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )

    with pytest.raises(ValueError):
        await _delegate(service, _request(repo), dry_run=True)
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_service_broadcasts_state_when_user_id_present(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    """When user_id is supplied, the service must broadcast started + finished."""
    repo = _make_repo(tmp_path / "repo")

    port = _FakeDelegationEventPort()
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = _request(repo)
    await _delegate(
        service,
        req,
        user_id="local_user",
        delegation_events=port,
    )

    states = [call[2] for call in port.calls if call[2] != "event"]
    assert states[0] == "started"
    assert states[-1] == "finished"
    assert {call[1] for call in port.calls} == {"turn-1"}


@pytest.mark.asyncio
async def test_service_broadcasts_failed_on_unknown_adapter(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")

    port = _FakeDelegationEventPort()
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = DelegateRequest(
        delegation_id="f" * 32, session_id="s1", turn_id="turn-1",
        adapter="codex",
        prompt="x", files_hint=[], workspace_root=str(repo),
        constraints=DelegateConstraints(), timeout_s=30, model=None,
    )
    await _delegate(
        service,
        req,
        user_id="local_user",
        delegation_events=port,
    )
    states = [call[2] for call in port.calls if call[2] != "event"]
    assert "started" in states
    assert "failed" in states


@pytest.mark.asyncio
async def test_service_does_not_broadcast_when_user_id_missing(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")

    port = _FakeDelegationEventPort()
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _FakeAdapter(name="claude_code")},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    await _delegate(
        service,
        _request(repo),
        delegation_events=port,
    )  # no user_id
    assert port.calls == []


@pytest.mark.asyncio
async def test_service_cancel_returns_false_for_unknown_id() -> None:
    assert CodeAgentService.cancel("does-not-exist") is False


@pytest.mark.asyncio
async def test_service_cancel_signals_active_delegation(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    """A running delegation should expose its cancel token via the registry."""
    import asyncio

    repo = _make_repo(tmp_path / "repo")
    seen_cancelled: list[bool] = []

    class _SlowAdapter:
        name = "claude_code"
        display_name = "Slow"

        @classmethod
        async def detect(cls):
            raise NotImplementedError

        async def run(self, req, *, cwd, bundle_dir, stdout_path, stderr_path,
                      on_event, cancel_token, binary_path):
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_path.write_text("")
            stderr_path.write_text("")
            for _ in range(40):
                if cancel_token.cancelled:
                    seen_cancelled.append(True)
                    return AdapterRunOutcome(
                        exit_code=-1, summary=None, cost=None,
                        error="cancelled by user", cancelled=True,
                    )
                await asyncio.sleep(0.05)
            return AdapterRunOutcome(
                exit_code=0, summary="not cancelled", cost=None, error=None,
            )

    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _SlowAdapter()},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    req = _request(repo)
    delegate_task = asyncio.create_task(_delegate(service, req))
    await asyncio.sleep(0.15)
    assert CodeAgentService.cancel(req.delegation_id) is True
    result = await delegate_task
    assert seen_cancelled == [True]
    assert result.success is False
    assert result.cancelled is True
    assert req.delegation_id not in CodeAgentService._ACTIVE_CANCEL_TOKENS


@pytest.mark.asyncio
async def test_service_bridges_runtime_cancellation_and_broadcasts_cancelled(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    adapter_started = asyncio.Event()

    class _WaitingAdapter:
        name = "claude_code"
        display_name = "Waiting"

        @classmethod
        async def detect(cls):
            raise NotImplementedError

        async def run(
            self,
            req,
            *,
            cwd,
            bundle_dir,
            stdout_path,
            stderr_path,
            on_event,
            cancel_token,
            binary_path,
        ):
            stdout_path.write_text("")
            stderr_path.write_text("")
            adapter_started.set()
            await cancel_token.wait()
            return AdapterRunOutcome(
                exit_code=-1,
                summary=None,
                cost=None,
                error=f"adapter cancelled: {cancel_token.reason}",
                cancelled=True,
            )

    port = _FakeDelegationEventPort()
    cancellation = EventCancelToken()
    service = CodeAgentService(
        adapters_factory=lambda: {"claude_code": _WaitingAdapter()},
        binary_paths={"claude_code": "/unused", "codex": "/unused"},
    )
    task = asyncio.create_task(
        _delegate(
            service,
            _request(repo),
            user_id="local_user",
            delegation_events=port,
            cancellation=cancellation,
        )
    )
    await asyncio.wait_for(adapter_started.wait(), timeout=2)
    cancellation.cancel("background_task_cancelled")
    result = await asyncio.wait_for(task, timeout=2)

    assert result.cancelled is True
    assert "background_task_cancelled" in (result.error or "")
    assert port.state_summaries[-1] == ("cancelled", result.model_dump())
