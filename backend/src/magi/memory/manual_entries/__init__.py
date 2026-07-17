"""User-authored memory entries.

A first-class data source alongside Chrome / screen / chat. Captures
text + images + mood + optional time/place context that the user
writes by hand. Persisted to ``manual_entries`` and projected to L1 so
the rest of the memory pipeline (episode formation, themes, mood,
diary) picks it up without a parallel ingestion path.
"""

from .asset_store import ManualEntryAssetStore
from .l1_projector import ManualEntryL1Projector
from .models import ManualEntry
from .recovery import ManualEntryRecoveryService, ManualEntryRecoveryStats
from .store import ManualEntryStore
from .weather_fetcher import WeatherFetcher, weather_category
from .workflow import ManualEntryWorkflow

__all__ = [
    "ManualEntry",
    "ManualEntryStore",
    "ManualEntryAssetStore",
    "ManualEntryL1Projector",
    "ManualEntryRecoveryService",
    "ManualEntryRecoveryStats",
    "ManualEntryWorkflow",
    "WeatherFetcher",
    "weather_category",
]
