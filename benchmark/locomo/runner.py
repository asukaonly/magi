"""Shared utilities for LoCoMo benchmark scripts."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for candidate in (REPO_ROOT, BACKEND_SRC):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)


DEFAULT_LOCOMO_ROOT = REPO_ROOT.parent / "locomo"


def format_run_id(now: datetime | None = None) -> str:
    moment = now or datetime.now()
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def resolve_locomo_root() -> Path:
    env_value = os.getenv("LOCOMO_ROOT")
    if env_value:
        path = Path(env_value).expanduser()
        if path.exists():
            return path
    if DEFAULT_LOCOMO_ROOT.exists():
        return DEFAULT_LOCOMO_ROOT
    raise FileNotFoundError(
        "LoCoMo root not found. Set LOCOMO_ROOT or clone "
        f"https://github.com/snap-research/locomo to {DEFAULT_LOCOMO_ROOT}."
    )


def resolve_locomo_dataset(dataset_path: str | Path | None = None) -> Path:
    if dataset_path is not None:
        return Path(dataset_path).expanduser()
    return resolve_locomo_root() / "data" / "locomo10.json"


def load_locomo_samples(dataset_path: str | Path | None = None, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = resolve_locomo_dataset(dataset_path)
    samples = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(samples, list):
        raise ValueError("LoCoMo dataset must be a JSON list.")
    rows = [dict(sample) for sample in samples]
    if limit is not None:
        return rows[:limit]
    return rows


def apply_qa_limit(samples: Sequence[dict[str, Any]], *, qa_limit: int | None = None) -> list[dict[str, Any]]:
    """Return samples with each conversation's QA list limited to ``qa_limit``."""
    if qa_limit is None:
        return [dict(sample) for sample in samples]
    if qa_limit < 0:
        raise ValueError("qa_limit must be non-negative")

    limited_samples: list[dict[str, Any]] = []
    for sample in samples:
        limited = dict(sample)
        limited["qa"] = list(sample.get("qa") or [])[:qa_limit]
        limited_samples.append(limited)
    return limited_samples


def synthesize_locomo_hypothesis(
    *,
    answer: str | None,
    hits: Sequence[Any],
    category: int,
    fallback: str = "unknown",
    max_hits: int = 3,
) -> str:
    if answer:
        text = str(answer).strip()
        if text:
            return _normalize_adversarial_hypothesis(text, category=category)

    snippets: list[str] = []
    for hit in hits[:max_hits]:
        content = str(getattr(hit, "content", "") or "").strip()
        if content:
            snippets.append(content)
    hypothesis = "\n".join(snippets) if snippets else fallback
    return _normalize_adversarial_hypothesis(hypothesis, category=category)


def _normalize_adversarial_hypothesis(text: str, *, category: int) -> str:
    if int(category) != 5:
        return text
    lowered = text.lower()
    if lowered in {"unknown", "cannot determine", "cannot be determined"}:
        return "No information available"
    return text


__all__ = [
    "DEFAULT_LOCOMO_ROOT",
    "apply_qa_limit",
    "format_run_id",
    "load_locomo_samples",
    "resolve_locomo_dataset",
    "resolve_locomo_root",
    "synthesize_locomo_hypothesis",
]
