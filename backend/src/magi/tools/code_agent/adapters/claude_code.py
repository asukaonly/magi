"""Adapter for the Claude Code CLI (``claude -p``).

Spawns the binary in headless stream-json mode, parses each JSONL event
into a typed ``RunEvent``, persists raw stdout/stderr, and extracts the
final assistant text + cost from the transcript for the service.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ..contracts import (
    AdapterName,
    CostInfo,
    DelegateRequest,
    ProbeResult,
    RunEvent,
)
from ..probe import probe_one
from .base import AdapterRunOutcome, CancelToken, OnEvent


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
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=self._build_env(),
        )

        prompt_blob = self._compose_stdin(req)
        try:
            assert process.stdin is not None
            process.stdin.write(prompt_blob.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

        stdout_buf: list[bytes] = []
        stderr_buf: list[bytes] = []
        last_assistant_text: Optional[str] = None
        cost_usd: Optional[float] = None
        cost_in: Optional[int] = None
        cost_out: Optional[int] = None

        async def _drain_stdout() -> None:
            nonlocal last_assistant_text, cost_usd, cost_in, cost_out
            assert process.stdout is not None
            async for raw in process.stdout:
                stdout_buf.append(raw)
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    await on_event(RunEvent(
                        kind="stdout", ts_ms=int(time.time() * 1000),
                        payload={"line": line},
                    ))
                    continue
                if not isinstance(obj, dict):
                    continue
                event_type = str(obj.get("type") or "")
                if event_type == "assistant":
                    text = self._extract_assistant_text(obj)
                    if text:
                        last_assistant_text = text
                        await on_event(RunEvent(
                            kind="assistant_text",
                            ts_ms=int(time.time() * 1000),
                            payload={"text": text},
                        ))
                elif event_type == "result":
                    if "total_cost_usd" in obj:
                        try:
                            cost_usd = float(obj["total_cost_usd"])
                        except (TypeError, ValueError):
                            pass
                    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
                    if usage:
                        cost_in = self._coerce_int(usage.get("input_tokens"))
                        cost_out = self._coerce_int(usage.get("output_tokens"))
                    await on_event(RunEvent(
                        kind="status",
                        ts_ms=int(time.time() * 1000),
                        payload={"event": "result", "raw": obj},
                    ))
                else:
                    await on_event(RunEvent(
                        kind="status",
                        ts_ms=int(time.time() * 1000),
                        payload={"event": event_type or "unknown", "raw": obj},
                    ))

        async def _drain_stderr() -> None:
            assert process.stderr is not None
            async for raw in process.stderr:
                stderr_buf.append(raw)

        try:
            await asyncio.wait_for(
                asyncio.gather(_drain_stdout(), _drain_stderr()),
                timeout=req.timeout_s,
            )
            exit_code = await process.wait()
        except asyncio.TimeoutError:
            await self._terminate(process)
            self._persist(stdout_path, stdout_buf)
            self._persist(stderr_path, stderr_buf)
            return AdapterRunOutcome(
                exit_code=-1,
                summary=None,
                cost=self._cost_or_none(cost_usd, cost_in, cost_out),
                error=f"adapter timeout after {req.timeout_s}s",
            )

        if cancel_token.cancelled:
            await self._terminate(process)

        self._persist(stdout_path, stdout_buf)
        self._persist(stderr_path, stderr_buf)

        cost = self._cost_or_none(cost_usd, cost_in, cost_out)
        if exit_code != 0:
            stderr_tail = _stderr_tail(stderr_buf)
            error_message = (
                f"adapter exited with code {exit_code}: {stderr_tail}"
                if stderr_tail
                else f"adapter exited with code {exit_code}"
            )
            await on_event(RunEvent(
                kind="error",
                ts_ms=int(time.time() * 1000),
                payload={"message": error_message, "stderr_tail": stderr_tail},
            ))
            return AdapterRunOutcome(
                exit_code=exit_code,
                summary=last_assistant_text,
                cost=cost,
                error=error_message,
            )
        return AdapterRunOutcome(
            exit_code=exit_code,
            summary=last_assistant_text,
            cost=cost,
            error=None,
        )

    def _build_argv(self, req: DelegateRequest, *, bundle_dir: Path, binary_path: str) -> list[str]:
        argv: list[str] = [
            binary_path, "-p",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode", "acceptEdits",
            "--bare",
            "--session-id", _format_uuid(req.delegation_id),
            "--add-dir", str(bundle_dir),
            "--input-format", "text",
        ]
        constraints_text = self._render_constraints(req)
        if constraints_text:
            argv += ["--append-system-prompt", constraints_text]
        if req.constraints.max_budget_usd is not None:
            argv += ["--max-budget-usd", str(req.constraints.max_budget_usd)]
        if req.model:
            argv += ["--model", req.model]
        return argv

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _compose_stdin(self, req: DelegateRequest) -> str:
        bundle_hint = (
            "Read TASK.md and CONSTRAINTS.md from the directory I added before "
            "starting; treat them as authoritative."
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
    def _cost_or_none(usd: Optional[float], inp: Optional[int], out: Optional[int]) -> Optional[CostInfo]:
        if usd is None and inp is None and out is None:
            return None
        return CostInfo(usd=usd, input_tokens=inp, output_tokens=out)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except ProcessLookupError:
            pass

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
