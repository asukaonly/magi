"""Every builtin persona seed must declare portrait cold-start lines.

The chat-shell portrait rail uses persona-specific cold-start copy when a
session has no relevant L2/L3/L4 memories yet. Each builtin persona owns
this surface, so the seed JSON is the source of truth.
"""

import json
from pathlib import Path


SEED_ROOT = Path(__file__).resolve().parent.parent.parent / "personalities"


def _all_seed_files() -> list[Path]:
    return sorted(SEED_ROOT.glob("*/*.json"))


def test_seed_root_exists():
    assert SEED_ROOT.is_dir(), f"seed root missing: {SEED_ROOT}"


def test_all_builtin_personas_have_portrait_cold_start_lines():
    files = _all_seed_files()
    assert files, "no persona seed files found"
    missing: list[str] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        interim = data.get("interim_lines") or {}
        lines = interim.get("portrait_cold_start") or []
        if not (isinstance(lines, list) and any(str(line).strip() for line in lines)):
            missing.append(path.name)
    assert not missing, (
        "personas missing interim_lines.portrait_cold_start: " + ", ".join(missing)
    )
