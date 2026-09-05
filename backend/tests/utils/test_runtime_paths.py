from __future__ import annotations

from pathlib import Path

from magi.utils.runtime import RuntimePaths


def test_runtime_paths_uses_split_storage_layout(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / ".magi")

    assert runtime_paths.data_dir == tmp_path / ".magi" / "data"
    assert runtime_paths.runtime_dir == tmp_path / ".magi" / "runtime"
    assert runtime_paths.cache_dir == tmp_path / ".magi" / "cache"
    assert runtime_paths.workspaces_dir == tmp_path / ".magi" / "workspaces"
    assert runtime_paths.memory_dir == tmp_path / ".magi" / "data" / "memory"
    assert runtime_paths.chat_dir == tmp_path / ".magi" / "data" / "chat"
    assert runtime_paths.resources_dir == tmp_path / ".magi" / "data" / "resources"
    assert runtime_paths.chat_resources_dir == tmp_path / ".magi" / "data" / "resources" / "chat"

    assert runtime_paths.chat_db_path == runtime_paths.chat_dir / "chat.db"
    assert runtime_paths.memory_db_path == runtime_paths.memory_dir / "memory.db"
    assert runtime_paths.l1_memory_db_path == runtime_paths.memory_dir / "l1_events.db"
    assert runtime_paths.runtime_trace_db_path == runtime_paths.runtime_dir / "runtime_trace.db"
    assert runtime_paths.scheduler_db_path == runtime_paths.runtime_dir / "scheduler.db"
    assert runtime_paths.message_queue_db_path == runtime_paths.runtime_dir / "message_queue.db"
    assert runtime_paths.llm_usage_db_path == runtime_paths.runtime_dir / "llm_usage.db"
    assert runtime_paths.source_state_db_path == runtime_paths.runtime_dir / "source_state.db"
    assert runtime_paths.plugin_cache_dir("screen_time") == (
        tmp_path / ".magi" / "cache" / "plugins" / "screen_time"
    )
    assert runtime_paths.workspace_bucket_dir("repo:demo") == (
        tmp_path / ".magi" / "workspaces" / "repo_demo"
    )
