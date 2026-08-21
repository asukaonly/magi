from __future__ import annotations

from magi.agent.execution.tool_context_formatters import ToolContextFormatterRegistry
from magi.tools.builtin.bash_tool import BashTool
from magi.tools.builtin.powershell_tool import PowerShellTool
from magi.tools.core_tools import core_tool_classes_for_os
from magi.tools.platform_tools import native_shell_tool_name


def test_native_shell_tool_name_is_platform_specific() -> None:
    assert native_shell_tool_name("nt") == "powershell"
    assert native_shell_tool_name("posix") == "bash"


def test_core_tools_expose_only_powershell_on_windows() -> None:
    classes = core_tool_classes_for_os("nt")

    assert PowerShellTool in classes
    assert BashTool not in classes


def test_core_tools_expose_only_bash_on_posix() -> None:
    classes = core_tool_classes_for_os("posix")

    assert BashTool in classes
    assert PowerShellTool not in classes


def test_shell_context_formatting_is_shared_by_both_dialects() -> None:
    registry = ToolContextFormatterRegistry.build_default(
        max_items=10,
        max_text_chars=3,
        memory_formatter=lambda data: data,
    )
    payload = {"command": "echo", "return_code": 0, "stdout": "abcdef", "stderr": ""}
    bash_formatter = registry.get("bash")
    powershell_formatter = registry.get("powershell")

    assert bash_formatter is not None
    assert powershell_formatter is not None
    assert bash_formatter(payload) == powershell_formatter(payload)
    assert powershell_formatter(payload)["stdout_preview"] == "abc"
