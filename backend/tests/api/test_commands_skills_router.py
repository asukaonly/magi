"""Tests for /api/commands/skills, /api/commands/expand-skill,
and /api/commands/run-skill-as-background."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.agent.background.contracts import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskTriggerSource,
)
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
        context=kw.get("context"),
        category=kw.get("category"),
        tags=kw.get("tags", []),
    )


@pytest.fixture
def client(monkeypatch):
    indexer = MagicMock()
    indexer.get_skill_names.return_value = [
        "pr-review",
        "internal-only",
        "deep-scan",
    ]

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
            "deep-scan": _meta(
                "deep-scan",
                description="Audit the whole repo",
                context="fork",
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
        if name == "deep-scan":
            return SkillContent(
                name=name,
                frontmatter=SkillFrontmatter(
                    name=name,
                    description="Audit the whole repo",
                    user_invocable=True,
                    context="fork",
                    allowed_tools=["read_file", "list_files"],
                ),
                prompt_template="Scan workspace ${PWD} for security issues.",
                supporting_data={},
                source_file=Path("/tmp/deep-scan/SKILL.md"),
            )
        return None

    fake_loader.load_skill.side_effect = load_skill

    app = FastAPI()
    app.include_router(commands_router, prefix="/api/commands")
    yield TestClient(app), monkeypatch


def test_list_skills_excludes_non_user_invocable(client):
    c, _ = client
    r = c.get("/api/commands/skills")
    assert r.status_code == 200
    body = r.json()
    names = {item["name"] for item in body["data"]}
    assert names == {"pr-review", "deep-scan"}
    deep = next(item for item in body["data"] if item["name"] == "deep-scan")
    assert deep["context_mode"] == "fork"


def test_expand_skill_returns_rendered_prompt(client):
    c, _ = client
    r = c.post(
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
    c, _ = client
    r = c.post(
        "/api/commands/expand-skill",
        json={"session_id": "s1", "skill_name": "ghost"},
    )
    assert r.status_code == 404


def test_expand_skill_403_for_non_user_invocable(client):
    c, _ = client
    r = c.post(
        "/api/commands/expand-skill",
        json={"session_id": "s1", "skill_name": "internal-only"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# run-skill-as-background
# ---------------------------------------------------------------------------


def _stub_manager(monkeypatch):
    """Wire a fake BackgroundTaskManager into the resolver."""

    enqueued: list[BackgroundTaskSpec] = []
    manager = MagicMock()

    async def _enqueue(spec: BackgroundTaskSpec) -> BackgroundTask:
        enqueued.append(spec)
        return BackgroundTask.new(spec)

    manager.enqueue = _enqueue
    monkeypatch.setattr(
        commands_module, "resolve_background_task_manager", lambda: manager
    )
    return enqueued


def test_run_skill_as_background_enqueues_task(client):
    c, monkeypatch = client
    enqueued = _stub_manager(monkeypatch)

    r = c.post(
        "/api/commands/run-skill-as-background",
        json={
            "session_id": "s1",
            "skill_name": "deep-scan",
            "workspace_path": "/tmp/work",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "/deep-scan"
    assert body["selected_tools"] == ["read_file", "list_files"]
    assert body["task_id"]

    assert len(enqueued) == 1
    spec = enqueued[0]
    assert spec.session_id == "s1"
    assert spec.workspace_path == "/tmp/work"
    assert spec.trigger_source == BackgroundTaskTriggerSource.MANUAL
    assert "Scan workspace" in spec.goal
    # PWD substitution carried through.
    assert spec.goal.endswith("for security issues.")
    assert "/tmp/work" in spec.goal
    assert spec.selected_tools == ["read_file", "list_files"]


def test_run_skill_as_background_rejects_inline_skill(client):
    c, monkeypatch = client
    _stub_manager(monkeypatch)
    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "pr-review"},
    )
    assert r.status_code == 400
    assert "context: fork" in r.json()["detail"]


def test_run_skill_as_background_404_for_missing(client):
    c, monkeypatch = client
    _stub_manager(monkeypatch)
    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "ghost"},
    )
    assert r.status_code == 404


def test_run_skill_as_background_403_for_non_invocable(client):
    c, monkeypatch = client
    _stub_manager(monkeypatch)
    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "internal-only"},
    )
    assert r.status_code == 403


def test_run_skill_as_background_503_when_manager_unavailable(client):
    c, monkeypatch = client

    def _missing():
        raise RuntimeError("manager binding not initialized")

    monkeypatch.setattr(commands_module, "resolve_background_task_manager", _missing)

    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "deep-scan"},
    )
    assert r.status_code == 503
