"""Timeline domain exports."""

from ..awareness.source_sync import PullSource, SourceSyncContext, SourceChangeBatch
from .adapter import TimelineAdapter
from .cluster_builder import TimelineClusterBuilder
from .context_bundle_builder import TimelineContextBundleBuilder
from .state_band_builder import TimelineStateBandBuilder
from .viewport_builder import TimelineViewportBuilder

# TimelineEvent and TimelineContentBlock are L12-internal types.
# Import them from ``magi.timeline.contracts`` directly when needed.

__all__ = [
    "PullSource",
    "SourceSyncContext",
    "SourceChangeBatch",
    "TimelineAdapter",
    "TimelineClusterBuilder",
    "TimelineContextBundleBuilder",
    "TimelineStateBandBuilder",
    "TimelineViewportBuilder",
]
