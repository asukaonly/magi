"""Exercise a real Git reader in a separate plugin process and its durable device checkpoint."""
import json
from pathlib import Path
import subprocess
import os
import sys
import shutil

import pytest
from magi.collector.cli import load_plugin
from magi.collector.queue import CollectorQueue
from magi.plugins.package_identity import compute_installed_package_sha256
from magi_plugin_sdk.sources import SourceSyncContext, ScopedSourceRuntimePaths


@pytest.mark.skipif(sys.platform != "darwin", reason="The first portable Git collector pilot is validated on macOS")
@pytest.mark.asyncio
async def test_real_git_worker_restarts_with_checkpoint_and_deduplicates_overlap(tmp_path):
    source_package = Path(os.environ.get("MAGI_PLUGINS_REPO", Path(__file__).resolve().parents[4] / "magi-plugins")) / "plugins/git_activity"
    if not source_package.is_dir():
        pytest.skip("The companion plugin checkout is required")
    package = tmp_path / "package"
    shutil.copytree(source_package, package, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    repo = tmp_path / "repository"
    repo.mkdir()
    for command in (["git", "init", "-q"], ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "First change"]):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    config = {"plugin": str(package), "plugin_sha256": compute_installed_package_sha256(package),
              "connection_id": "conn_11111111111111111111111111111111",
              "settings": {"sources": {"git_activity": {"enabled": True, "repos": [str(repo)], "initial_sync_policy": "lookback_days", "initial_sync_lookback_days": 30}}}}
    root = tmp_path / "collector"
    root.mkdir()
    manifest, process = load_plugin(config, root)
    queue = CollectorQueue(root / "outbox.db", {"connection": config["connection_id"]})
    try:
        source = process.get_sources()[0][1]
        context = SourceSyncContext(connection_id=config["connection_id"], source_type="git_activity", manual=False,
                    last_cursor=None, last_success_at=None, limit=200,
                    runtime_paths=ScopedSourceRuntimePaths(config["connection_id"], manifest.plugin_id, root / "plugin-state"), plugin_settings=config["settings"])
        batch = await source.collect_items(context)
        assert batch.changes
        scope = {"connection_id": config["connection_id"], "connection_epoch": "11111111-1111-1111-1111-111111111111",
                 "plugin_id": manifest.plugin_id, "plugin_version": manifest.version, "source_type": "git_activity"}
        queue.append(batch, scope)
        event = json.loads(queue.head()["event"])
        await process.shutdown()
        _, process = load_plugin(config, root)
        state = queue.state()
        from dataclasses import replace
        second = await process.get_sources()[0][1].collect_items(replace(context, last_cursor=state["checkpoint"], last_success_at=state["last_success"]))
        count = queue.status()["pending"]
        queue.append(second, scope)
        assert queue.status()["pending"] == count
        # The center worker receives only collected data; it needs no access to the original repository.
        center_config = {**config, "settings": {"sources": {"git_activity": {"enabled": True, "repos": []}}}}
        center_root = tmp_path / "center"
        center_root.mkdir()
        _, center = load_plugin(center_config, center_root)
        try:
            center_source = center.get_sources()[0][1]
            item = await center_source.fetch_item(event["payload"]["data"]["source_change"]["payload"])
            output = await center_source.build_output(item)
            assert output.narration.body
            assert output.narration.title == repo.name
            assert output.source_type == "git_activity"
            assert output.source_item_id == event["payload"]["data"]["source_change"]["object_id"]
        finally:
            await center.shutdown()
    finally:
        queue.close()
        await process.shutdown()
