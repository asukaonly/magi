"""Collect ``git diff`` and ``git status`` from a worktree."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .contracts import DiffSnapshot, DiffStats


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
    )


def _parse_stats(unified_diff: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in unified_diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def collect_diff(worktree_path: Path) -> DiffSnapshot:
    worktree_path = Path(worktree_path).resolve()
    status_proc = _run_git(["status", "--porcelain"], cwd=worktree_path)
    untracked_proc = _run_git(
        ["ls-files", "--others", "--exclude-standard", "-z"],
        cwd=worktree_path,
    )
    if untracked_proc.returncode == 0:
        untracked_files = [
            path
            for path in untracked_proc.stdout.split("\0")
            if path
        ]
        if untracked_files:
            _run_git(
                ["add", "--intent-to-add", "--", *untracked_files],
                cwd=worktree_path,
            )
    diff_proc = _run_git(["diff", "--binary", "HEAD"], cwd=worktree_path)
    names_proc = _run_git(
        ["diff", "--name-only", "-z", "HEAD"],
        cwd=worktree_path,
    )
    if diff_proc.returncode != 0 and status_proc.returncode != 0:
        return DiffSnapshot(
            stats=DiffStats(),
            files_changed=[],
            unified_diff="",
            status_porcelain="",
        )
    unified = diff_proc.stdout if diff_proc.returncode == 0 else ""
    porcelain = status_proc.stdout if status_proc.returncode == 0 else ""
    files_changed = (
        [path for path in names_proc.stdout.split("\0") if path]
        if names_proc.returncode == 0
        else []
    )
    additions, deletions = _parse_stats(unified)
    return DiffSnapshot(
        stats=DiffStats(
            files_changed=len(files_changed),
            additions=additions,
            deletions=deletions,
        ),
        files_changed=files_changed,
        unified_diff=unified,
        status_porcelain=porcelain,
    )


__all__ = ["collect_diff"]
