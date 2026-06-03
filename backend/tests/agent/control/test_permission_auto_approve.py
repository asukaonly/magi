"""Per-binding auto-approve bypass in PermissionGateway — CF-8.

Pins:
* When both ``binding_settings_store`` and ``binding_origin_resolver``
  are wired AND the resolver returns a (channel, ext_user_id) with
  ``auto_approve=True``, the prompt is suppressed and the gate
  returns ALLOWED with source="auto_approve_binding".
* The bypass fires AFTER kill-list (security floors win) AND AFTER
  cached rules (explicit user-recorded decisions win) AND AFTER
  ``_needs_prompt`` (low-risk paths still take the existing "auto"
  shortcut — bypass only matters when we WOULD have prompted).
* ``auto_approve=False`` → normal prompter flow.
* Either dependency unwired → no bypass (degenerate case → normal flow).
* Resolver raising → no bypass + WARNING log (fail-closed).
* Store raising → no bypass + WARNING log (fail-closed).
* Resolver returning None → no bypass (binding not identifiable).
* session_id=None → no bypass (orphan request can't have a binding).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from magi.control.common.interaction_broker import InteractionBroker
from magi.control.permission.classifier import RiskClassifier
from magi.control.permission.contracts import (
    PermissionOutcome,
    PermissionScope,
    ToolOrigin,
)
from magi.control.permission.gateway import (
    PermissionGateway,
    UserPromptResponse,
)
from magi.control.permission.rules import PermissionRuleStore
from magi.control.settings import (
    ControlSettings,
    PermissionMode,
)


@dataclass
class _BindingSettingsStub:
    """Mimic ChannelBindingSettingsStore.get for tests."""

    auto_approve: bool = False
    raises: bool = False

    async def get(self, *, channel_type: str, external_user_id: str):
        if self.raises:
            raise RuntimeError("boom")

        @dataclass
        class _Result:
            auto_approve: bool
        return _Result(auto_approve=self.auto_approve)


class _RecordingPrompter:
    """Records whether it was invoked so tests can assert prompt
    suppression."""

    def __init__(self, allow: bool = True) -> None:
        self.calls: list = []
        self._allow = allow

    async def __call__(self, request, *, timeout_seconds):
        self.calls.append(request)
        return UserPromptResponse(
            allow=self._allow,
            scope=PermissionScope.ONE_SHOT,
            matcher=None,
            note=None,
        )


@pytest.fixture
def rules_store(tmp_path):
    """Sync fixture that schema-initializes via direct sqlite,
    avoiding async-fixture-mode wrangling."""
    db_path = tmp_path / "rules.db"
    import sqlite3
    conn = sqlite3.connect(db_path)
    # Schema cribbed from PermissionRuleStore.initialize — keeps the
    # test self-contained without needing to await store.initialize().
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS permission_rules (
        rule_id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        allow INTEGER NOT NULL,
        tool_name TEXT NOT NULL,
        matcher_json TEXT NOT NULL DEFAULT '{}',
        session_id TEXT,
        note TEXT,
        created_at_ms INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_permission_rules_tool
        ON permission_rules(tool_name);
    """)
    conn.commit()
    conn.close()
    return PermissionRuleStore(db_path=str(db_path))


def _make_gateway(
    *,
    rules_store: PermissionRuleStore,
    prompter,
    binding_store=None,
    binding_resolver=None,
    settings=None,
):
    return PermissionGateway(
        classifier=RiskClassifier(),
        rules=rules_store,
        broker=InteractionBroker(),
        settings_provider=lambda: settings or ControlSettings(
            permission_mode=PermissionMode.ALL,
        ),
        prompter=prompter,
        binding_settings_store=binding_store,
        binding_origin_resolver=binding_resolver,
    )


async def _resolver_returning(ch: str | None, uid: str | None):
    """Test helper — fix the (channel, uid) return."""
    async def _r(session_id):
        if ch is None:
            return None
        return (ch, uid)
    return _r


# === Bypass fires =========================================================


@pytest.mark.asyncio
async def test_auto_approve_true_suppresses_prompt(rules_store) -> None:
    prompter = _RecordingPrompter()
    store = _BindingSettingsStub(auto_approve=True)

    async def resolver(session_id):
        return ("weixin", "userA")

    gateway = _make_gateway(
        rules_store=rules_store,
        prompter=prompter,
        binding_store=store,
        binding_resolver=resolver,
    )
    decision = await gateway.gate(
        tool_name="image_gen", arguments={},
        agent_id="a", origin=ToolOrigin.CHAT,
        session_id="s1",
        tool_is_dangerous=True,  # force the prompt-needed path
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "auto_approve_binding"
    assert prompter.calls == []  # prompter never invoked


# === Bypass doesn't fire ==================================================


@pytest.mark.asyncio
async def test_auto_approve_false_uses_prompter(rules_store) -> None:
    prompter = _RecordingPrompter(allow=True)
    store = _BindingSettingsStub(auto_approve=False)

    async def resolver(session_id):
        return ("weixin", "userA")

    gateway = _make_gateway(
        rules_store=rules_store, prompter=prompter,
        binding_store=store, binding_resolver=resolver,
    )
    decision = await gateway.gate(
        tool_name="image_gen", arguments={},
        agent_id="a", origin=ToolOrigin.CHAT,
        session_id="s1", tool_is_dangerous=True,
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "user"  # came via prompter
    assert len(prompter.calls) == 1


@pytest.mark.asyncio
async def test_no_store_no_bypass(rules_store) -> None:
    """``binding_settings_store=None`` (partial bootstrap) → no
    bypass, fall through to prompter."""
    prompter = _RecordingPrompter(allow=True)

    async def resolver(session_id):
        return ("weixin", "userA")

    gateway = _make_gateway(
        rules_store=rules_store, prompter=prompter,
        binding_store=None, binding_resolver=resolver,
    )
    decision = await gateway.gate(
        tool_name="image_gen", arguments={},
        agent_id="a", origin=ToolOrigin.CHAT,
        session_id="s1", tool_is_dangerous=True,
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "user"
    assert len(prompter.calls) == 1


@pytest.mark.asyncio
async def test_no_resolver_no_bypass(rules_store) -> None:
    """``binding_origin_resolver=None`` → no bypass."""
    prompter = _RecordingPrompter(allow=True)
    store = _BindingSettingsStub(auto_approve=True)
    gateway = _make_gateway(
        rules_store=rules_store, prompter=prompter,
        binding_store=store, binding_resolver=None,
    )
    decision = await gateway.gate(
        tool_name="image_gen", arguments={},
        agent_id="a", origin=ToolOrigin.CHAT,
        session_id="s1", tool_is_dangerous=True,
    )
    assert decision.source == "user"
    assert len(prompter.calls) == 1


@pytest.mark.asyncio
async def test_no_session_id_no_bypass(rules_store) -> None:
    """``session_id=None`` (orphan) → no bypass — there's no binding
    to look up."""
    prompter = _RecordingPrompter(allow=True)
    store = _BindingSettingsStub(auto_approve=True)

    async def resolver(session_id):
        return ("weixin", "userA")

    gateway = _make_gateway(
        rules_store=rules_store, prompter=prompter,
        binding_store=store, binding_resolver=resolver,
    )
    decision = await gateway.gate(
        tool_name="image_gen", arguments={},
        agent_id="a", origin=ToolOrigin.CHAT,
        session_id=None, tool_is_dangerous=True,
    )
    assert decision.source == "user"
    assert len(prompter.calls) == 1


@pytest.mark.asyncio
async def test_resolver_returns_none_no_bypass(rules_store) -> None:
    """Resolver can't identify the binding (no active run / no
    source_channel) → no bypass."""
    prompter = _RecordingPrompter(allow=True)
    store = _BindingSettingsStub(auto_approve=True)

    async def resolver(session_id):
        return None

    gateway = _make_gateway(
        rules_store=rules_store, prompter=prompter,
        binding_store=store, binding_resolver=resolver,
    )
    decision = await gateway.gate(
        tool_name="image_gen", arguments={},
        agent_id="a", origin=ToolOrigin.CHAT,
        session_id="s1", tool_is_dangerous=True,
    )
    assert decision.source == "user"
    assert len(prompter.calls) == 1


# === Fail-closed on exceptions ===========================================


@pytest.mark.asyncio
async def test_resolver_raises_no_bypass(
    rules_store, caplog
) -> None:
    """Resolver raising → no bypass + WARNING. Bug in the resolver
    must not silently auto-approve dangerous tools."""
    prompter = _RecordingPrompter(allow=True)
    store = _BindingSettingsStub(auto_approve=True)

    async def bad_resolver(session_id):
        raise RuntimeError("resolver broken")

    gateway = _make_gateway(
        rules_store=rules_store, prompter=prompter,
        binding_store=store, binding_resolver=bad_resolver,
    )
    with caplog.at_level("WARNING"):
        decision = await gateway.gate(
            tool_name="image_gen", arguments={},
            agent_id="a", origin=ToolOrigin.CHAT,
            session_id="s1", tool_is_dangerous=True,
        )
    assert decision.source == "user"
    assert any(
        "binding_origin_resolver_failed" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_store_raises_no_bypass(rules_store, caplog) -> None:
    """Store raising → no bypass + WARNING. SQLite locked / disk
    full must not silently auto-approve."""
    prompter = _RecordingPrompter(allow=True)
    store = _BindingSettingsStub(auto_approve=True, raises=True)

    async def resolver(session_id):
        return ("weixin", "userA")

    gateway = _make_gateway(
        rules_store=rules_store, prompter=prompter,
        binding_store=store, binding_resolver=resolver,
    )
    with caplog.at_level("WARNING"):
        decision = await gateway.gate(
            tool_name="image_gen", arguments={},
            agent_id="a", origin=ToolOrigin.CHAT,
            session_id="s1", tool_is_dangerous=True,
        )
    assert decision.source == "user"
    assert any(
        "binding_settings_lookup_failed" in rec.message
        for rec in caplog.records
    )
