"""Readable collector outcomes with an explicit machine-output mode."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any


def line(message: str, tone: str = "info") -> str:
    icons = (sys.stdout.isatty() or sys.stderr.isatty()) and os.environ.get("TERM") != "dumb"
    mark = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}[tone] if icons else {
        "info": "[INFO]", "success": "[OK]", "warning": "[WARN]", "error": "[ERROR]",
    }[tone]
    clean = "".join(char for char in message if char == "\n" or char.isprintable())
    return f"{mark} {clean}"


def command(root: Path, *args: str) -> str:
    return shlex.join([os.environ.get("MAGI_CLI_LAUNCHER", "magi-server"), "--data-dir", str(root), "collect", *args])


def emit(value: dict[str, Any], text: str, *, machine: bool) -> None:
    print(json.dumps(value, indent=2) if machine else text)


def queue_report(value: dict[str, Any], root: Path, title: str = "Collector queue") -> str:
    pending, failed = value["pending"], value["failed"]
    # Pending is the total stored count, including terminal failures.
    text = line(title, "warning" if failed else "info")
    text += f"\nWaiting to send: {pending - failed}\nFailed (manual action needed): {failed}\nData: {root}"
    head = value.get("head")
    if head:
        text += f"\nFirst queued item: {head['sequence']}\nDelivery attempts: {head['attempts']}"
        if head.get("failure"):
            text += f"\nLast error code: {head['failure']}"
    if failed:
        text += f"\n\nAfter resolving the error, retry failed deliveries:\n  {command(root, 'retry')}"
    elif pending:
        text += f"\n\nRun the collector to send queued items:\n  {command(root, 'run')}"
    else:
        text += "\nNo queued items. This does not indicate whether the collector is running."
    return text
