"""Tests for /api/commands/skills and /api/commands/expand-skill."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import commands as commands_module
from magi.api.routers.commands import commands_router
from magi.skills.schema import SkillContent, SkillFrontmatter, SkillMetadata


def _meta(name: str, **kw) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=kw.get("description", f"{name} skill"),
        directory=Path("/tmp"),
        argument_hint=kw.get("argument_hint"),
        user_invocable=kw.get("user_invocable", True),
        category=kw.get("category"),
        tags=kw.get("tags", []),
    )


@pytest.fixture
def client(monkeypatch):
    indexer = MagicMock()
    indexer.get_skill_names.return_value = ["pr-review", "internal-only"]

    def get_metadata(name: str):
        return {
            "pr-review": _meta(
                "pr-review",
                description="Review a pull request",
                argument_hint="<pr_number>",
            ),
            "internal-only": _meta(
                "internal-only",
                description="hidden",
                user_invocable=False,
            ),
        }.get(name)

    indexer.get_metadata.side_effect = get_metadata

    monkeypatch.setattr(commands_module, "resolve_skill_indexer", lambda: indexer)

    fake_loader = MagicMock()
    monkeypatch.setattr(
        "magi.skills.expander.resolve_skill_loader",
        lambda: fake_loader,
    )

    def load_skill(name: str):
        if name == "pr-review":
            return SkillContent(
                name=name,
                frontmatter=SkillFrontmatter(
                    name=name,
                    description="Review a pull request",
                    argument_hint="<pr_number>",
                    user_invocable=True,
                ),
                prompt_template="Please review PR #$0 carefully.",
                supporting_data={},
                source_file=Path("/tmp/pr-review/SKILL.md"),
            )
        if name == "internal-only":
            return SkillContent(
                name=name,
                frontmatter=SkillFrontmatter(
                    name=name,
                    description="hidden",
                    user_invocable=False,
                ),
                prompt_template="hidden body",
                supporting_data={},
                source_file=Path("/tmp/internal-only/SKILL.md"),
            )
        return None

    fake_loader.load_skill.side_effect = load_skill

    app = FastAPI()
    app.include_router(commands_router, prefix="/api/commands")
    yield TestClient(app)


def test_list_skills_excludes_non_user_invocable(client):
    r = client.get("/api/commands/skills")
    assert r.status_code == 200
    body = r.json()
    names = {item["name"] for item in body["data"]}
    assert names == {"pr-review"}
    pr = body["data"][0]
    assert pr["argument_hint"] == "<pr_number>"
    assert pr["description"] == "Review a pull request"


def test_expand_skill_returns_rendered_prompt(client):
    r = client.post(
        "/api/commands/expand-skill",
        json={
            "session_id": "s1",
            "skill_name": "pr-review",
            "arguments": ["123"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rendered_prompt"] == "Please review PR #123 carefully."
    assert body["invocation_text"] == "/pr-review 123"
    assert body["argument_hint"] == "<pr_number>"


def test_expand_skill_404_for_missing(client):
    r = client.post(
        "/api/commands/expand-skill",
        json={"session_id": "s1", "skill_name": "ghost"},
    )
    assert r.status_code == 404


def test_expand_skill_403_for_non_user_invocable(client):
    r = client.post(
        "/api/commands/expand-skill",
        json={"session_id": "s1", "skill_name": "internal-only"},
    )
    assert r.status_code == 403
