"""Helpers for preparing subprocess environments for external code-agent CLIs."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping


_ENV_NODE_SHEBANG_RE = re.compile(r"^#!\s*/usr/bin/env(?:\s+-S)?\s+node(?:\s|$)")


def _read_shebang(binary_path: Path) -> str:
    try:
        with binary_path.open("rb") as handle:
            first_line = handle.readline(256)
    except OSError:
        return ""
    return first_line.decode("utf-8", errors="ignore").strip()


def _uses_env_node_launcher(binary_path: Path) -> bool:
    return bool(_ENV_NODE_SHEBANG_RE.match(_read_shebang(binary_path)))


def discover_runtime_bin_dirs(binary_path: str | Path) -> list[str]:
    path = Path(binary_path).expanduser()
    if not _uses_env_node_launcher(path):
        return []

    node_names = ("node.exe", "node.cmd", "node.bat") if os.name == "nt" else ("node",)
    candidates: list[str] = []
    seen: set[str] = set()

    def add_if_has_node(bin_dir: Path) -> None:
        normalized = str(bin_dir)
        if normalized in seen:
            return
        if any((bin_dir / node_name).is_file() for node_name in node_names):
            seen.add(normalized)
            candidates.append(normalized)

    for parent in [path.parent, *path.parents]:
        add_if_has_node(parent)
        add_if_has_node(parent / "bin")

    return candidates


def build_exec_env(
    binary_path: str | Path,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    runtime_bin_dirs = discover_runtime_bin_dirs(binary_path)
    if not runtime_bin_dirs:
        return env

    existing_parts = [part for part in str(env.get("PATH") or "").split(os.pathsep) if part]
    merged_parts: list[str] = []
    seen: set[str] = set()
    for part in [*runtime_bin_dirs, *existing_parts]:
        if part in seen:
            continue
        seen.add(part)
        merged_parts.append(part)
    env["PATH"] = os.pathsep.join(merged_parts)
    return env


__all__ = ["build_exec_env", "discover_runtime_bin_dirs"]