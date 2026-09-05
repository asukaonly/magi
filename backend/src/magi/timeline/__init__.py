"""Timeline domain exports."""

from ..awareness.sensor_sync import PullSyncSensor, SensorSyncContext, SourceChangeBatch
from .adapter import TimelineAdapter
from .cluster_builder import TimelineClusterBuilder
from .context_bundle_builder import TimelineContextBundleBuilder
from .state_band_builder import TimelineStateBandBuilder
from .viewport_builder import TimelineViewportBuilder

# TimelineEvent and TimelineContentBlock are L12-internal types.
# Import them from ``magi.timeline.contracts`` directly when needed.

__all__ = [
    "PullSyncSensor",
    "SensorSyncContext",
    "SourceChangeBatch",
    "TimelineAdapter",
    "TimelineClusterBuilder",
    "TimelineContextBundleBuilder",
    "TimelineStateBandBuilder",
    "TimelineViewportBuilder",
]
