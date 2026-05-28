"""Per-device availability probing for plugins with SuggestionDescriptors."""

from magi.availability.contracts import AvailabilityReason, AvailabilityResult
from magi.availability.resolver import AvailabilityResolver, ManifestProvider

__all__ = [
    "AvailabilityReason",
    "AvailabilityResult",
    "AvailabilityResolver",
    "ManifestProvider",
]
