"""Verification tests for P1-D3: OS secret store reference storage and plaintext migration."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import yaml

from magi.config import loader as config_loader
from magi.config.loader import ConfigLoader
from magi.core.secret_store import (
    InMemorySecretStore,
    SecretStorageStatus,
    SecretStoreError,
    override_secret_store,
)
from magi.plugins.connections import PluginConnectionStore
from magi.utils.runtime import RuntimePaths


class _FailingWriteSecretStore(InMemorySecretStore):
    """SecretStore double whose set() fails to verify migration rollback safety."""

    def __init__(self, *, fail_after: int = 0) -> None:
        super().__init__()
        self._fail_after = fail_after
        self._writes = 0

    def set(self, ref: str, value: str) -> None:
        if self._writes >= self._fail_after:
            raise SecretStoreError("Simulated keychain access denied")
        self._writes += 1
        super().set(ref, value)

    def status(self) -> SecretStorageStatus:
        return SecretStorageStatus(backend="failing_mock", secure=True, detail="mock")


def _patch_loader_home(monkeypatch, root: Path) -> None:
    config_dir = root / "config"
    plugins_dir = config_dir / "plugins"
    monkeypatch.setattr(config_loader, "get_config_dir", lambda: config_dir)
    monkeypatch.setattr(config_loader, "get_config_file", lambda: config_dir / "agent.yaml")
    monkeypatch.setattr(config_loader, "get_llm_config_file", lambda: config_dir / "llm.yaml")
    monkeypatch.setattr(config_loader, "get_lifecycle_config_file", lambda: config_dir / "lifecycle.yaml")
    monkeypatch.setattr(config_loader, "get_plugins_config_dir", lambda: plugins_dir)
    monkeypatch.setattr(config_loader, "get_plugins_index_file", lambda: plugins_dir / "index.yaml")
    monkeypatch.setattr(config_loader, "get_data_dir", lambda: root / "data")


def test_config_and_plugin_secrets_never_written_plaintext_and_survive_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_loader_home(monkeypatch, tmp_path)
    secret_store = InMemorySecretStore()
    llm_secret = "sk-live-openai-topsecret-99887766"
    tavily_secret = "tvly-prod-secret-55443322"
    telegram_token = "123456789:AAH-telegram-bot-secret-token"

    with override_secret_store(secret_store):
        loader = ConfigLoader()
        loader.load()
        assert loader.save(
            {
                "llm.providers.openai.enabled": True,
                "llm.providers.openai.provider_type": "openai",
                "llm.providers.openai.display_name": "OpenAI",
                "llm.providers.openai.api_key": llm_secret,
                "tools.web_search.providers.tavily.api_key": tavily_secret,
            }
        )

        # Verify raw disk files contain zero plaintext secret substrings
        raw_llm = (tmp_path / "config" / "llm.yaml").read_text(encoding="utf-8")
        raw_agent = (tmp_path / "config" / "agent.yaml").read_text(encoding="utf-8")
        assert llm_secret not in raw_llm
        assert tavily_secret not in raw_agent
        assert "secret_ref:llm:" in raw_llm
        assert "secret_ref:agent:" in raw_agent

        # Plugin connection secret (e.g. Telegram bot token)
        conn_store = PluginConnectionStore(
            runtime_paths=RuntimePaths(base_dir=tmp_path),
            require_package=lambda _pkg: object(),
            authorize_enable=lambda _conn: True,
            validate_settings=lambda _conn: None,
        )
        connection = conn_store.create(
            "telegram",
            display_name="My Telegram Bot",
            credentials={"bot_token": telegram_token},
            enabled=False,
        )
        raw_state = conn_store.path.read_text(encoding="utf-8")
        assert telegram_token not in raw_state
        assert "secret_ref:plugins:" in raw_state

        # Simulate full service restart with brand-new instances reading from disk + secret store
        restarted_loader = ConfigLoader()
        reloaded_cfg = restarted_loader.load()
        assert reloaded_cfg.llm.providers["openai"].api_key == llm_secret
        assert reloaded_cfg.tools.web_search.providers["tavily"].api_key == tavily_secret

        restarted_conn_store = PluginConnectionStore(
            runtime_paths=RuntimePaths(base_dir=tmp_path),
            require_package=lambda _pkg: object(),
            authorize_enable=lambda _conn: True,
            validate_settings=lambda _conn: None,
        )
        ctx = restarted_conn_store.context(connection.connection_id)
        assert ctx.credentials.get("bot_token") == telegram_token

        # Disconnecting removes the secret from the store
        restarted_conn_store.disconnect(connection.connection_id, expected_revision=connection.revision)
        assert not any(k.startswith("secret_ref:plugins:") for k in secret_store._items)


def test_legacy_plaintext_files_migrate_atomically_and_rollback_when_keychain_denied(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_loader_home(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    legacy_llm_secret = "sk-legacy-anthropic-secret-11223344"
    legacy_tool_secret = "qweather-legacy-secret-66778899"
    legacy_tg_token = "987654321:BBG-legacy-telegram-secret"

    # Bootstrap default files first, then inject legacy plaintext secrets on disk
    with override_secret_store(InMemorySecretStore()):
        ConfigLoader().load()

    (config_dir / "llm.yaml").write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "anthropic": {
                        "enabled": True,
                        "provider_type": "anthropic",
                        "display_name": "Anthropic",
                        "api_key": legacy_llm_secret,
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    agent_data = yaml.safe_load((config_dir / "agent.yaml").read_text(encoding="utf-8"))
    agent_data["tools"]["weather"]["providers"]["qweather"]["api_key"] = legacy_tool_secret
    (config_dir / "agent.yaml").write_text(
        yaml.safe_dump(agent_data, sort_keys=False),
        encoding="utf-8",
    )

    conn_id = f"conn_{uuid4().hex}"
    cred_ref = f"cred_{uuid4().hex}"
    runtime_paths = RuntimePaths(base_dir=tmp_path)
    state_path = runtime_paths.runtime_dir / "plugin-connections" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_state_payload = json.dumps(
        {
            "schema_version": 1,
            "connections": {
                conn_id: {
                    "connection": {
                        "connection_id": conn_id,
                        "plugin_id": "telegram",
                        "display_name": "Legacy Bot",
                        "enabled": False,
                        "settings": {},
                        "credential_refs": {"bot_token": cred_ref},
                        "revision": 1,
                    },
                    "credentials": {cred_ref: legacy_tg_token},
                    "private_state": {},
                    "content_state": {},
                    "state_revision": 0,
                    "readiness": [],
                }
            },
        },
        indent=2,
    )
    state_path.write_text(legacy_state_payload, encoding="utf-8")

    # 1. Denied keychain write must preserve plaintext files intact (fail-safe rollback)
    denied_store = _FailingWriteSecretStore(fail_after=0)
    with override_secret_store(denied_store):
        cfg_denied = ConfigLoader().load()
        assert cfg_denied.llm.providers["anthropic"].api_key == legacy_llm_secret
        assert cfg_denied.tools.weather.providers["qweather"].api_key == legacy_tool_secret
        assert legacy_llm_secret in (config_dir / "llm.yaml").read_text(encoding="utf-8")
        assert legacy_tool_secret in (config_dir / "agent.yaml").read_text(encoding="utf-8")

        conn_store_denied = PluginConnectionStore(
            runtime_paths=runtime_paths,
            require_package=lambda _pkg: object(),
        )
        assert conn_store_denied.context(conn_id).credentials.get("bot_token") == legacy_tg_token
        assert legacy_tg_token in state_path.read_text(encoding="utf-8")
        assert len(denied_store._items) == 0

    # 2. Working secret store migrates atomically and scrubs all plaintext from disk
    ok_store = InMemorySecretStore()
    with override_secret_store(ok_store):
        cfg_migrated = ConfigLoader().load()
        assert cfg_migrated.llm.providers["anthropic"].api_key == legacy_llm_secret
        assert cfg_migrated.tools.weather.providers["qweather"].api_key == legacy_tool_secret
        assert legacy_llm_secret not in (config_dir / "llm.yaml").read_text(encoding="utf-8")
        assert legacy_tool_secret not in (config_dir / "agent.yaml").read_text(encoding="utf-8")
        assert "secret_ref:llm:" in (config_dir / "llm.yaml").read_text(encoding="utf-8")
        assert "secret_ref:agent:" in (config_dir / "agent.yaml").read_text(encoding="utf-8")

        conn_store_ok = PluginConnectionStore(
            runtime_paths=runtime_paths,
            require_package=lambda _pkg: object(),
        )
        assert conn_store_ok.context(conn_id).credentials.get("bot_token") == legacy_tg_token
        scrubbed_state = state_path.read_text(encoding="utf-8")
        assert legacy_tg_token not in scrubbed_state
        assert "secret_ref:plugins:" in scrubbed_state
