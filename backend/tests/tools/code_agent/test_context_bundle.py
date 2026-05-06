"""Tests for code_agent context bundle generation."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.code_agent.context_bundle import (
    ContextBundle,
    is_sensitive_path,
)
from magi.tools.code_agent.contracts import DelegateConstraints


def test_is_sensitive_path_matches_envs_and_keys() -> None:
    for p in [".env", ".env.local", "src/.env.production",
              "secrets/db.pem", "id_rsa", "id_rsa.pub",
              "config.key", "AWS_credentials"]:
        assert is_sensitive_path(p), p


def test_is_sensitive_path_rejects_normal_files() -> None:
    for p in ["src/foo.py", "README.md", "package.json", "pyproject.toml"]:
        assert not is_sensitive_path(p), p


def test_bundle_writes_three_files(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "_bundle"
    bundle = ContextBundle(
        bundle_dir=bundle_dir,
        prompt="add max_retries to connect()",
        files_hint=["src/net.py", "tests/test_net.py"],
        constraints=DelegateConstraints(),
    )
    written = bundle.write()
    assert written.task_md.is_file()
    assert written.relevant_files_txt.is_file()
    assert written.constraints_md.is_file()
    assert "add max_retries" in written.task_md.read_text()
    assert "src/net.py" in written.relevant_files_txt.read_text()
    body = written.constraints_md.read_text().lower()
    assert "git push" in body or "do not commit" in body


def test_bundle_filters_sensitive_paths(tmp_path: Path) -> None:
    bundle = ContextBundle(
        bundle_dir=tmp_path / "_bundle",
        prompt="x",
        files_hint=["src/foo.py", ".env", "secrets/db.pem", "README.md"],
        constraints=DelegateConstraints(),
    )
    written = bundle.write()
    listed = written.relevant_files_txt.read_text().splitlines()
    assert "src/foo.py" in listed
    assert "README.md" in listed
    assert ".env" not in listed
    assert "secrets/db.pem" not in listed
    assert written.dropped == [".env", "secrets/db.pem"]


def test_bundle_constraints_md_reflects_settings(tmp_path: Path) -> None:
    bundle = ContextBundle(
        bundle_dir=tmp_path / "_bundle",
        prompt="x",
        files_hint=[],
        constraints=DelegateConstraints(
            forbid_paths=["weird/path"],
            forbid_git_commit=True,
            forbid_git_push=True,
            forbid_network=True,
        ),
    )
    written = bundle.write()
    body = written.constraints_md.read_text()
    assert "weird/path" in body
    assert "network" in body.lower()


def test_bundle_idempotent(tmp_path: Path) -> None:
    bundle = ContextBundle(
        bundle_dir=tmp_path / "_bundle",
        prompt="x",
        files_hint=["a.py"],
        constraints=DelegateConstraints(),
    )
    bundle.write()
    bundle.write()
    assert (tmp_path / "_bundle" / "TASK.md").is_file()
