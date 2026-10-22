"""Offline channel storage transfer: python -m magi.bootstrap.channel_storage_transfer."""

from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import yaml
from magi_plugin_sdk.fs import read_managed_bytes

from ..config.storage_models import StructuredStorageSettings
from ..db.runner import run_upgrade_database
from ..utils.runtime import RuntimePaths
from ..utils.worker_instance import WorkerInstance
from .channel_storage import migrate_channel_storage


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate channel state while the Magi center is stopped"
    )
    parser.add_argument("--root", type=Path, required=True, help="Private Magi center data root")
    parser.add_argument("--target", choices=("sqlite", "mysql"), required=True)
    parser.add_argument(
        "--replace-target",
        action="store_true",
        help="Replace all channel state in the owned destination",
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
        if settings.channels != arguments.target:
            raise ValueError(
                "Configure the requested channel storage target before running migration"
            )
        paths = RuntimePaths(base_dir=root)
        run_upgrade_database("channels", paths.channels_db_path)
        result = asyncio.run(
            migrate_channel_storage(paths, settings, replace_destination=arguments.replace_target)
        )
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
