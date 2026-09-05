from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk import (
    Plugin,
    Source,
    SourceOutput,
    UserContentClearContext,
    UserContentClearRequest,
)


class _RuntimePaths:
    def plugin_cache_dir(self, plugin_id: str) -> Path:
        return Path("cache") / plugin_id


class _Plugin(Plugin):
    pass


class _Source(Source):
    async def build_output(self, item: dict) -> SourceOutput:
        raise NotImplementedError


def _context() -> UserContentClearContext:
    settings = {
        "account": {"id": "account-1"},
        "paths": ["/private/source"],
    }
    return UserContentClearContext(
        request=UserContentClearRequest(clear_generation=3),
        runtime_paths=_RuntimePaths(),
        plugin_id="example",
        source_id="timeline.example",
        plugin_settings=settings,
    )


@pytest.mark.asyncio
async def test_plugin_and_source_clear_hooks_have_idempotent_noop_defaults() -> None:
    context = _context()

    assert await _Plugin().clear_user_content(context) is None
    assert await _Source().clear_user_content(context) is None


def test_clear_context_exposes_an_immutable_settings_snapshot() -> None:
    settings = {
        "account": {"id": "account-1"},
        "paths": ["/private/source"],
    }
    context = UserContentClearContext(
        request=UserContentClearRequest(clear_generation=3),
        runtime_paths=_RuntimePaths(),
        plugin_id="example",
        plugin_settings=settings,
    )
    settings["account"]["id"] = "changed"
    settings["paths"].append("/later")

    assert context.plugin_settings["account"]["id"] == "account-1"
    assert context.plugin_settings["paths"] == ("/private/source",)
    with pytest.raises(TypeError):
        context.plugin_settings["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        context.plugin_settings["account"]["id"] = "changed"  # type: ignore[index]


def test_clear_context_makes_retention_and_network_policy_explicit() -> None:
    context = _context()

    assert context.network_access_allowed is False
    assert context.preserve_configuration is True
    assert context.preserve_credentials is True
    assert context.preserve_accounts is True
    assert context.preserve_source_progress is True
    assert context.runtime_paths.plugin_cache_dir("example") == Path("cache/example")


@pytest.mark.parametrize("generation", [0, -1, True])
def test_clear_request_rejects_invalid_generations(generation: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        UserContentClearRequest(clear_generation=generation)  # type: ignore[arg-type]
