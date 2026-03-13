"""Normalization helpers for Terminal History timeline ingestion."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .types import TerminalCommand


def normalize_terminal_command(item: dict[str, Any] | TerminalCommand, sensor: Any) -> dict[str, Any]:
    """Normalize terminal command data into timeline event format.

    Args:
        item: Terminal command data (dict or TerminalCommand object)
        sensor: The sensor instance

    Returns:
        Dictionary with normalized event data
    """
    # Handle both dict and TerminalCommand object inputs
    if isinstance(item, TerminalCommand):
        command = item
    else:
        command = TerminalCommand(
            command=item.get("command", ""),
            executed_at=item.get("executed_at", datetime.now()),
            shell=item.get("shell", "unknown"),
            history_line=item.get("history_line", 0),
            raw_line=item.get("raw_line", ""),
        )

    # Build title (truncate long commands)
    title = command.command[:100] + "..." if len(command.command) > 100 else command.command

    # Build summary with execution time
    executed_str = command.executed_at.strftime("%Y-%m-%d %H:%M:%S")
    summary = f"{command.command[:50]}... @ {executed_str}" if len(command.command) > 50 else f"{command.command} @ {executed_str}"

    # Build content blocks
    content_blocks = [
        {
            "kind": "text",
            "value": f"命令：{command.command}"
        },
        {
            "kind": "text",
            "value": f"执行时间：{executed_str}"
        },
        {
            "kind": "text",
            "value": f"Shell：{command.shell}"
        },
    ]

    # Build tags
    tags = ["terminal", "command", command.shell]

    # Build provenance
    provenance = {
        "sensor_id": sensor.sensor_id,
        "shell": command.shell,
        "history_line": command.history_line,
        "command_length": len(command.command),
    }

    # Create unique event ID
    event_id = f"terminal_{int(command.executed_at.timestamp())}_{abs(hash(command.command) % 10000):04d}"

    return {
        "event_id": event_id,
        "source_type": "terminal_history",
        "source_item_id": event_id,
        "occurred_at": command.executed_at.timestamp(),
        "title": title,
        "summary": summary,
        "content_blocks": content_blocks,
        "tags": tags,
        "provenance": provenance,
    }
