"""Tests for typed skill commands and background skill runs."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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
    monkeypatch.setattr(
        commands_module,
        "get_enabled_skill_names",
        lambda: {"pr-review", "internal-only", "deep-scan"},
    )
    monkeypatch.setattr(
        "magi.commands.registry.get_enabled_skill_names",
        lambda: {"pr-review", "internal-only", "deep-scan"},
    )

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
    r = c.get("/api/commands/")
    assert r.status_code == 200
    body = r.json()
    skills = [item for item in body["data"] if item["kind"] == "skill"]
    names = {item["name"] for item in skills}
    assert names == {"pr-review", "deep-scan"}
    deep = next(item for item in skills if item["name"] == "deep-scan")
    assert deep["context_mode"] == "fork"


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


def _stub_chat_writer(monkeypatch):
    """Wire a fake chat writer that records pending task messages."""
    appended: list = []

    class _Writer:
        async def create_background_task_pending_message(
            self,
            *,
            user_id: str,
            session_id: str,
            title: str,
            trigger_source: str,
            skill_name: str,
            invocation_text: str,
        ) -> str:
            message_id = f"msg-{len(appended) + 1}"
            payload = {
                "background_task_id": "",
                "background_task_status": "pending",
                "background_task_title": title,
                "trigger_source": trigger_source,
                "skill_name": skill_name,
                "invocation_text": invocation_text,
            }
            record = SimpleNamespace(
                message_id=message_id,
                session_id=session_id,
                user_id=user_id,
                message_kind="background_task_pending",
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            appended.append(record)
            return message_id

        async def attach_background_task_id(
            self,
            *,
            user_id: str,
            session_id: str,
            message_id: str,
            task_id: str,
        ) -> None:
            for record in appended:
                if record.message_id == message_id:
                    payload = json.loads(record.payload_json)
                    payload["background_task_id"] = task_id
                    record.payload_json = json.dumps(payload, ensure_ascii=False)
                    return

    monkeypatch.setattr(commands_module, "require_chat_surface_write_service", lambda: _Writer())
    return appended


def test_run_skill_as_background_enqueues_task(client):
    c, monkeypatch = client
    enqueued = _stub_manager(monkeypatch)
    appended = _stub_chat_writer(monkeypatch)

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
    assert body["pending_message_id"]

    assert len(enqueued) == 1
    spec = enqueued[0]
    assert spec.session_id == "s1"
    assert spec.workspace_path == "/tmp/work"
    assert spec.trigger_source == BackgroundTaskTriggerSource.MANUAL
    assert spec.pending_message_id == body["pending_message_id"]
    assert "Scan workspace" in spec.goal
    assert spec.goal.endswith("for security issues.")
    assert "/tmp/work" in spec.goal
    assert spec.selected_tools == ["read_file", "list_files"]

    # Pending row was written with the patched task_id payload.
    assert len(appended) == 1
    pending = appended[0]
    assert pending.message_kind == "background_task_pending"
    assert pending.message_id == body["pending_message_id"]
    payload = json.loads(pending.payload_json)
    assert payload["background_task_id"] == body["task_id"]
    assert payload["skill_name"] == "deep-scan"


def test_run_skill_as_background_rejects_inline_skill(client):
    c, monkeypatch = client
    _stub_manager(monkeypatch)
    _stub_chat_writer(monkeypatch)
    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "pr-review"},
    )
    assert r.status_code == 400
    assert "context: fork" in r.json()["detail"]


def test_run_skill_as_background_404_for_missing(client):
    c, monkeypatch = client
    _stub_manager(monkeypatch)
    _stub_chat_writer(monkeypatch)
    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "ghost"},
    )
    assert r.status_code == 404


def test_run_skill_as_background_403_for_non_invocable(client):
    c, monkeypatch = client
    _stub_manager(monkeypatch)
    _stub_chat_writer(monkeypatch)
    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "internal-only"},
    )
    assert r.status_code == 403


def test_run_skill_as_background_503_when_manager_unavailable(client):
    c, monkeypatch = client
    _stub_chat_writer(monkeypatch)

    def _missing():
        raise RuntimeError("manager binding not initialized")

    monkeypatch.setattr(commands_module, "resolve_background_task_manager", _missing)

    r = c.post(
        "/api/commands/run-skill-as-background",
        json={"session_id": "s1", "skill_name": "deep-scan"},
    )
    assert r.status_code == 503
