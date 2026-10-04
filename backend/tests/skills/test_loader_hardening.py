"""Regression tests for SKILL.md loader hardening.

Covers:

- The path-traversal guard on ``[](...)`` file references.
- The default-off behaviour of ``!`command``` auto-execution.
- The body size cap.
- The corrected ``yaml.YAMLError`` exception type.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from magi.skills.indexer import SkillIndexer
from magi.skills.loader import SkillLoader, MAX_SKILL_BODY_BYTES


def _write_skill(root: Path, name: str, body: str, frontmatter_extra: str = "") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill = skill_dir / "SKILL.md"
    extra_line = f"\n{frontmatter_extra}" if frontmatter_extra else ""
    skill.write_text(
        f"---\nname: {name}\ndescription: test{extra_line}\n---\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def loader_with_root(tmp_path):
    indexer = SkillIndexer(skill_locations=[tmp_path])
    yield tmp_path, indexer


def test_file_reference_inlines_when_inside_skill_dir(loader_with_root):
    root, indexer = loader_with_root
    skill_dir = _write_skill(root, "ok-skill", "See: [doc](allowed.txt)")
    (skill_dir / "allowed.txt").write_text("INSIDE", encoding="utf-8")

    indexer.scan_all()
    skill = SkillLoader(indexer).load_skill("ok-skill")
    assert skill is not None
    assert "INSIDE" in skill.prompt_template


def test_file_reference_rejected_on_traversal(loader_with_root, caplog):
    root, indexer = loader_with_root
    _write_skill(root, "traversal-skill", "See: [secret](../../etc/passwd)")
    indexer.scan_all()
    skill = SkillLoader(indexer).load_skill("traversal-skill")
    assert skill is not None
    # Literal markdown preserved, no file content embedded.
    assert "[secret](../../etc/passwd)" in skill.prompt_template
    assert "root:" not in skill.prompt_template


def test_file_reference_rejected_on_absolute_path(loader_with_root):
    root, indexer = loader_with_root
    _write_skill(root, "abs-skill", "See: [secret](/etc/passwd)")
    indexer.scan_all()
    skill = SkillLoader(indexer).load_skill("abs-skill")
    assert skill is not None
    assert "[secret](/etc/passwd)" in skill.prompt_template
    assert "root:" not in skill.prompt_template


def test_file_reference_rejected_on_symlink_escape(tmp_path, loader_with_root):
    root, indexer = loader_with_root
    skill_dir = _write_skill(root, "symlink-skill", "See: [bad](link)")

    outside = tmp_path.parent / f"outside_{os.getpid()}.txt"
    try:
        outside.write_text("EXFIL", encoding="utf-8")
        (skill_dir / "link").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    indexer.scan_all()
    skill = SkillLoader(indexer).load_skill("symlink-skill")
    try:
        assert skill is not None
        assert "EXFIL" not in skill.prompt_template
    finally:
        try:
            outside.unlink()
        except FileNotFoundError:
            pass


def test_command_resolution_disabled_by_default(loader_with_root, monkeypatch):
    monkeypatch.delenv("MAGI_SKILLS_ALLOW_COMMAND_RESOLUTION", raising=False)
    root, indexer = loader_with_root
    _write_skill(root, "cmd-skill", "Tag: !`echo SHOULD-NOT-RUN`")
    indexer.scan_all()
    skill = SkillLoader(indexer).load_skill("cmd-skill")
    assert skill is not None
    # Literal preserved exactly as written; the command did not execute.
    assert "!`echo SHOULD-NOT-RUN`" in skill.prompt_template
    assert "SHOULD-NOT-RUN\n" not in skill.prompt_template.replace(
        "!`echo SHOULD-NOT-RUN`", ""
    )


def test_command_resolution_runs_when_opted_in(loader_with_root, monkeypatch):
    monkeypatch.setenv("MAGI_SKILLS_ALLOW_COMMAND_RESOLUTION", "1")
    root, indexer = loader_with_root
    _write_skill(root, "cmd-skill-on", "Tag: !`echo magi-cmd-ran`")
    indexer.scan_all()
    skill = SkillLoader(indexer).load_skill("cmd-skill-on")
    assert skill is not None
    assert "magi-cmd-ran" in skill.prompt_template
    assert "!`echo magi-cmd-ran`" not in skill.prompt_template


def test_body_truncated_when_oversize(loader_with_root, caplog):
    root, indexer = loader_with_root
    big = "A" * (MAX_SKILL_BODY_BYTES + 4096)
    _write_skill(root, "big-skill", big)
    indexer.scan_all()
    skill = SkillLoader(indexer).load_skill("big-skill")
    assert skill is not None
    encoded = skill.prompt_template.encode("utf-8")
    # Truncated to the cap plus the appended marker.
    assert len(encoded) < MAX_SKILL_BODY_BYTES + 200
    assert "truncated at" in skill.prompt_template


def test_yaml_error_after_indexing_preserves_body_and_warns(loader_with_root, caplog):
    root, indexer = loader_with_root
    directory = _write_skill(root, "changed-yaml", "original body")
    indexer.scan_all()
    skill_file = directory / "SKILL.md"
    skill_file.write_text(
        "---\nname: changed-yaml\ndescription: ok\n: : invalid\n---\nretained body\n",
        encoding="utf-8",
    )
    skill = SkillLoader(indexer).load_skill("changed-yaml")
    assert skill is not None
    assert skill.source_file == skill_file
    assert skill.prompt_template == "retained body\n"
    assert skill.frontmatter.name == "" and skill.frontmatter.description == ""
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == "magi.skills.loader" and record.levelname == "WARNING"
    ]
    assert len(warnings) == 1 and "Failed to parse frontmatter" in warnings[0]
