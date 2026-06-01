"""Location resolution layer.

Provides a multi-source location lookup with priority ordering and
time-weighted aggregation. Sources currently implemented:

  - IPGeo  (city accuracy, no permission)
  - WiFi   (~100m accuracy via Mozilla Location Service)
  - Photo  (10m accuracy via EXIF GPS, when photo plugin is enabled)

Consumers ask the resolver for the dominant location of a time window;
the resolver tries each source by priority and aggregates samples
weighted by per-source validity intervals.
"""

from .models import LocationSample, ResolvedPlace
from .store import LocationSampleStore, PlaceGeocodeCache

# LocationResolver lives in .resolver and is re-exported lazily by callers
# that need it (avoids a hard import dependency on source backends here).

__all__ = [
    "LocationSample",
    "ResolvedPlace",
    "LocationSampleStore",
    "PlaceGeocodeCache",
]
