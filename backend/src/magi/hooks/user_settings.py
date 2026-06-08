"""Read user-level configuration from ``~/.claude/settings.json``.

Currently scoped to the ``hooks`` field — the only piece consumed by the
runtime. Schema mirrors Claude Code's format so a user's existing
settings.json works unchanged.

Example::

    {
      "hooks": {
        "PreToolUse": [
          {
            "matcher": "Bash",
            "hooks": [
              {"type": "command", "command": "/usr/local/bin/log-bash"}
            ]
          }
        ],
        "PostToolUse": [
          {"hooks": [{"type": "command", "command": "/usr/local/bin/audit"}]}
        ]
      }
    }
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Tuple

from .contracts import HookEventType
from .registry import HookRegistry

logger = logging.getLogger(__name__)


def _settings_path() -> Path:
    override = os.environ.get("MAGI_CLAUDE_SETTINGS_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "settings.json"


def _load_settings() -> Optional[dict[str, Any]]:
    path = _settings_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("user settings unreadable at %s", path)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("user settings is not valid JSON at %s", path)
        return None
    if not isinstance(data, dict):
        logger.warning("user settings root must be an object at %s", path)
        return None
    return data


def _iter_hook_specs(
    settings: Mapping[str, Any],
) -> Iterable[Tuple[HookEventType, Optional[str], dict[str, Any]]]:
    """Yield ``(event_type, matcher, hook_spec)`` for every shell hook declared."""
    hooks_block = settings.get("hooks")
    if not isinstance(hooks_block, dict):
        return
    for event_name, entries in hooks_block.items():
        try:
            event_type = HookEventType(event_name)
        except ValueError:
            logger.warning("unknown hook event type in settings.json: %s", event_name)
            continue
        if not isinstance(entries, list):
            logger.warning("hook entries for %s must be a list", event_name)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher")
            matcher_str = str(matcher).strip() if matcher else None
            for hook in entry.get("hooks", []) or []:
                if not isinstance(hook, dict):
                    continue
                yield event_type, matcher_str, hook


async def load_user_hook_handlers(registry: HookRegistry) -> int:
    """Discover shell hook declarations and register them into ``registry``.

    Returns the number of registered handlers (0 when no settings file).
    """
    settings = _load_settings()
    if settings is None:
        return 0

    from .shell_handler import build_shell_hook_handler

    count = 0
    for event_type, matcher, spec in _iter_hook_specs(settings):
        spec_type = str(spec.get("type") or "").strip().lower()
        if spec_type != "command":
            logger.warning("unsupported hook spec type=%s — skipping", spec_type or "<missing>")
            continue
        command = str(spec.get("command") or "").strip()
        if not command:
            logger.warning("hook spec missing command — skipping")
            continue
        timeout_raw = spec.get("timeout")
        try:
            timeout_s = float(timeout_raw) if timeout_raw is not None else None
        except (TypeError, ValueError):
            timeout_s = None
        handler = build_shell_hook_handler(
            command=command,
            timeout_s=timeout_s,
            source=f"settings.json:{event_type.value}",
        )
        registry.register(
            event_type,
            handler,
            matcher=matcher,
            source=f"settings.json:{event_type.value}",
        )
        count += 1
    if count:
        logger.info("loaded %d user hook handler(s) from %s", count, _settings_path())
    return count


__all__ = ["load_user_hook_handlers"]
