"""Translate validated logical records at the relational storage boundary."""

import json
from typing import Any

from ..storage_snapshot import FactSnapshot
from .event_mapping import event_record_from_mapping
from ..retrieval.search_text import get_search_text


def snapshot_fact(values: dict[str, Any]) -> dict[str, Any]:
    result = {name: values[name] for name in FactSnapshot.model_fields if name != "metadata"}
    result["metadata"] = (
        json.loads(values["metadata_json"]) if values["metadata_json"] is not None else None
    )
    return result


def fact_row(fact: FactSnapshot) -> dict[str, Any]:
    values = fact.model_dump(mode="json")
    metadata = values.pop("metadata")
    values["metadata_json"] = (
        json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
    )
    return values


def fact_search_text(values: dict[str, Any]) -> str:
    return get_search_text(event_record_from_mapping(values).event)
