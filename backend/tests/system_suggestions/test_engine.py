"""Tests for the orchestration engine: gate -> throttle -> classify -> build."""

from __future__ import annotations

from magi.system_suggestions.engine import run_suggestion_check
from magi.system_suggestions.throttle import SuggestionThrottle
from magi_plugin_sdk.contracts import (
    LocalizedText,
    PluginManifest,
    SuggestionDescriptor,
    Triggers,
)


def _manifest(plugin_id: str, category: str, keywords_zh: list[str]) -> PluginManifest:
    """Build a PluginManifest with a suggestion_descriptor (zh keywords only)."""
    return PluginManifest(
        id=plugin_id,
        name=plugin_id,
        version="0.1.0",
        entry_module="plugin",
        entry_class="X",
        suggestion_descriptor=SuggestionDescriptor(
            category=category,
            triggers=Triggers(intents=[], entities=[], keywords={"zh": keywords_zh}),
            platform_support=["darwin", "win32", "linux"],
            local_requirements=[],
            rationale=LocalizedText(
                zh=f"connect {plugin_id} (zh)",
                en=f"connect {plugin_id} (en)",
            ),
        ),
    )


def _browser_manifests() -> list[PluginManifest]:
    return [_manifest("chrome-history", "browser_history", ["浏览"])]


async def _run(text, *, classify, throttle, session="s1"):
    return await run_suggestion_check(
        recent_text=text,
        locale="zh",
        session_id=session,
        plugin_manifests=_browser_manifests(),
        is_available=lambda _pid: True,
        is_dismissed=lambda _c: False,
        classify=classify,
        throttle=throttle,
    )


async def test_no_candidates_skips_classify():
    calls = []

    async def classify(*a, **k):
        calls.append(1)
        return {}

    out = await _run("无关文本", classify=classify, throttle=SuggestionThrottle())
    assert out == []
    assert calls == []  # classify never called when gate is empty


async def test_classify_confidence_drives_proposals():
    async def classify(*a, **k):
        return {"browser_history": 0.8}

    out = await _run("我想看浏览历史", classify=classify, throttle=SuggestionThrottle())
    assert len(out) == 1 and out[0].confidence == 0.8


async def test_throttle_returns_cached_without_reclassifying():
    th = SuggestionThrottle(reclassify_after=99)
    calls = []

    async def classify(*a, **k):
        calls.append(1)
        return {"browser_history": 0.7}

    await _run("浏览", classify=classify, throttle=th)
    await _run("浏览", classify=classify, throttle=th)  # same candidates -> cached
    assert len(calls) == 1


async def test_classify_failure_degrades_to_keyword():
    async def boom(*a, **k):
        raise RuntimeError("llm down")

    out = await _run("浏览", classify=boom, throttle=SuggestionThrottle())
    assert len(out) == 1  # keyword fallback still yields the proposal
