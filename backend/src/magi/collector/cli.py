"""Operate one explicitly trusted device source with no agent bootstrap."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import getpass
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import sys
import time
from typing import Iterator


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="magi-server collect", description="Collect one device source without starting a center or agent.")
    commands = root.add_subparsers(dest="action", required=True)
    init = commands.add_parser("init", help="Pair and claim a source; prompts privately for the pairing code")
    init.add_argument("--address", required=True)
    init.add_argument("--connection", required=True)
    init.add_argument("--plugin", type=Path, required=True)
    init.add_argument("--settings-file", type=Path, required=True, help="Local source settings JSON, without credentials")
    init.add_argument("--trust-plugin", action="store_true", required=True, help="Allow this plugin to run with your OS account access")
    init.add_argument("--name", default=socket.gethostname())
    run = commands.add_parser("run", help="Collect and upload until Ctrl+C; restart with the same directory to resume")
    run.add_argument("--once", action="store_true")
    run.add_argument("--interval", type=int, default=60)
    commands.add_parser("status", help="Show queue counts and safe error codes")
    commands.add_parser("retry", help="Retry failed deliveries without changing their identities")
    discard = commands.add_parser("discard", help="Discard failed deliveries, retaining sequence watermarks")
    discard.add_argument("--confirm", action="store_true", required=True)
    return root


@contextmanager
def instance(root: Path) -> Iterator[None]:
    from ..utils.private_data import protect_private_data_tree
    if os.name != "posix":
        raise RuntimeError("Standalone collection currently requires a macOS or Linux host")
    import fcntl
    protect_private_data_tree(root)
    with (root / "collector.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A collector already owns this data directory") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class NoCredentials:
    """This first source protocol supports resource-free, credential-free plugins."""
    def get(self, key: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        raise PermissionError("Collector plugin credentials are not supported")

    def delete(self, key: str) -> None:
        raise PermissionError("Collector plugin credentials are not supported")


def load_plugin(config: dict, root: Path):
    from magi_plugin_sdk.context import PluginContext
    from magi_plugin_sdk.runtime import PluginConnection
    from ..plugins.discovery import load_plugin_manifest
    from ..plugins.package_identity import compute_installed_package_sha256
    from ..plugins.process_runtime import ProcessPluginProxy
    package = Path(config["plugin"])
    if compute_installed_package_sha256(package) != config["plugin_sha256"]:
        raise ValueError("Trusted plugin content changed; initialize a new collector directory after reviewing it")
    manifest = load_plugin_manifest(package / "plugin.toml", source="external")
    platform = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    if manifest.platforms and platform not in manifest.platforms:
        raise ValueError("Collector plugin does not support this operating system")
    if manifest.execution_mode != "trusted_process" or manifest.depends_on:
        raise ValueError("Collector requires a standalone trusted-process source package")
    connection = PluginConnection(connection_id=config["connection_id"], plugin_id=manifest.plugin_id,
                                  display_name="Device collector", enabled=True, settings=config["settings"])
    context = PluginContext(connection, root / "plugin-state", root / "plugin-resources", NoCredentials())
    process = ProcessPluginProxy(manifest, connection, context,
                                 python_executable=os.environ.get("MAGI_PLUGIN_PYTHON"),
                                 dependency_paths=[package / ".deps"] if (package / ".deps").is_dir() else [])
    return manifest, process


async def initialize(args: argparse.Namespace, root: Path) -> None:
    from ..plugins.discovery import load_plugin_manifest
    from ..plugins.package_identity import compute_installed_package_sha256
    from ..plugins.connection_persistence import write_connection_json
    from .transport import CollectorTransport, validate_address
    import re

    if (root / "collector.json").exists():
        raise ValueError("This collector is already paired; use a new dedicated directory")
    if re.fullmatch(r"conn_[0-9a-f]{32}", args.connection) is None:
        raise ValueError("Invalid connection identity")
    source_package = args.plugin.expanduser().resolve(strict=True)
    package = root / "package"
    if package.exists():
        raise ValueError("A previous package snapshot exists; use a new collector directory")
    shutil.copytree(source_package, package, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".git"))
    manifest = load_plugin_manifest(package / "plugin.toml", source="external")
    settings = json.loads(args.settings_file.read_text())
    if not isinstance(settings, dict):
        raise ValueError("Collector settings must be an object")
    config = {"address": validate_address(args.address), "connection_id": args.connection,
              "plugin": str(package), "plugin_sha256": compute_installed_package_sha256(package), "settings": settings}
    process = None
    transport = CollectorTransport(args.address, {})
    try:
        _, process = load_plugin(config, root)
        sources = process.get_sources()
        portable = {str(spec.metadata.get("source_type")) for _, source, spec in sources
                    if spec.metadata.get("remote_collection") == "source.change.v1" and source.supports_pull_sync and not source.supports_watch_mode}
        if not portable:
            raise ValueError("Plugin does not declare a portable remote source")
        code = getpass.getpass("Collector pairing code: ").strip()
        grant = await transport.request("POST", "/server/pair", token=code, body={"name": args.name})
        from uuid import UUID
        UUID(grant["server_id"])
        UUID(grant["client_id"])
        if not isinstance(grant.get("client_credential"), str) or not grant["client_credential"]:
            raise ValueError("Invalid collector credential response")
        # Save before claiming: a failed claim can resume without losing a consumed pairing grant.
        write_connection_json(root / "collector.json", json.dumps({"config": config, "credential": grant}, indent=2))
        transport.credential = grant
        scope = await transport.scope(args.connection, manifest.version, manifest.plugin_id, claim=True)
        if scope["plugin_id"] != manifest.plugin_id or scope["source_type"] not in portable:
            raise ValueError("Granted source does not match the installed collector plugin")
        write_connection_json(root / "scope.json", json.dumps(scope))
        print(f"Collector paired. Data: {root}\nRun: magi-server --data-dir '{root}' collect run")
    finally:
        if process is not None:
            await process.shutdown()
        await transport.close()
        if not (root / "collector.json").exists():
            shutil.rmtree(package)


async def run_collector(args: argparse.Namespace, root: Path, config: dict, credential: dict) -> None:
    from magi_plugin_sdk.sources import SourceSyncContext, ScopedSourceRuntimePaths
    from .queue import CollectorQueue
    from .transport import CollectorTransport
    from ..plugins.connection_persistence import write_connection_json
    import httpx

    if not 1 <= args.interval <= 3600:
        raise ValueError("Collection interval must be between 1 and 3600 seconds")
    manifest, process = load_plugin(config, root)
    transport = CollectorTransport(config["address"], credential)
    queue = None
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    try:
        scope_path = root / "scope.json"
        if scope_path.exists():
            scope = json.loads(scope_path.read_text())
        else:
            scope = await transport.scope(config["connection_id"], manifest.version, manifest.plugin_id, claim=True)
            write_connection_json(scope_path, json.dumps(scope))
        source = next((source for _, source, spec in process.get_sources()
                       if spec.metadata.get("source_type") == scope["source_type"]
                       and spec.metadata.get("remote_collection") == "source.change.v1"), None)
        if source is None or scope["plugin_id"] != manifest.plugin_id:
            raise ValueError("Collector source no longer matches its grant")
        identity = {**scope, "client_id": credential["client_id"],
                    "configuration": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()}
        queue = CollectorQueue(root / "outbox.db", identity)
        next_collection = 0.0
        next_scope_check = 0.0
        while not stopped.is_set():
            if time.monotonic() >= next_scope_check:
                try:
                    current = await transport.scope(config["connection_id"], manifest.version, manifest.plugin_id)
                    if current != scope:
                        raise ValueError("Server or source content generation changed; preserve this queue and pair a new collector directory")
                except httpx.RequestError:
                    pass
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500 and exc.response.status_code != 429:
                        raise
                next_scope_check = time.monotonic() + 60
            if time.monotonic() >= next_collection:
                state = queue.state()
                try:
                    batch = await source.collect_items(SourceSyncContext(
                        connection_id=config["connection_id"], source_type=scope["source_type"], manual=False,
                        last_cursor=state["checkpoint"], last_success_at=state["last_success"], limit=200,
                        runtime_paths=ScopedSourceRuntimePaths(config["connection_id"], manifest.plugin_id, root / "plugin-state"),
                        plugin_settings=config["settings"],
                    ))
                    if not batch.complete and batch.next_cursor == state["checkpoint"]:
                        raise ValueError("An incomplete source batch must advance its checkpoint")
                    queue.append(batch, scope)
                    next_collection = time.monotonic() + (args.interval if batch.complete else 1)
                except BufferError:
                    print("Collector queue is full; collection paused until delivery frees space.")
                    next_collection = time.monotonic() + args.interval
            for _ in range(32):
                if not await transport.deliver(queue, scope):
                    break
            if args.once:
                print(json.dumps(queue.status()))
                break
            try:
                await asyncio.wait_for(stopped.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
    finally:
        if queue is not None:
            queue.close()
        await process.shutdown()
        await transport.close()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = Path(os.environ.get("MAGI_HOME", str(Path.home() / ".magi-collector"))).expanduser().absolute()
    if root in {Path.home(), Path(root.anchor)}:
        raise ValueError("Collector data needs a dedicated directory")
    os.environ["MAGI_HOME"] = str(root)
    try:
        if args.action == "status":
            import sqlite3
            with sqlite3.connect((root / "outbox.db").as_uri() + "?mode=ro", uri=True) as database:
                database.row_factory = sqlite3.Row
                counts = database.execute("SELECT COUNT(*),COALESCE(SUM(terminal),0) FROM events").fetchone()
                head = database.execute("SELECT sequence,attempts,retry_at,failure,terminal FROM events ORDER BY sequence LIMIT 1").fetchone()
                print(json.dumps({"pending": counts[0], "failed": counts[1], "head": dict(head) if head else None}, indent=2))
            return 0
        with instance(root):
            if args.action == "init":
                asyncio.run(initialize(args, root))
                return 0
            paired = json.loads((root / "collector.json").read_text())
            config, credential = paired["config"], paired["credential"]
            if args.action == "run":
                asyncio.run(run_collector(args, root, config, credential))
            else:
                from .queue import CollectorQueue
                scope = json.loads((root / "scope.json").read_text())
                identity = {**scope, "client_id": credential["client_id"],
                            "configuration": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()}
                queue = CollectorQueue(root / "outbox.db", identity)
                try:
                    if args.action != "status":
                        queue.recover(discard=args.action == "discard")
                    print(json.dumps(queue.status(), indent=2))
                finally:
                    queue.close()
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Collector stopped: {exc}")
        return 1
