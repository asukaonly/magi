from __future__ import annotations

from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.config.models import LLMCacheObservabilitySettings, ModelVendor
from magi.llm.cache_observability import build_cache_observation
from magi.utils.model_context_messages import build_working_context_message


def test_build_cache_observation_hashes_prompt_and_tools_without_raw_text() -> None:
    system_prompt = (
        "stable system head"
        f"\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\n"
        "# Persona Turn Steer\nsecret per-turn text"
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "private schema text",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    observation = build_cache_observation(
        system_prompt=system_prompt,
        tools=tools,
        vendor=ModelVendor.OPENAI,
        event_context={"session_id": "s1"},
        cache_whole_system=False,
        store_tool_names=True,
    )

    assert observation["system_head_chars"] == len("stable system head")
    assert observation["dynamic_context_chars"] == len(
        "# Persona Turn Steer\nsecret per-turn text"
    )
    assert observation["tool_count"] == 1
    assert observation["tool_names"] == ["weather"]
    assert observation["cache_strategy"] == "prompt_cache_key"
    assert observation["cache_eligible"] is True
    assert observation["system_head_hash"]
    assert observation["dynamic_context_hash"]
    assert observation["tools_hash"]
    assert "stable system head" not in str(observation)
    assert "secret per-turn text" not in str(observation)
    assert "private schema text" not in str(observation)


def test_build_cache_observation_can_omit_tool_names() -> None:
    observation = build_cache_observation(
        system_prompt="stable",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "file_read",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        vendor=ModelVendor.ANTHROPIC,
        event_context={},
        cache_whole_system=True,
        store_tool_names=False,
    )

    assert observation["cache_strategy"] == "system_marker"
    assert observation["tool_count"] == 1
    assert observation["tool_names"] == []
    assert "file_read" not in str(observation)


def test_marker_vendor_without_boundary_is_not_reported_as_system_cache() -> None:
    observation = build_cache_observation(
        system_prompt="ordinary unmarked prompt",
        tools=[],
        vendor=ModelVendor.ANTHROPIC,
        event_context={"session_id": "s1"},
        cache_whole_system=False,
        store_tool_names=True,
    )

    assert observation["cache_strategy"] == "none"
    assert observation["cache_eligible"] is False


def test_cache_observation_measures_typed_dynamic_context_not_user_text() -> None:
    working_context = build_working_context_message("recall")
    assert working_context is not None
    base_messages = [working_context]

    first = build_cache_observation(
        system_prompt=f"stable\n{SYSTEM_PROMPT_CACHE_BOUNDARY}",
        messages=[*base_messages, {"role": "user", "content": "first question"}],
        tools=[],
        vendor=ModelVendor.OPENAI,
        event_context={"session_id": "s1"},
        cache_whole_system=False,
        store_tool_names=True,
    )
    second = build_cache_observation(
        system_prompt=f"stable\n{SYSTEM_PROMPT_CACHE_BOUNDARY}",
        messages=[*base_messages, {"role": "user", "content": "different question"}],
        tools=[],
        vendor=ModelVendor.OPENAI,
        event_context={"session_id": "s1"},
        cache_whole_system=False,
        store_tool_names=True,
    )

    assert first["dynamic_context_chars"] > 0
    assert first["dynamic_context_hash"] == second["dynamic_context_hash"]


def test_cache_observability_settings_default_to_lightweight_enabled() -> None:
    settings = LLMCacheObservabilitySettings()

    assert settings.enabled is True
    assert settings.retention_days == 30
    assert settings.max_rows == 50_000
    assert settings.store_tool_names is True
