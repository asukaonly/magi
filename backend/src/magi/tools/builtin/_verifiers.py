"""File-type-aware verifiers used by the verify tool.

Each verifier is a small async callable that takes a file path + timeout and
returns a ``VerifyOutcome``. The dispatch table maps file extensions to
verifiers; ``get_verifier_for(path)`` returns ``None`` for unsupported
extensions so the caller can record a ``skipped`` outcome.

Subprocess verifiers (``py_compile``, ``tsc``, ``node``) honour a per-call
timeout. Pure-Python verifiers (``json.loads``, ``tomllib.loads``) skip the
subprocess entirely and parse in-process for speed.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Awaitable, Callable, Literal, Optional

from magi_plugin_sdk.subprocess import hidden_process_kwargs
from .bash_tool import _build_subprocess_env, _decode_process_output_with_encoding


VerifyStatus = Literal["pass", "fail", "skipped", "timeout"]


@dataclass(frozen=True)
class VerifyOutcome:
    path: str
    verifier: str
    status: VerifyStatus
    exit_code: int
    stdout: str
    stderr: str
    reason: Optional[str]
    duration_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


VerifierFn = Callable[[Path, int], Awaitable[VerifyOutcome]]


async def _run_subprocess(
    label: str,
    argv: list[str],
    *,
    rel_path: str,
    timeout_s: int,
) -> VerifyOutcome:
    start = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_build_subprocess_env(),
            **hidden_process_kwargs(),
        )
    except FileNotFoundError:
        return VerifyOutcome(
            path=rel_path,
            verifier=label,
            status="skipped",
            exit_code=-1,
            stdout="",
            stderr="",
            reason=f"{argv[0]} not on PATH",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return VerifyOutcome(
            path=rel_path,
            verifier=label,
            status="timeout",
            exit_code=-1,
            stdout="",
            stderr="",
            reason=f"timeout after {timeout_s}s",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    out_text, _ = _decode_process_output_with_encoding(stdout) if stdout else ("", "utf-8")
    err_text, _ = _decode_process_output_with_encoding(stderr) if stderr else ("", "utf-8")
    code = process.returncode if process.returncode is not None else -1
    return VerifyOutcome(
        path=rel_path,
        verifier=label,
        status="pass" if code == 0 else "fail",
        exit_code=code,
        stdout=out_text,
        stderr=err_text,
        reason=None,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


async def _verify_python(path: Path, timeout_s: int) -> VerifyOutcome:
    return await _run_subprocess(
        "py_compile",
        [sys.executable, "-m", "py_compile", str(path)],
        rel_path=str(path),
        timeout_s=timeout_s,
    )


async def _verify_typescript(path: Path, timeout_s: int) -> VerifyOutcome:
    if shutil.which("tsc") is None:
        return VerifyOutcome(
            path=str(path),
            verifier="tsc",
            status="skipped",
            exit_code=-1,
            stdout="",
            stderr="",
            reason="tsc not on PATH",
            duration_ms=0,
        )
    return await _run_subprocess(
        "tsc",
        ["tsc", "--noEmit", "--pretty", "false", str(path)],
        rel_path=str(path),
        timeout_s=timeout_s,
    )


async def _verify_javascript(path: Path, timeout_s: int) -> VerifyOutcome:
    if shutil.which("node") is None:
        return VerifyOutcome(
            path=str(path),
            verifier="node --check",
            status="skipped",
            exit_code=-1,
            stdout="",
            stderr="",
            reason="node not on PATH",
            duration_ms=0,
        )
    return await _run_subprocess(
        "node --check",
        ["node", "--check", str(path)],
        rel_path=str(path),
        timeout_s=timeout_s,
    )


async def _verify_json(path: Path, timeout_s: int) -> VerifyOutcome:
    _ = timeout_s
    start = time.monotonic()
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return VerifyOutcome(
            path=str(path),
            verifier="json.loads",
            status="fail",
            exit_code=1,
            stdout="",
            stderr=str(exc),
            reason=None,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    return VerifyOutcome(
        path=str(path),
        verifier="json.loads",
        status="pass",
        exit_code=0,
        stdout="",
        stderr="",
        reason=None,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


async def _verify_toml(path: Path, timeout_s: int) -> VerifyOutcome:
    _ = timeout_s
    start = time.monotonic()
    try:
        if sys.version_info >= (3, 11):
            import tomllib  # type: ignore[import-not-found]
            tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            import tomli
            tomli.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return VerifyOutcome(
            path=str(path),
            verifier="tomllib.loads",
            status="fail",
            exit_code=1,
            stdout="",
            stderr=str(exc),
            reason=None,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    return VerifyOutcome(
        path=str(path),
        verifier="tomllib.loads",
        status="pass",
        exit_code=0,
        stdout="",
        stderr="",
        reason=None,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


_DISPATCH: dict[str, VerifierFn] = {
    ".py": _verify_python,
    ".ts": _verify_typescript,
    ".tsx": _verify_typescript,
    ".js": _verify_javascript,
    ".jsx": _verify_javascript,
    ".json": _verify_json,
    ".toml": _verify_toml,
}


def get_verifier_for(path: Path) -> VerifierFn | None:
    return _DISPATCH.get(path.suffix.lower())


async def verify_file(path: Path, *, timeout_s: int) -> VerifyOutcome:
    if not path.exists():
        return VerifyOutcome(
            path=str(path),
            verifier="(none)",
            status="skipped",
            exit_code=-1,
            stdout="",
            stderr="",
            reason="file does not exist",
            duration_ms=0,
        )
    fn = get_verifier_for(path)
    if fn is None:
        return VerifyOutcome(
            path=str(path),
            verifier="(none)",
            status="skipped",
            exit_code=-1,
            stdout="",
            stderr="",
            reason=f"no verifier for extension {path.suffix!r}",
            duration_ms=0,
        )
    return await fn(path, timeout_s)


__all__ = [
    "VerifyOutcome",
    "VerifyStatus",
    "VerifierFn",
    "get_verifier_for",
    "verify_file",
]
