"""Sensor sync contracts - re-exported from magi-plugin-sdk."""

from magi_plugin_sdk.sensors import (  # noqa: F401
    PluginRuntimePaths,
    PullSyncSensor,
    SensorSyncContext,
    ScopedSensorRuntimePaths,
    SourceChange,
    SourceChangeBatch,
)

__all__ = [
    "PluginRuntimePaths",
    "PullSyncSensor",
    "SensorSyncContext",
    "ScopedSensorRuntimePaths",
    "SourceChange",
    "SourceChangeBatch",
]
