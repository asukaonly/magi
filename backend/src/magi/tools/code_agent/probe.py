"""Probe ``claude`` / ``codex`` binaries for availability and version.

Strategy:
1. If ``binary_path_override`` is given, probe that exact path.
2. Else look on ``PATH`` first (cheap), then a hardcoded list of common
   install locations on macOS / Linux / Windows.
3. Run ``<binary> --version`` with a 5 s timeout; capture stdout.

A 24 h cache lives at ``~/.magi/code_agent_probe.json``. ``probe_all(force=False)``
returns the cached result when fresh; ``force=True`` re-probes.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from magi_plugin_sdk.subprocess import hidden_process_kwargs
from .contracts import AdapterName, ProbeResult
from ._user_paths import code_agent_probe_cache_path
from .runtime_env import build_exec_env
from magi_plugin_sdk.fs import atomic_write_text


PROBE_TIMEOUT_S = 5
PROBE_CACHE_TTL_S = 24 * 60 * 60


_BINARY_NAME: dict[AdapterName, str] = {
    "claude_code": "claude",
    "codex": "codex",
}


def _fallback_dirs() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = [
        home / ".local" / "bin",
        home / ".cargo" / "bin",
        home / ".codex" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]
    nvm_root = home / ".nvm" / "versions" / "node"
    if nvm_root.is_dir():
        for child in nvm_root.iterdir():
            if child.is_dir():
                bin_dir = child / "bin"
                if bin_dir.is_dir():
                    candidates.append(bin_dir)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm")
    return [p for p in candidates if p.is_dir()]


def _which_with_fallback(name: str) -> Optional[Path]:
    direct = shutil.which(name)
    if direct:
        return Path(direct).resolve()
    suffixes = (".exe", ".cmd", ".bat") if sys.platform == "win32" else ("",)
    for d in _fallback_dirs():
        for suf in suffixes:
            cand = d / (name + suf)
            if cand.is_file():
                return cand.resolve()
    return None


def probe_one(
    adapter: AdapterName,
    *,
    binary_path_override: Optional[str] = None,
) -> ProbeResult:
    detected_at = int(time.time() * 1000)
    binary_name = _BINARY_NAME[adapter]
    binary: Optional[Path] = None
    if binary_path_override:
        cand = Path(binary_path_override).expanduser()
        if cand.is_file():
            binary = cand.resolve()
    if binary is None:
        binary = _which_with_fallback(binary_name)
    if binary is None:
        return ProbeResult(
            name=adapter,
            installed=False,
            binary_path=None,
            version=None,
            detected_at=detected_at,
            error=f"{binary_name} not found on PATH or fallback locations",
            extras={},
        )

    try:
        proc = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            env=build_exec_env(binary),
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(
            name=adapter, installed=True, binary_path=str(binary),
            version=None, detected_at=detected_at,
            error=f"--version probe timeout after {PROBE_TIMEOUT_S}s",
            extras={},
        )
    except OSError as exc:
        return ProbeResult(
            name=adapter, installed=True, binary_path=str(binary),
            version=None, detected_at=detected_at,
            error=f"failed to invoke binary: {exc}",
            extras={},
        )

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    version = stdout.splitlines()[0] if stdout else None
    if proc.returncode != 0:
        return ProbeResult(
            name=adapter, installed=True, binary_path=str(binary),
            version=None, detected_at=detected_at,
            error=f"--version exit={proc.returncode}: {stderr or stdout}",
            extras={},
        )
    return ProbeResult(
        name=adapter, installed=True, binary_path=str(binary),
        version=version, detected_at=detected_at, error=None, extras={},
    )


def save_probe_cache(results: dict[AdapterName, ProbeResult]) -> None:
    payload = {name: r.model_dump() for name, r in results.items()}
    atomic_write_text(code_agent_probe_cache_path(), json.dumps(payload))


def load_probe_cache() -> Optional[dict[AdapterName, ProbeResult]]:
    path = code_agent_probe_cache_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    out: dict[AdapterName, ProbeResult] = {}
    for name in ("claude_code", "codex"):
        entry = raw.get(name)
        if not isinstance(entry, dict):
            return None
        try:
            out[name] = ProbeResult.model_validate(entry)
        except Exception:
            return None
    return out


def _cache_is_fresh(results: dict[AdapterName, ProbeResult]) -> bool:
    now_ms = int(time.time() * 1000)
    ttl_ms = PROBE_CACHE_TTL_S * 1000
    return all(now_ms - r.detected_at <= ttl_ms for r in results.values())


def probe_all(*, force: bool = False) -> dict[AdapterName, ProbeResult]:
    if not force:
        cached = load_probe_cache()
        if cached is not None and _cache_is_fresh(cached):
            return cached
    out: dict[AdapterName, ProbeResult] = {
        "claude_code": probe_one("claude_code"),
        "codex": probe_one("codex"),
    }
    save_probe_cache(out)
    return out


__all__ = [
    "PROBE_TIMEOUT_S",
    "PROBE_CACHE_TTL_S",
    "probe_one",
    "probe_all",
    "load_probe_cache",
    "save_probe_cache",
]
