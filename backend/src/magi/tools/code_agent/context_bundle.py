"""Generate the context bundle handed to an external coding CLI.

Bundle layout (under ``<delegation_dir>/_bundle/``):

* ``TASK.md`` - the prompt verbatim plus the file hint list.
* ``RELEVANT_FILES.txt`` - newline-separated file paths the external
  agent should look at first; sensitive paths (env files, keys, secrets,
  credentials) are removed and reported via ``WrittenBundle.dropped``.
* ``CONSTRAINTS.md`` - human-readable summary of ``DelegateConstraints``,
  intended for the external agent's ``--add-dir`` so it can read it.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import DelegateConstraints
from ...agent.workspace_cache.atomic_io import atomic_write_text


_SENSITIVE_PATTERNS: tuple[str, ...] = (
    "*.env", ".env*", "*.pem", "id_rsa*", "*credentials*",
    "*secret*", ".npmrc", ".netrc", "*.key",
)


def is_sensitive_path(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    for pattern in _SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern.lower()):
            return True
        if fnmatch.fnmatch(p, pattern.lower()):
            return True
    return False


@dataclass(frozen=True)
class WrittenBundle:
    bundle_dir: Path
    task_md: Path
    relevant_files_txt: Path
    constraints_md: Path
    dropped: list[str] = field(default_factory=list)


@dataclass
class ContextBundle:
    bundle_dir: Path
    prompt: str
    files_hint: list[str]
    constraints: DelegateConstraints

    def write(self) -> WrittenBundle:
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        kept, dropped = self._partition_paths()
        task_md = self.bundle_dir / "TASK.md"
        relevant = self.bundle_dir / "RELEVANT_FILES.txt"
        constraints = self.bundle_dir / "CONSTRAINTS.md"
        atomic_write_text(task_md, self._render_task_md(kept))
        atomic_write_text(relevant, "\n".join(kept) + ("\n" if kept else ""))
        atomic_write_text(constraints, self._render_constraints_md())
        return WrittenBundle(
            bundle_dir=self.bundle_dir,
            task_md=task_md,
            relevant_files_txt=relevant,
            constraints_md=constraints,
            dropped=dropped,
        )

    def _partition_paths(self) -> tuple[list[str], list[str]]:
        kept: list[str] = []
        dropped: list[str] = []
        for raw in self.files_hint:
            p = str(raw).strip()
            if not p:
                continue
            if is_sensitive_path(p):
                dropped.append(p)
            else:
                kept.append(p)
        return kept, dropped

    def _render_task_md(self, kept: list[str]) -> str:
        lines = ["# Task", "", self.prompt.strip(), "", "## Relevant files"]
        if kept:
            for p in kept:
                lines.append(f"- {p}")
        else:
            lines.append("(none specified)")
        return "\n".join(lines) + "\n"

    def _render_constraints_md(self) -> str:
        lines = ["# Constraints", ""]
        if self.constraints.forbid_git_commit:
            lines.append("- Do not run git commit.")
        if self.constraints.forbid_git_push:
            lines.append("- Do not run git push.")
        if self.constraints.forbid_network:
            lines.append(
                "- Avoid network access; this delegation runs in a network-restricted context."
            )
        if self.constraints.forbid_paths:
            lines.append("- Do not read or modify these paths:")
            for p in self.constraints.forbid_paths:
                lines.append(f"  - `{p}`")
        if self.constraints.max_budget_usd is not None:
            lines.append(f"- Hard budget: ${self.constraints.max_budget_usd:.2f}.")
        return "\n".join(lines) + "\n"


__all__ = ["ContextBundle", "WrittenBundle", "is_sensitive_path"]
