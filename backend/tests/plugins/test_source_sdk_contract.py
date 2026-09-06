import pytest

from magi_plugin_sdk.sources import ScopedSourceRuntimePaths

from magi.awareness import ContentBlock as BackendContentBlock
from magi.awareness import L2BatchPolicy as BackendL2BatchPolicy
from magi.awareness import PluginRuntimePaths as BackendPluginRuntimePaths
from magi.awareness import Source as BackendSourceBase
from magi.awareness import SourceMemoryPolicy as BackendSourceMemoryPolicy
from magi.awareness import SourceOutput as BackendSourceOutput
from magi.awareness import SourceOutputMetadata as BackendSourceOutputMetadata
from magi.awareness import SourceSyncContext as BackendSourceSyncContext
from magi.awareness import SourceChangeBatch as BackendSourceChangeBatch
from magi_plugin_sdk.sources import ContentBlock as SdkContentBlock
from magi_plugin_sdk.sources import L2BatchPolicy as SdkL2BatchPolicy
from magi_plugin_sdk.sources import PluginRuntimePaths as SdkPluginRuntimePaths
from magi_plugin_sdk.sources import Source as SdkSourceBase
from magi_plugin_sdk.sources import SourceMemoryPolicy as SdkSourceMemoryPolicy
from magi_plugin_sdk.sources import SourceOutput as SdkSourceOutput
from magi_plugin_sdk.sources import SourceOutputMetadata as SdkSourceOutputMetadata
from magi_plugin_sdk.sources import SourceSyncContext as SdkSourceSyncContext
from magi_plugin_sdk.runtime import SourceChangeBatch as SdkSourceChangeBatch


def test_backend_source_contracts_reexport_sdk_symbols() -> None:
    assert BackendContentBlock is SdkContentBlock
    assert BackendL2BatchPolicy is SdkL2BatchPolicy
    assert BackendPluginRuntimePaths is SdkPluginRuntimePaths
    assert BackendSourceBase is SdkSourceBase
    assert BackendSourceMemoryPolicy is SdkSourceMemoryPolicy
    assert BackendSourceOutput is SdkSourceOutput
    assert BackendSourceOutputMetadata is SdkSourceOutputMetadata
    assert BackendSourceSyncContext is SdkSourceSyncContext
    assert BackendSourceChangeBatch is SdkSourceChangeBatch


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
