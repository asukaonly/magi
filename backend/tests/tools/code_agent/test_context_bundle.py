"""Tests for code_agent context bundle generation."""
from __future__ import annotations

import pytest

from magi.tools.code_agent.context_bundle import (
    ContextBundle,
)
from magi.tools.code_agent.contracts import DelegateConstraints


def test_bundle_filters_sensitive_paths_and_keeps_normal_file_hints(tmp_path):
    allowed = ["src/foo.py", "README.md", "package.json", "pyproject.toml"]
    blocked = [
        ".env",
        ".env.local",
        "src/.env.production",
        "secrets/db.pem",
        "id_rsa",
        "id_rsa.pub",
        "config.key",
        "AWS_credentials",
    ]
    written = ContextBundle(
        bundle_dir=tmp_path / "_bundle",
        prompt="Review files",
        files_hint=allowed + blocked,
        constraints=DelegateConstraints(),
    ).write()
    assert written.relevant_files_txt.read_text().splitlines() == allowed
    assert written.dropped == blocked
    task = written.task_md.read_text()
    assert task == "# Task\n\nReview files\n\n## Relevant files\n" + "".join(
        f"- {path}\n" for path in allowed
    )


@pytest.mark.parametrize(
    "overrides,expected_rules",
    [
        ({}, ["- Do not run git commit.", "- Do not run git push."]),
        ({"forbid_git_commit": False}, ["- Do not run git push."]),
        ({"forbid_git_push": False}, ["- Do not run git commit."]),
        ({"forbid_git_commit": False, "forbid_git_push": False}, []),
        (
            {"forbid_network": True, "forbid_paths": ["weird/path"], "max_budget_usd": 2.5},
            [
                "- Do not run git commit.",
                "- Do not run git push.",
                "- Avoid network access; this delegation runs in a network-restricted context.",
                "- Do not read or modify these paths:",
                "  - `weird/path`",
                "- Hard budget: $2.50.",
            ],
        ),
    ],
)
def test_bundle_renders_only_enabled_restrictions(tmp_path, overrides, expected_rules):
    written = ContextBundle(
        bundle_dir=tmp_path / "_bundle",
        prompt="x",
        files_hint=[],
        constraints=DelegateConstraints(**overrides),
    ).write()
    assert written.constraints_md.read_text().splitlines() == ["# Constraints", "", *expected_rules]


def test_bundle_rewrites_exact_content_without_accumulating_previous_output(tmp_path):
    bundle = ContextBundle(
        bundle_dir=tmp_path / "_bundle",
        prompt="Review a",
        files_hint=["a.py"],
        constraints=DelegateConstraints(),
    )
    bundle.write()
    first = {path.name: path.read_bytes() for path in bundle.bundle_dir.iterdir()}
    assert set(first) == {"TASK.md", "RELEVANT_FILES.txt", "CONSTRAINTS.md"}
    bundle.write()
    assert {path.name: path.read_bytes() for path in bundle.bundle_dir.iterdir()} == first
    bundle.prompt = "Review b"
    bundle.files_hint = ["b.py"]
    bundle.constraints = DelegateConstraints(forbid_git_commit=False, forbid_git_push=False)
    bundle.write()
    assert {path.name: path.read_text() for path in bundle.bundle_dir.iterdir()} == {
        "TASK.md": "# Task\n\nReview b\n\n## Relevant files\n- b.py\n",
        "RELEVANT_FILES.txt": "b.py\n",
        "CONSTRAINTS.md": "# Constraints\n\n",
    }
