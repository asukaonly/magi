#!/usr/bin/env python3
"""Require immutable commit pins for third-party GitHub Actions."""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
USES_PATTERN = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
COMMIT_PIN_PATTERN = re.compile(r"^[^/@\s]+/[^@\s]+@(?P<sha>[0-9a-f]{40})$")


def unpinned_actions(workflow_dir: Path = WORKFLOW_DIR) -> list[str]:
    """Return stable file-and-action descriptions for every mutable reference."""
    failures: list[str] = []
    for path in sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"))):
        content = path.read_text(encoding="utf-8")
        for match in USES_PATTERN.finditer(content):
            action = match.group(1)
            if action.startswith("./") or COMMIT_PIN_PATTERN.fullmatch(action):
                continue
            line = content.count("\n", 0, match.start()) + 1
            failures.append(f"{path.relative_to(ROOT)}:{line}: {action}")
    return failures


def main() -> int:
    failures = unpinned_actions()
    if not failures:
        print("All third-party GitHub Actions use immutable commit pins.")
        return 0
    print("Mutable GitHub Action references are not allowed:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
