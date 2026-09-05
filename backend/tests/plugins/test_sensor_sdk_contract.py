import pytest

from magi_plugin_sdk.sensors import ScopedSensorRuntimePaths

from magi.awareness import ContentBlock as BackendContentBlock
from magi.awareness import L2BatchPolicy as BackendL2BatchPolicy
from magi.awareness import PluginRuntimePaths as BackendPluginRuntimePaths
from magi.awareness import SensorBase as BackendSensorBase
from magi.awareness import SensorMemoryPolicy as BackendSensorMemoryPolicy
from magi.awareness import SensorOutput as BackendSensorOutput
from magi.awareness import SensorOutputMetadata as BackendSensorOutputMetadata
from magi.awareness import SensorSyncContext as BackendSensorSyncContext
from magi.awareness import SourceChangeBatch as BackendSourceChangeBatch
from magi_plugin_sdk.sensors import ContentBlock as SdkContentBlock
from magi_plugin_sdk.sensors import L2BatchPolicy as SdkL2BatchPolicy
from magi_plugin_sdk.sensors import PluginRuntimePaths as SdkPluginRuntimePaths
from magi_plugin_sdk.sensors import SensorBase as SdkSensorBase
from magi_plugin_sdk.sensors import SensorMemoryPolicy as SdkSensorMemoryPolicy
from magi_plugin_sdk.sensors import SensorOutput as SdkSensorOutput
from magi_plugin_sdk.sensors import SensorOutputMetadata as SdkSensorOutputMetadata
from magi_plugin_sdk.sensors import SensorSyncContext as SdkSensorSyncContext
from magi_plugin_sdk.runtime import SourceChangeBatch as SdkSourceChangeBatch


def test_backend_sensor_contracts_reexport_sdk_symbols() -> None:
    assert BackendContentBlock is SdkContentBlock
    assert BackendL2BatchPolicy is SdkL2BatchPolicy
    assert BackendPluginRuntimePaths is SdkPluginRuntimePaths
    assert BackendSensorBase is SdkSensorBase
    assert BackendSensorMemoryPolicy is SdkSensorMemoryPolicy
    assert BackendSensorOutput is SdkSensorOutput
    assert BackendSensorOutputMetadata is SdkSensorOutputMetadata
    assert BackendSensorSyncContext is SdkSensorSyncContext
    assert BackendSourceChangeBatch is SdkSourceChangeBatch


def test_sensor_sync_context_accepts_runtime_path_protocol(tmp_path) -> None:
    context = SdkSensorSyncContext(
        connection_id="photo-account",
        source_type="example",
        manual=False,
        last_cursor=None,
        last_success_at=None,
        limit=100,
        runtime_paths=ScopedSensorRuntimePaths("photo-account", "photo-library", tmp_path),
        plugin_settings={},
    )

    assert context.connection_id == "photo-account"
    assert context.runtime_paths.plugin_cache_dir("photo-library") == tmp_path
    with pytest.raises(PermissionError):
        context.runtime_paths.plugin_cache_dir("another-plugin")
