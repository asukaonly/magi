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
from pathlib import Path
from typing import Optional

from ..contracts import (
    AdapterName,
    DelegateRequest,
    ProbeResult,
    RunEvent,
)
from ..probe import probe_one
from .base import AdapterRunOutcome, CancelToken, OnEvent


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
        )
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=self._build_env(),
        )
        try:
            assert process.stdin is not None
            process.stdin.write(self._compose_stdin(req).encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

        stdout_buf: list[bytes] = []
        stderr_buf: list[bytes] = []

        async def _drain_stdout() -> None:
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
                etype = str(obj.get("type") or "")
                kind = "assistant_text" if etype == "agent_message" else "status"
                await on_event(RunEvent(
                    kind=kind,
                    ts_ms=int(time.time() * 1000),
                    payload={"event": etype or "unknown", "raw": obj},
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
                summary=self._read_last_message(last_message_path),
                cost=None,
                error=f"adapter timeout after {req.timeout_s}s",
            )

        if cancel_token.cancelled:
            await self._terminate(process)

        self._persist(stdout_path, stdout_buf)
        self._persist(stderr_path, stderr_buf)
        summary = self._read_last_message(last_message_path)

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
    ) -> list[str]:
        argv: list[str] = [
            binary_path, "exec",
            "--json",
            "--sandbox", "workspace-write",
            "--ask-for-approval", "never",
            "--cd", str(req.workspace_root),
            "--add-dir", str(bundle_dir),
            "--skip-git-repo-check",
            "-o", str(last_message_path),
        ]
        if req.model:
            argv += ["--model", req.model]
        argv.append("-")
        return argv

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
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
