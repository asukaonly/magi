"""Adapter for the Codex CLI (``codex exec --json ...``).

Codex emits ``--json`` JSONL events on stdout. The "final assistant message"
isn't always cleanly tagged, so we use ``-o <path>`` to redirect it to a file
and read the file at the end. Cost is not reliably present in the JSONL
stream and is left as None.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from magi_plugin_sdk.subprocess import ManagedSubprocess

from ..contracts import (
    AdapterName,
    DelegateRequest,
    ProbeResult,
    RunEvent,
    RunEventKind,
)
from ..probe import probe_one
from ..runtime_env import build_exec_env
from .base import (
    AdapterRunOutcome,
    CancelToken,
    OnEvent,
    wait_for_run_or_cancel,
)


@dataclass
class _SpawnedProcess:
    process: asyncio.subprocess.Process
    managed: ManagedSubprocess


@dataclass
class _CodexRunState:
    stdout_buf: list[bytes]
    stderr_buf: list[bytes]


class CodexAdapter:
    name: AdapterName = "codex"
    display_name: str = "Codex"

    @classmethod
    async def detect(cls) -> ProbeResult:
        return probe_one(cls.name)

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
        last_message_path = stdout_path.parent / "codex_last_message.txt"
        last_message_path.parent.mkdir(parents=True, exist_ok=True)
        argv = self._build_argv(
            req,
            bundle_dir=bundle_dir,
            binary_path=binary_path,
            last_message_path=last_message_path,
            working_directory=cwd,
        )
        spawned = await self._spawn_process(
            req=req,
            cwd=cwd,
            argv=argv,
            binary_path=binary_path,
        )
        state = _CodexRunState(stdout_buf=[], stderr_buf=[])
        try:
            await self._write_prompt(spawned.process, req)
            exit_code, cancelled = await wait_for_run_or_cancel(
                self._drain_until_exit(req, spawned, state, on_event),
                cancel_token=cancel_token,
                terminate=lambda: self._terminate(
                    spawned.process,
                    managed=spawned.managed,
                ),
            )
        except asyncio.TimeoutError:
            return AdapterRunOutcome(
                exit_code=-1,
                summary=self._read_last_message(last_message_path),
                cost=None,
                error=f"adapter timeout after {req.timeout_s}s",
            )
        except BaseException:
            await self._terminate(spawned.process, managed=spawned.managed)
            raise
        finally:
            self._persist_logs(stdout_path, stderr_path, state)

        if cancelled:
            reason = cancel_token.reason or "cancelled"
            return AdapterRunOutcome(
                exit_code=-1,
                summary=self._read_last_message(last_message_path),
                cost=None,
                error=f"adapter cancelled: {reason}",
                cancelled=True,
            )
        if exit_code is None:  # pragma: no cover - guarded by helper contract
            raise RuntimeError("Codex adapter exited without a status")
        summary = self._read_last_message(last_message_path)
        return await self._outcome_from_exit_code(
            exit_code,
            summary=summary,
            stderr_buf=state.stderr_buf,
            on_event=on_event,
        )

    async def _spawn_process(
        self,
        *,
        req: DelegateRequest,
        cwd: Path,
        argv: list[str],
        binary_path: str,
    ) -> _SpawnedProcess:
        managed = await ManagedSubprocess.spawn(
            argv,
            label=f"code_agent.codex.{req.delegation_id}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=self._build_env(binary_path),
        )
        return _SpawnedProcess(process=managed.proc, managed=managed)

    async def _write_prompt(
        self,
        process: asyncio.subprocess.Process,
        req: DelegateRequest,
    ) -> None:
        try:
            assert process.stdin is not None
            process.stdin.write(self._compose_stdin(req).encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def _drain_until_exit(
        self,
        req: DelegateRequest,
        spawned: _SpawnedProcess,
        state: _CodexRunState,
        on_event: OnEvent,
    ) -> int:
        await asyncio.wait_for(
            asyncio.gather(
                self._drain_stdout(spawned.process, state, on_event),
                self._drain_stderr(spawned.process, state),
            ),
            timeout=req.timeout_s,
        )
        return await spawned.managed.wait()

    async def _drain_stdout(
        self,
        process: asyncio.subprocess.Process,
        state: _CodexRunState,
        on_event: OnEvent,
    ) -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            state.stdout_buf.append(raw)
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                await self._handle_stdout_line(line, on_event)

    @staticmethod
    async def _handle_stdout_line(line: str, on_event: OnEvent) -> None:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            await on_event(
                RunEvent(
                    kind="stdout",
                    ts_ms=int(time.time() * 1000),
                    payload={"line": line},
                )
            )
            return
        if not isinstance(obj, dict):
            return
        etype = str(obj.get("type") or "")
        kind: RunEventKind = (
            "assistant_text" if etype == "agent_message" else "status"
        )
        await on_event(
            RunEvent(
                kind=kind,
                ts_ms=int(time.time() * 1000),
                payload={"event": etype or "unknown", "raw": obj},
            )
        )

    @staticmethod
    async def _drain_stderr(
        process: asyncio.subprocess.Process,
        state: _CodexRunState,
    ) -> None:
        assert process.stderr is not None
        async for raw in process.stderr:
            state.stderr_buf.append(raw)

    def _persist_logs(
        self,
        stdout_path: Path,
        stderr_path: Path,
        state: _CodexRunState,
    ) -> None:
        self._persist(stdout_path, state.stdout_buf)
        self._persist(stderr_path, state.stderr_buf)

    async def _outcome_from_exit_code(
        self,
        exit_code: int,
        *,
        summary: Optional[str],
        stderr_buf: list[bytes],
        on_event: OnEvent,
    ) -> AdapterRunOutcome:
        if exit_code != 0:
            stderr_tail = _stderr_tail(stderr_buf)
            error_message = (
                f"adapter exited with code {exit_code}: {stderr_tail}"
                if stderr_tail
                else f"adapter exited with code {exit_code}"
            )
            await on_event(
                RunEvent(
                    kind="error",
                    ts_ms=int(time.time() * 1000),
                    payload={"message": error_message, "stderr_tail": stderr_tail},
                )
            )
            return AdapterRunOutcome(
                exit_code=exit_code,
                summary=summary,
                cost=None,
                error=error_message,
            )
        return AdapterRunOutcome(
            exit_code=exit_code,
            summary=summary,
            cost=None,
            error=None,
        )

    def _build_argv(
        self,
        req: DelegateRequest,
        *,
        bundle_dir: Path,
        binary_path: str,
        last_message_path: Path,
        working_directory: Path,
    ) -> list[str]:
        argv: list[str] = [
            binary_path,
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "--cd",
            str(working_directory),
            "--add-dir",
            str(bundle_dir),
            "--skip-git-repo-check",
            "-o",
            str(last_message_path),
        ]
        if req.model:
            argv += ["--model", req.model]
        argv.append("-")
        return argv

    def _build_env(self, binary_path: str) -> dict[str, str]:
        env = build_exec_env(binary_path, base_env=os.environ.copy())
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _compose_stdin(self, req: DelegateRequest) -> str:
        bundle_hint = (
            "Read TASK.md and CONSTRAINTS.md from the directory I added before "
            "starting; treat them as authoritative.\n"
            "IMPORTANT: Your summary and final response MUST be in Chinese (简体中文). "
            "Code comments and variable names can remain in English, but explanations "
            "and summaries should be in Chinese."
        )
        constraints = self._render_constraints(req)
        return f"{bundle_hint}\n\n{constraints}\n\n{req.prompt}\n"

    @staticmethod
    def _render_constraints(req: DelegateRequest) -> str:
        parts: list[str] = []
        if req.constraints.forbid_git_commit:
            parts.append("Do not run git commit.")
        if req.constraints.forbid_git_push:
            parts.append("Do not run git push.")
        if req.constraints.forbid_paths:
            parts.append(
                "Do not read or modify these paths: "
                + ", ".join(req.constraints.forbid_paths)
                + "."
            )
        return " ".join(parts)

    @staticmethod
    def _read_last_message(path: Path) -> Optional[str]:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        return text or None

    @staticmethod
    async def _terminate(
        process: asyncio.subprocess.Process,
        *,
        managed: Any = None,
    ) -> None:
        if process.returncode is not None:
            if managed is not None:
                await managed.wait()
            return
        if managed is not None:
            try:
                await managed.shutdown(
                    sigterm_grace_seconds=1.0,
                    sigkill_grace_seconds=1.0,
                )
            except Exception:
                pass
            if process.returncode is not None:
                await managed.wait()
                return
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=2)
        except ProcessLookupError:
            await process.wait()

    @staticmethod
    def _persist(path: Path, chunks: list[bytes]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            for chunk in chunks:
                f.write(chunk)


__all__ = ["CodexAdapter"]


def _stderr_tail(chunks: list[bytes], max_chars: int = 200) -> str:
    if not chunks:
        return ""
    text = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    last = text.splitlines()[-1].strip()
    if len(last) > max_chars:
        last = last[:max_chars] + "…"
    return last
