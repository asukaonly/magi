"""Translate validated logical records at the relational storage boundary."""

import json
from typing import Any

from ..storage_snapshot import FactSnapshot
from .event_mapping import event_record_from_mapping
from ..retrieval.search_text import get_search_text


from magi_plugin_sdk.storage_models.event_snapshot_mapping import (
    snapshot_fact,
    fact_row,
    fact_search_text,
)
