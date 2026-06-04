"""Unit tests for resident system tool resolution (ADR-0005 §4)."""
from __future__ import annotations

from magi.tools.system_tools import resolve_resident_system_tools


class _CategoryRegistry:
    """Registry stub supporting ``list_tools(category=...)``."""

    def __init__(self, by_category: dict[str, list[str]]) -> None:
        self._by_category = by_category

    def list_tools(self, category: str | None = None) -> list[str]:
        if category is None:
            return [name for names in self._by_category.values() for name in names]
        return list(self._by_category.get(category, []))


def test_control_category_tools_are_resident() -> None:
    reg = _CategoryRegistry(
        {"control": ["enter_plan_mode", "exit_plan_mode", "todo_write", "ask_user_question"],
         "file": ["file_read", "file_edit"]}
    )
    resident = resolve_resident_system_tools(reg)
    assert "enter_plan_mode" in resident
    assert "ask_user_question" in resident
    assert "todo_write" in resident
    # capability tools are NOT resident
    assert "file_read" not in resident
    assert "file_edit" not in resident


def test_explicit_system_tools_are_resident_but_other_system_tools_are_not() -> None:
    reg = _CategoryRegistry(
        {"control": ["enter_plan_mode"],
         "system": ["detach_to_background", "find-relevant-tools", "bash", "powershell"]}
    )
    resident = resolve_resident_system_tools(reg)
    assert "detach_to_background" in resident  # explicit allowlist
    assert "find-relevant-tools" in resident   # explicit allowlist
    assert "enter_plan_mode" in resident       # control category
    # plain capability/system tools stay out so they are routed normally
    assert "bash" not in resident
    assert "powershell" not in resident


def test_tolerates_registry_without_category_kwarg() -> None:
    class _NoCategoryRegistry:
        def list_tools(self, *args: object, **kwargs: object) -> list[str]:
            if args or kwargs:
                raise TypeError("list_tools() takes no arguments")
            return ["detach_to_background", "file_read"]

    # Must not raise; control set is empty, but explicit allowlist still applies.
    resident = resolve_resident_system_tools(_NoCategoryRegistry())
    assert "detach_to_background" in resident
    assert "file_read" not in resident
