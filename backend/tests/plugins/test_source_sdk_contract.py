import pytest

from magi_plugin_sdk.sources import ScopedSourceRuntimePaths

from magi_plugin_sdk.sources import SourceSyncContext as SdkSourceSyncContext


def test_source_sync_context_accepts_runtime_path_protocol(tmp_path) -> None:
    context = SdkSourceSyncContext(
        connection_id="photo-account",
        source_type="example",
        manual=False,
        last_cursor=None,
        last_success_at=None,
        limit=100,
        runtime_paths=ScopedSourceRuntimePaths("photo-account", "photo-library", tmp_path),
        plugin_settings={},
    )

    assert context.connection_id == "photo-account"
    assert context.runtime_paths.plugin_cache_dir("photo-library") == tmp_path
    with pytest.raises(PermissionError):
        context.runtime_paths.plugin_cache_dir("another-plugin")
