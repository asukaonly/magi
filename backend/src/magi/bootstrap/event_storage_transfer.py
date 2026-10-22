"""Offline event transfer: python -m magi.bootstrap.event_storage_transfer."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml
from magi_plugin_sdk.fs import read_managed_bytes

from ..config.storage_models import StructuredStorageSettings
from ..db.mysql import MysqlSettings
from ..db.runner import run_upgrade_database
from ..utils.runtime import RuntimePaths
from ..utils.worker_instance import WorkerInstance
from .event_storage import migrate_event_storage


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate memory events while the Magi center is stopped"
    )
    parser.add_argument("--root", type=Path, required=True, help="Private Magi center data root")
    parser.add_argument("--target", choices=("sqlite", "mysql"), required=True)
    parser.add_argument(
        "--replace-target",
        action="store_true",
        help="Replace complete event state in the owned destination",
    )
    parser.add_argument(
        "--source-mysql-config",
        type=Path,
        help="Original MySQL settings for a remote-to-remote move",
    )
    arguments = parser.parse_args()
    root = arguments.root.expanduser().absolute()
    with WorkerInstance(root):
        raw = yaml.safe_load(
            read_managed_bytes(root / "config" / "agent.yaml", max_bytes=4 * 1024 * 1024)
        )
        if not isinstance(raw, dict):
            raise ValueError("Agent configuration must be a mapping")
        settings = StructuredStorageSettings.model_validate(raw.get("structured_storage", {}))
        if settings.memory_events != arguments.target:
            raise ValueError(
                "Configure the requested event storage target before running migration"
            )
        source_mysql = None
        if arguments.source_mysql_config is not None:
            source_mysql = MysqlSettings.model_validate(
                yaml.safe_load(
                    read_managed_bytes(
                        arguments.source_mysql_config.expanduser().absolute(), max_bytes=1024 * 1024
                    )
                )
            )
        paths = RuntimePaths(base_dir=root)
        run_upgrade_database("l1", paths.l1_memory_db_path)
        result = asyncio.run(
            migrate_event_storage(
                paths,
                destination=arguments.target,
                mysql=settings.mysql,
                source_mysql=source_mysql,
                replace_destination=arguments.replace_target,
            )
        )
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
