"""Adapter for the Claude Code CLI (``claude -p``).

Spawns the binary in headless stream-json mode, parses each JSONL event
into a typed ``RunEvent``, persists raw stdout/stderr, and extracts the
final assistant text + cost from the transcript for the service. Session
persistence is disabled so Magi remains the only owner of delegated context.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from magi_plugin_sdk.subprocess import ManagedSubprocess

from ..contracts import (
    AdapterName,
    CostInfo,
    DelegateRequest,
    ProbeResult,
    RunEvent,
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
class _ClaudeRunState:
    stdout_buf: list[bytes]
    stderr_buf: list[bytes]
    last_assistant_text: Optional[str] = None
    cost_usd: Optional[float] = None
    cost_in: Optional[int] = None
    cost_out: Optional[int] = None


class ClaudeCodeAdapter:
    name: AdapterName = "claude_code"
    display_name: str = "Claude Code"

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
        argv = self._build_argv(req, bundle_dir=bundle_dir, binary_path=binary_path)
        spawned = await self._spawn_process(
            req=req,
            cwd=cwd,
            argv=argv,
            binary_path=binary_path,
        )
        state = _ClaudeRunState(stdout_buf=[], stderr_buf=[])
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
                summary=None,
                cost=self._state_cost_or_none(state),
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
                summary=state.last_assistant_text,
                cost=self._state_cost_or_none(state),
                error=f"adapter cancelled: {reason}",
                cancelled=True,
            )
        if exit_code is None:  # pragma: no cover - guarded by helper contract
            raise RuntimeError("Claude Code adapter exited without a status")
        return await self._outcome_from_exit_code(exit_code, state, on_event)

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
            label=f"code_agent.claude_code.{req.delegation_id}",
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
        prompt_blob = self._compose_stdin(req)
        try:
            assert process.stdin is not None
            process.stdin.write(prompt_blob.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def _drain_until_exit(
        self,
        req: DelegateRequest,
        spawned: _SpawnedProcess,
        state: _ClaudeRunState,
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
        state: _ClaudeRunState,
        on_event: OnEvent,
    ) -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            state.stdout_buf.append(raw)
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                await self._handle_stdout_line(line, state, on_event)

    async def _handle_stdout_line(
        self,
        line: str,
        state: _ClaudeRunState,
        on_event: OnEvent,
    ) -> None:
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
        event_type = str(obj.get("type") or "")
        if event_type in ("stream_event", "user", "system"):
            return
        if event_type == "assistant":
            await self._handle_assistant_event(obj, state, on_event)
        elif event_type == "result":
            await self._handle_result_event(obj, state, on_event)
        else:
            await on_event(
                RunEvent(
                    kind="status",
                    ts_ms=int(time.time() * 1000),
                    payload={"event": event_type or "unknown", "raw": obj},
                )
            )

    async def _handle_assistant_event(
        self,
        obj: dict[str, Any],
        state: _ClaudeRunState,
        on_event: OnEvent,
    ) -> None:
        text = self._extract_assistant_text(obj)
        if not text:
            return
        state.last_assistant_text = text
        await on_event(
            RunEvent(
                kind="assistant_text",
                ts_ms=int(time.time() * 1000),
                payload={"text": text},
            )
        )

    async def _handle_result_event(
        self,
        obj: dict[str, Any],
        state: _ClaudeRunState,
        on_event: OnEvent,
    ) -> None:
        if "total_cost_usd" in obj:
            try:
                state.cost_usd = float(obj["total_cost_usd"])
            except (TypeError, ValueError):
                pass
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
        if usage:
            state.cost_in = self._coerce_int(usage.get("input_tokens"))
            state.cost_out = self._coerce_int(usage.get("output_tokens"))
        await on_event(
            RunEvent(
                kind="status",
                ts_ms=int(time.time() * 1000),
                payload={"event": "result", "raw": obj},
            )
        )

    @staticmethod
    async def _drain_stderr(
        process: asyncio.subprocess.Process,
        state: _ClaudeRunState,
    ) -> None:
        assert process.stderr is not None
        async for raw in process.stderr:
            state.stderr_buf.append(raw)

    def _persist_logs(
        self,
        stdout_path: Path,
        stderr_path: Path,
        state: _ClaudeRunState,
    ) -> None:
        self._persist(stdout_path, state.stdout_buf)
        self._persist(stderr_path, state.stderr_buf)

    async def _outcome_from_exit_code(
        self,
        exit_code: int,
        state: _ClaudeRunState,
        on_event: OnEvent,
    ) -> AdapterRunOutcome:
        cost = self._state_cost_or_none(state)
        if exit_code != 0:
            stderr_tail = _stderr_tail(state.stderr_buf)
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
                summary=state.last_assistant_text,
                cost=cost,
                error=error_message,
            )
        return AdapterRunOutcome(
            exit_code=exit_code,
            summary=state.last_assistant_text,
            cost=cost,
            error=None,
        )

    def _state_cost_or_none(self, state: _ClaudeRunState) -> CostInfo | None:
        return self._cost_or_none(state.cost_usd, state.cost_in, state.cost_out)

    def _build_argv(self, req: DelegateRequest, *, bundle_dir: Path, binary_path: str) -> list[str]:
        argv: list[str] = [
            binary_path,
            "-p",
            "--no-session-persistence",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--bare",
            "--session-id",
            _format_uuid(req.delegation_id),
            "--add-dir",
            str(bundle_dir),
            "--input-format",
            "text",
        ]
        constraints_text = self._render_constraints(req)
        if constraints_text:
            argv += ["--append-system-prompt", constraints_text]
        if req.constraints.max_budget_usd is not None:
            argv += ["--max-budget-usd", str(req.constraints.max_budget_usd)]
        if req.model:
            argv += ["--model", req.model]
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
        return f"{bundle_hint}\n\n{req.prompt}\n"

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
    def _extract_assistant_text(obj: dict[str, Any]) -> Optional[str]:
        msg = obj.get("message")
        if not isinstance(msg, dict):
            return None
        content = msg.get("content")
        if not isinstance(content, list):
            return None
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                txt = part.get("text")
                if isinstance(txt, str):
                    chunks.append(txt)
        return "\n".join(chunks).strip() or None

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _cost_or_none(
        usd: Optional[float], inp: Optional[int], out: Optional[int]
    ) -> Optional[CostInfo]:
        if usd is None and inp is None and out is None:
            return None
        return CostInfo(usd=usd, input_tokens=inp, output_tokens=out)

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


__all__ = ["ClaudeCodeAdapter"]


def _format_uuid(delegation_id: str) -> str:
    """Render a 32-char hex delegation id as canonical 8-4-4-4-12 UUID."""
    try:
        return str(uuid.UUID(delegation_id))
    except (ValueError, AttributeError):
        return delegation_id


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
