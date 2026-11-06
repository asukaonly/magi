"""Real plugin installation and disposable database fixtures for storage contracts."""

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.storage_plugins import build_storage_plugin_runtime
from magi.bootstrap.structured_storage import StructuredStorageModule
from magi.config.storage_models import StructuredStorageSettings, StorageSelection
from magi.plugins.discovery import load_plugin_manifest
from magi.utils.runtime import RuntimePaths


@pytest.fixture(scope="session")
def mysql_package(tmp_path_factory):
    from _shared.mysql_storage_plugin import package
    dependencies = os.environ.get("MAGI_TEST_MYSQL_PLUGIN_DEPS")
    if not dependencies:
        pytest.skip("Set MAGI_TEST_MYSQL_PLUGIN_DEPS to the installed plugin dependencies")
    root = tmp_path_factory.mktemp("storage-package")
    target = root / "storage-mysql"
    shutil.copytree(package, target, ignore=shutil.ignore_patterns("__pycache__", ".deps"))
    shutil.copytree(dependencies, target / ".deps", ignore=shutil.ignore_patterns("__pycache__"))
    return target


@pytest.fixture
async def mysql_settings():
    port = os.environ.get("MAGI_TEST_MYSQL_PORT")
    if not port:
        pytest.skip("Set MAGI_TEST_MYSQL_PORT for real storage integration")
    from _shared.mysql_storage_plugin.database import MysqlDatabase, MysqlSettings
    from sqlalchemy import text
    settings = MysqlSettings(host="127.0.0.1", port=int(port), database="magi_test_architecture",
        user=os.environ.get("MAGI_TEST_MYSQL_USER", "root"), password=os.environ.get("MAGI_TEST_MYSQL_PASSWORD", ""), tls=False)
    admin = MysqlDatabase(settings)
    name = "magi_test_plugin_" + uuid4().hex
    async with admin.transaction() as db:
        await db.execute(text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"))
    try:
        yield settings.model_copy(update={"database": name})
    finally:
        async with admin.transaction() as db:
            await db.execute(text(f"DROP DATABASE {name}"))
        await admin.close()


def select(paths, settings):
    path = paths.config_dir / "agent.yaml"
    document = yaml.safe_load(path.read_text()) if path.exists() else {}
    document["structured_storage"] = settings.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document))


async def install_mysql(paths, package, settings):
    manifest = load_plugin_manifest(package / "plugin.toml", source="external")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "agent.yaml").write_text(yaml.safe_dump({"plugins": {"scan_paths": [str(package.parent)]}}))
    index = paths.config_dir / "plugins" / "index.yaml"
    index.parent.mkdir(exist_ok=True)
    index.write_text(yaml.safe_dump({"packages": {manifest.plugin_id: {
        "source": "external", "manifest_path": str(package / "plugin.toml"), "trusted": True,
        "consented_capabilities": [item.model_dump(mode="json") for item in manifest.capabilities],
    }}}))
    runtime = build_storage_plugin_runtime(paths)
    try:
        connection = runtime.connections.create("storage-mysql", display_name="Test database", enabled=True,
            settings=settings.model_dump(mode="json", exclude={"password", "ca_file"}),
            credentials={"password": settings.password.get_secret_value()})
        return StorageSelection(connection_id=connection.connection_id, provider_id="mysql")
    finally:
        await runtime.close()


async def start(paths, settings):
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.config = SimpleNamespace(structured_storage=settings)
    context.plugins.storage_runtime = build_storage_plugin_runtime(paths)
    module = StructuredStorageModule(context)
    try:
        await module.init()
    except BaseException:
        await context.plugins.storage_runtime.close()
        raise
    return context, module


async def stop(context, module):
    try:
        await module.shutdown()
    finally:
        await context.plugins.storage_runtime.close()


@pytest.fixture
async def storage_environment(tmp_path, mysql_settings, mysql_package):
    paths = RuntimePaths(base_dir=tmp_path)
    remote = await install_mysql(paths, mysql_package, mysql_settings)
    return paths, remote
