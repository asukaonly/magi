"""Pull-sync contracts for timeline sensors — re-export shim.

The canonical definitions have moved to ``awareness.sensor_sync``.
This module re-exports them for backward compatibility.
"""

from __future__ import annotations

from ..awareness.sensor_sync import PullSyncSensor, SensorSyncContext, SensorSyncResult

__all__ = ["PullSyncSensor", "SensorSyncContext", "SensorSyncResult"]

