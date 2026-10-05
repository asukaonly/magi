from __future__ import annotations

from magi.agent.execution.tool_context_formatters import ToolContextFormatterRegistry
from magi.tools.builtin.bash_tool import BashTool
from magi.tools.builtin.powershell_tool import PowerShellTool
from magi.tools.core_tools import core_tool_classes_for_os
from magi.tools.platform_tools import native_shell_tool_name


def test_core_inventory_exposes_exactly_the_native_shell_for_each_platform():
    for os_name, expected, excluded in [
        ("nt", PowerShellTool, BashTool),
        ("posix", BashTool, PowerShellTool),
    ]:
        classes = core_tool_classes_for_os(os_name)
        assert [cls for cls in classes if cls in (BashTool, PowerShellTool)] == [expected]
        assert excluded not in classes
        assert native_shell_tool_name(os_name) == expected().schema.name


def test_shell_context_formatting_is_shared_by_both_dialects() -> None:
    registry = ToolContextFormatterRegistry.build_default(
        max_items=10,
        max_text_chars=3,
        memory_formatter=lambda data: data,
    )
    payload = {
        "command": "echo",
        "return_code": 0,
        "stdout": "abcdef",
        "stderr": "",
        "stdout_total_bytes": 6,
        "stderr_total_bytes": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timed_out": False,
    }
    bash_formatter = registry.get("bash")
    powershell_formatter = registry.get("powershell")

    assert bash_formatter is not None
    assert powershell_formatter is not None
    assert bash_formatter(payload) == powershell_formatter(payload)
    assert powershell_formatter(payload)["stdout_preview"] == "def"
