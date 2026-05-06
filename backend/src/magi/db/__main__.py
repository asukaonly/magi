"""CLI entry-point: ``python -m magi.db <command> [target] [args...]``.

Wraps Alembic so commands run against the active Magi runtime layout
without forcing the user to repeat ``-x dburl=...``. Supported
commands mirror the most common Alembic verbs:

    python -m magi.db upgrade [target] [revision]   default revision: head
    python -m magi.db downgrade <target> <revision>
    python -m magi.db current [target]
    python -m magi.db history [target]
    python -m magi.db revision <target> -m "message"

When ``target`` is omitted on commands that support it (``upgrade``,
``current``, ``history``), the action runs against every registered
target in order.
"""

from __future__ import annotations

import argparse
import sys

from alembic import command

from .runner import MIGRATION_TARGETS, _build_config
from ..utils.runtime import get_runtime_paths


def _resolve_target(name: str):
    for target in MIGRATION_TARGETS:
        if target.name == name:
            return target
    valid = ", ".join(t.name for t in MIGRATION_TARGETS)
    raise SystemExit(f"unknown target {name!r}; expected one of: {valid}")


def _all_or_one(name: str | None):
    if name is None:
        return MIGRATION_TARGETS
    return (_resolve_target(name),)


def _config_for(target):
    rp = get_runtime_paths()
    db_path = target.db_path(rp)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return _build_config(target, db_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m magi.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("upgrade", help="alembic upgrade head (or to revision)")
    p_up.add_argument("target", nargs="?", default=None)
    p_up.add_argument("revision", nargs="?", default="head")

    p_down = sub.add_parser("downgrade", help="alembic downgrade <revision>")
    p_down.add_argument("target")
    p_down.add_argument("revision")

    p_cur = sub.add_parser("current", help="show current revision(s)")
    p_cur.add_argument("target", nargs="?", default=None)

    p_hist = sub.add_parser("history", help="show revision history")
    p_hist.add_argument("target", nargs="?", default=None)

    p_rev = sub.add_parser("revision", help="create a new revision file")
    p_rev.add_argument("target")
    p_rev.add_argument("-m", "--message", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "upgrade":
        for t in _all_or_one(args.target):
            command.upgrade(_config_for(t), args.revision)
    elif args.cmd == "downgrade":
        command.downgrade(_config_for(_resolve_target(args.target)), args.revision)
    elif args.cmd == "current":
        for t in _all_or_one(args.target):
            print(f"--- {t.name} ---")
            command.current(_config_for(t), verbose=True)
    elif args.cmd == "history":
        for t in _all_or_one(args.target):
            print(f"--- {t.name} ---")
            command.history(_config_for(t), verbose=True)
    elif args.cmd == "revision":
        target = _resolve_target(args.target)
        command.revision(_config_for(target), message=args.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
