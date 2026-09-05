#!/usr/bin/env python3
r"""Check real plugin workers against the host registrars without invoking actions.

Run from the host checkout with its backend dependencies installed::

    python scripts/check-plugin-runtime.py --plugins-repo ../magi-plugins \
        --python ../magi-plugins/.venv/bin/python --report /tmp/plugin-runtime.json

The worker Python needs the companion plugins' third-party dependencies. If
--python is omitted, use that repository's .venv; never fall back to a system
worker interpreter. SDK/backend imports come from this checkout, and each worker
receives only its manifest's declared library roots. Connections, settings paths,
and dummy credentials are temporary. Operation authorization always denies; no
collection, channel start, tool, settings action, or provider action is invoked.
The optional report records each package; any failure exits with status 1.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback
from typing import Any

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument(
    "--plugins-repo",
    type=Path,
    required=True,
    help="Companion repository containing plugins/*/plugin.toml",
)
parser.add_argument(
    "--python",
    type=Path,
    dest="worker_python",
    help="Worker interpreter with plugin dependencies (default: companion .venv)",
)
parser.add_argument("--report", type=Path, help="Optional JSON report destination")
parser.add_argument(
    "--package", action="append", help="Optional executable package ids to rerun"
)
args = parser.parse_args()
HOST_ROOT = Path(__file__).resolve().parents[1]
args.plugins_repo = args.plugins_repo.expanduser().resolve()
if not (args.plugins_repo / "plugins").is_dir():
    parser.error("--plugins-repo must contain a plugins directory")
if args.worker_python is None:
    interpreter = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    args.worker_python = args.plugins_repo / ".venv" / interpreter
# Preserve the venv path: resolving its Python symlink loses the dependency environment.
args.worker_python = args.worker_python.expanduser().absolute()
if not args.worker_python.is_file() or not os.access(args.worker_python, os.X_OK):
    parser.error(
        "Worker Python is unavailable; pass --python with the companion dependency interpreter"
    )
if sys.flags.optimize:
    parser.error("Run without -O: acceptance checks require assertions")
if args.report is not None:
    args.report = args.report.expanduser().absolute()
sys.path[:0] = [str(HOST_ROOT / "sdk/src"), str(HOST_ROOT / "backend/src")]

from magi.plugins.connection_settings import validate_connection_settings
from magi.plugins.contribution_registration import PluginContributionRegistrar
from magi.plugins.discovery import load_plugin_manifest
from magi.plugins.history_importers import HistoryImporterRegistry
from magi.plugins.operations import PluginOperationRegistry
from magi.plugins.process_runtime import ProcessLimits, ProcessPluginProxy
from magi.plugins.providers import PluginProviderRegistry
from magi.plugins.sensors import SensorRegistry
from magi.plugins.skills import PluginSkillRegistry
from magi.hooks.registry import HookRegistry
from magi.skills.indexer import SkillIndexer
from magi.skills.loader import SkillLoader
from magi.tools.registry import ToolRegistry
from magi_plugin_sdk import PluginManifest
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import (
    PluginConnection,
    SDK_VERSION,
    PLUGIN_PROTOCOL_VERSION,
)
from magi_plugin_sdk.versioning import parse_plugin_version


class Credentials:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = dict(values)

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def read_setting(settings: dict[str, Any], key: str) -> Any:
    if key in settings:
        return settings[key]
    value = settings
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def write_setting(settings: dict[str, Any], key: str, value: Any) -> None:
    if key in settings:
        settings[key] = deepcopy(value)
        return
    parts = key.split(".")
    for part in parts[:-1]:
        settings = settings.setdefault(part, {})
    settings[parts[-1]] = deepcopy(value)


def explicit_connection(
    manifest: PluginManifest, root: Path, number: int
) -> tuple[PluginConnection, PluginContext]:
    connection_id = f"acceptance-{manifest.plugin_id}-{number}"
    directory = root / connection_id
    (directory / "empty-source").mkdir(parents=True)
    settings = deepcopy(manifest.default_settings)
    credentials = {}
    for field in manifest.settings_fields:
        if field.type == "secret":
            credentials[field.key] = (
                "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmno"
            )
            continue
        if read_setting(settings, field.key) is None and field.default is not None:
            write_setting(settings, field.key, field.default)
    for field in manifest.settings_fields:
        if field.type == "secret" or not field.required:
            continue
        if field.depends_on_key and field.depends_on_values:
            if str(read_setting(settings, field.depends_on_key)).lower() not in [
                item.lower() for item in field.depends_on_values
            ]:
                continue
        if read_setting(settings, field.key) not in (None, "", []):
            continue
        if field.type == "path":
            value = str(directory / "empty-source")
            if isinstance(field.default, list):
                value = [value]
        elif field.type == "tags":
            value = ["acceptance"]
        elif field.type == "switch":
            value = False
        elif field.type == "number":
            value = field.minimum if field.minimum is not None else 1
        elif field.type == "select":
            value = field.options[0].value
        else:
            value = "acceptance"
        write_setting(settings, field.key, value)
    connection = PluginConnection(
        connection_id=connection_id,
        plugin_id=manifest.plugin_id,
        display_name=f"Acceptance {number}",
        enabled=True,
        settings=settings,
        credential_refs={
            key: f"dummy-{number}-{index}" for index, key in enumerate(credentials)
        },
    )
    validate_connection_settings(connection, manifest.settings_fields)
    context = PluginContext(
        connection,
        directory / "state",
        directory / "resources",
        Credentials(credentials),
    )
    context.state_dir.mkdir(parents=True)
    context.resources_dir.mkdir(parents=True)
    return connection, context


def revision(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def write_report(report: dict[str, Any]) -> None:
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


async def main() -> int:
    manifests = {}
    for path in sorted((args.plugins_repo / "plugins").glob("*/plugin.toml")):
        manifest = load_plugin_manifest(path, source="external")
        assert manifest.plugin_id not in manifests, manifest.plugin_id
        assert manifest.protocol_version == PLUGIN_PROTOCOL_VERSION
        assert parse_plugin_version(manifest.min_sdk_version) <= parse_plugin_version(
            SDK_VERSION
        )
        manifests[manifest.plugin_id] = manifest
    libraries = {
        key: value for key, value in manifests.items() if value.kind == "library"
    }
    executable_ids = set(manifests) - set(libraries)
    if not executable_ids:
        parser.error("No executable plugin manifests found")
    if args.package and set(args.package) - executable_ids:
        parser.error(
            f"Unknown executable packages: {sorted(set(args.package) - executable_ids)}"
        )
    report = {
        "sdk_version": SDK_VERSION,
        "protocol": PLUGIN_PROTOCOL_VERSION,
        "host_root": str(HOST_ROOT),
        "host_head": revision(HOST_ROOT),
        "companion_root": str(args.plugins_repo),
        "companion_head": revision(args.plugins_repo),
        "worker_python": str(args.worker_python),
        "libraries": [
            {"plugin_id": key, "version": item.version, "path": item.plugin_dir}
            for key, item in libraries.items()
        ],
        "scope": "Actual worker bootstrap/catalog, host contribution normalization, two connection ownership, disable/unregister/drained shutdown. No collection, channel start, tool, settings or provider action invocations.",
        "packages": [],
    }
    with tempfile.TemporaryDirectory(
        prefix="magi-registration-acceptance-"
    ) as temporary:
        root = Path(temporary)
        connections = {}
        tools, sensors, hooks, history = (
            ToolRegistry(),
            SensorRegistry(),
            HookRegistry(),
            HistoryImporterRegistry(),
        )
        indexer = SkillIndexer(skill_locations=[root / "empty-skills"])
        loader = SkillLoader(indexer)
        skills = PluginSkillRegistry(tools, indexer, loader)
        operations = PluginOperationRegistry(
            tools, get_connection=connections.get, authorize=lambda *_: False
        )
        providers = PluginProviderRegistry(get_connection=connections.get)
        registrar = PluginContributionRegistrar(
            tool_registry=tools,
            sensor_registry=sensors,
            history_importer_registry=history,
            hook_registry_provider=lambda: hooks,
            skill_registrar=skills,
            operation_registrar=operations,
            provider_registrar=providers,
        )

        def registry_snapshot() -> dict[str, Any]:
            return {
                "tools": sorted(tools._tools),
                "operations": sorted(operations._entries),
                "sensors": sorted(spec.sensor_id for spec in sensors.list_specs()),
                "history": sorted(
                    (item.plugin_id, item.connection_id, item.importer_id)
                    for item in history.list()
                ),
                "hooks": hooks.total(),
                "skills": sorted(tools._skills),
                "skill_index": sorted(indexer._plugin_skills),
                "providers": sorted(providers._providers),
                "registration_owners": sorted(registrar._registrations),
                "tool_aliases": sorted(tools._tool_aliases.items()),
            }

        def owner_snapshot(connection_id: str) -> dict[str, Any]:
            return {
                "tools": {
                    key: value
                    for key, value in tools._tool_instances.items()
                    if getattr(value, "_plugin_connection_id", None) == connection_id
                },
                "operations": {
                    key: value
                    for key, value in operations._entries.items()
                    if key[0] == connection_id
                },
                "sensors": {
                    item.sensor_id: item.sensor
                    for item in sensors.snapshot_user_content_clear_targets()
                    if item.connection_id == connection_id
                },
                "history": {
                    item.importer_id: item
                    for item in history.list()
                    if item.connection_id == connection_id
                },
                "providers": {
                    key: value
                    for key, value in providers._providers.items()
                    if value.connection_id == connection_id
                },
                "disposers": list(registrar._registrations.get(connection_id, ())),
            }

        empty = registry_snapshot()
        for manifest in manifests.values():
            if manifest.kind == "library" or (
                args.package and manifest.plugin_id not in args.package
            ):
                continue
            entry = {
                "plugin_id": manifest.plugin_id,
                "version": manifest.version,
                "manifest_sha256": hashlib.sha256(
                    Path(manifest.manifest_path).read_bytes()
                ).hexdigest(),
                "declared_types": sorted(
                    kind.value for kind in manifest.contribution_types
                ),
                "depends_on": list(manifest.depends_on),
                "connections": [],
                "status": "failed",
            }
            workers = []
            stage = "dependencies"
            try:
                dependencies = []
                for name in manifest.depends_on:
                    assert (
                        name in libraries
                    ), f"Dependency {name} is absent or executable"
                    dependencies.append(Path(libraries[name].plugin_dir))
                for number in (1, 2):
                    stage = f"connection_{number}_settings"
                    connection, context = explicit_connection(manifest, root, number)
                    connections[connection.connection_id] = connection
                    stage = f"connection_{number}_worker_bootstrap"
                    worker = await asyncio.to_thread(
                        ProcessPluginProxy,
                        manifest,
                        connection,
                        context,
                        python_executable=report["worker_python"],
                        dependency_paths=dependencies,
                        limits=ProcessLimits(startup_timeout=15),
                    )
                    workers.append((connection, worker))
                    stage = f"connection_{number}_catalog"
                    raw_tools = [kind().get_schema() for kind in worker.get_tools()]
                    result = {
                        "connection_id": connection.connection_id,
                        "pid": worker.diagnostics["pid"],
                        "tools": [
                            {
                                "name": schema.name,
                                "effect": schema.effect_class,
                                "replay": schema.effect_replay_policy,
                                "input_schema": schema.json_input_schema(),
                            }
                            for schema in raw_tools
                        ],
                    }
                    entry["connections"].append(result)
                    stage = f"connection_{number}_host_registration"
                    contributed = registrar.register(
                        plugin_id=manifest.plugin_id,
                        connection_id=connection.connection_id,
                        manifest=manifest,
                        plugin_instance=worker,
                    )
                    assert {item.contribution_type for item in contributed} == set(
                        manifest.contribution_types
                    )
                    result["contribution_counts"] = dict(
                        Counter(item.contribution_type.value for item in contributed)
                    )
                    result["normalized_operations"] = [
                        binding.spec.model_dump(mode="json")
                        for key, binding in operations._entries.items()
                        if key[0] == connection.connection_id
                    ]
                    for schema in raw_tools:
                        normalized = operations._entries[
                            (connection.connection_id, schema.name)
                        ].spec
                        assert normalized.input_schema == schema.json_input_schema()
                        assert normalized.effect == schema.effect_class
                        assert normalized.replay == schema.effect_replay_policy
                    for name in tools.list_tools():
                        alias = tools.exported_tool_name(name)
                        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alias), alias
                        assert tools.resolve_tool_name(alias) == name
                    before_duplicate = registry_snapshot()
                    try:
                        registrar.register(
                            plugin_id=manifest.plugin_id,
                            connection_id=connection.connection_id,
                            manifest=manifest,
                            plugin_instance=worker,
                        )
                    except ValueError as exc:
                        assert "already registered" in str(exc)
                    else:
                        raise AssertionError(
                            "Duplicate owner registration unexpectedly succeeded"
                        )
                    assert registry_snapshot() == before_duplicate
                stage = "owner_safe_disable"
                first, second = workers
                second_snapshot = owner_snapshot(second[0].connection_id)
                connections[first[0].connection_id] = first[0].model_copy(
                    update={"enabled": False, "revision": 1}
                )
                registrar.unregister(first[0].connection_id)
                await first[1].shutdown()
                assert first[1].diagnostics["exit_code"] is not None
                assert owner_snapshot(second[0].connection_id) == second_snapshot
                assert second[1].diagnostics["healthy"]
                connections[second[0].connection_id] = second[0].model_copy(
                    update={"enabled": False, "revision": 1}
                )
                registrar.unregister(second[0].connection_id)
                await second[1].shutdown()
                assert second[1].diagnostics["exit_code"] is not None
                assert registry_snapshot() == empty, registry_snapshot()
                entry["status"] = "passed"
            except Exception as exc:
                entry.update(
                    failed_stage=stage,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
            finally:
                cleanup = []
                for connection, worker in workers:
                    try:
                        registrar.unregister(connection.connection_id)
                        await worker.shutdown()
                        assert worker.diagnostics["exit_code"] is not None
                    except Exception as exc:
                        cleanup.append(f"{type(exc).__name__}: {exc}")
                    connections.pop(connection.connection_id, None)
                if cleanup or registry_snapshot() != empty:
                    entry.update(
                        status="failed",
                        cleanup_errors=cleanup,
                        remaining_registrations=registry_snapshot(),
                    )
                report["packages"].append(entry)
                write_report(report)
                print(
                    json.dumps(
                        {
                            "plugin_id": entry["plugin_id"],
                            "status": entry["status"],
                            "stage": entry.get("failed_stage"),
                            "error": entry.get("error"),
                            "contributions": [
                                item.get("contribution_counts")
                                for item in entry["connections"]
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    report["summary"] = dict(Counter(item["status"] for item in report["packages"]))
    report["summary"]["libraries"] = len(libraries)
    report["summary"]["workers"] = sum(
        len(item["connections"]) for item in report["packages"]
    )
    write_report(report)
    print(json.dumps(report["summary"]), flush=True)
    return int(any(item["status"] != "passed" for item in report["packages"]))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
