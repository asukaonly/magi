"""Auto-detect: suggest batch_create when a listing surfaces many homogeneous items.

A glob/file_list that returns a large set of same-kind items is the signal to
batch (rather than loop one-by-one and hit the per-turn iteration cap). This is a
HINT generator — the agent still decides. It is task-agnostic (groups by file
extension) and pure (no I/O), so it unit-tests cleanly. The decision to attach
the hint to a tool's output (and the on/off gate) lives at the call site.
"""
from __future__ import annotations

import os
from collections import Counter

DEFAULT_THRESHOLD = 30


def suggest_batch(paths: "list[str]", *, threshold: int = DEFAULT_THRESHOLD) -> "str | None":
    """Return a one-line hint if ``paths`` contains a large homogeneous group
    (same file extension) at or above ``threshold``; otherwise None."""
    if len(paths) < threshold:
        return None
    exts = Counter(
        os.path.splitext(p)[1].lower()
        for p in paths
        if os.path.splitext(p)[1]
    )
    if not exts:
        return None
    top_ext, top_n = exts.most_common(1)[0]
    if top_n < threshold:
        return None
    return (
        f"{top_n} '{top_ext}' files here. For a repetitive operation over this "
        f"many similar items, prefer batch_create over processing them one-by-one "
        f"(one-by-one hits the per-turn iteration cap, can't resume on crash, and "
        f"re-prompts for permission each time)."
    )
