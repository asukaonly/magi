"""Tests for config router extensions."""

from magi.api.routers.config import SystemConfigModel, _build_update_paths


def test_build_update_paths_contains_new_sections():
    config = SystemConfigModel()
    updates = _build_update_paths(config)

    assert "preferences" in updates
    assert "personality" in updates
    assert "memory_layers" in updates
    assert "tools.builtIn" in updates
    assert "tools.skills" in updates


def test_build_update_paths_skip_masked_api_key():
    config = SystemConfigModel()
    config.llm.api_key = "***"
    updates = _build_update_paths(config)
    assert "llm.api_key" not in updates

