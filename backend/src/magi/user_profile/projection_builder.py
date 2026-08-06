"""Build user profile projections from L2 assertions."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Any

from ..memory.derivation_revision import DerivationRevision
from .derivation import derive_age_years, derive_birth_year, parse_iso_date
from .models import (
    DEFAULT_USER_ID,
    UserProfileProjection,
)
from .projection_freshness import (
    assertion_records_highwater,
    list_current_profile_assertions,
)

_FIELD_TRAITS: dict[str, str] = {
    "identity.real_name": "real_name",
    "identity.birth_date": "birth_date",
    "identity.birth_year": "birth_year",
    "identity.location.home": "home_location",
    "communication.address.preferred": "preferred_form_of_address",
}

_SOURCE_PRIORITY = {
    "settings_profile": 400,
    "user_feedback": 300,
    "user_authored": 300,
    "chat": 100,
}
_STATE_PRIORITY = {
    "stable": 300,
    "corroborated": 200,
    "tentative": 100,
}


class UserProfileProjectionBuilder:
    """Select the current user profile view from active L2 profile assertions."""

    def __init__(self, l2_store: Any):
        self._l2_store = l2_store

    @property
    def l2_store(self) -> Any:
        """Return the authoritative source used for freshness checks."""

        return self._l2_store

    async def build(self, user_id: str = DEFAULT_USER_ID) -> UserProfileProjection:
        entity_id = f"user:{user_id}"
        derivation_revision = await DerivationRevision.capture(self._l2_store, entity_id)
        assertions = await self._list_profile_assertions(entity_id)
        selected, conflicts = self._select_current_assertions(assertions)
        projection = _new_projection(user_id=user_id, entity_id=entity_id)
        field_sources: dict[str, Any] = {}
        communication: dict[str, Any] = {}

        _apply_profile_traits(
            projection,
            selected=selected,
            field_sources=field_sources,
        )
        _apply_disallowed_forms(
            selected,
            communication=communication,
            field_sources=field_sources,
        )
        _apply_stated_age(
            projection,
            selected=selected,
            field_sources=field_sources,
        )
        _apply_birth_date_derivations(projection, field_sources=field_sources)
        _apply_display_name(projection)
        _finalize_projection(
            projection,
            communication=communication,
            field_sources=field_sources,
            conflicts=conflicts,
        )
        await derivation_revision.ensure_current(self._l2_store)
        projection.source_revision = derivation_revision.source_revision
        projection.source_generation = int(derivation_revision.clear_generation or 0)
        projection.input_assertion_highwater = assertion_records_highwater(assertions)
        return projection

    async def _list_profile_assertions(self, entity_id: str) -> list[dict[str, Any]]:
        return await list_current_profile_assertions(
            self._l2_store,
            entity_id=entity_id,
        )

    def _select_current_assertions(
        self,
        assertions: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for assertion in assertions:
            trait_name = str(assertion.get("trait_name") or "").strip()
            if not trait_name:
                continue
            grouped.setdefault(trait_name, []).append(assertion)

        selected: dict[str, dict[str, Any]] = {}
        conflicts: dict[str, Any] = {}
        for trait_name, candidates in grouped.items():
            ordered = sorted(candidates, key=_assertion_score, reverse=True)
            selected[trait_name] = ordered[0]
            unique_values = {_stable_value(candidate.get("trait_value")) for candidate in ordered}
            if len(unique_values) > 1:
                conflicts[trait_name] = {
                    "selected_assertion_id": ordered[0].get("assertion_id"),
                    "candidates": [
                        {
                            "assertion_id": candidate.get("assertion_id"),
                            "value": _parse_assertion_value(candidate.get("trait_value")),
                            "source": candidate.get("source_domain"),
                            "confidence": candidate.get("confidence_score"),
                            "validation_state": candidate.get("validation_state"),
                        }
                        for candidate in ordered[:5]
                    ],
                }
        return selected, conflicts


def _new_projection(*, user_id: str, entity_id: str) -> UserProfileProjection:
    return UserProfileProjection(
        user_id=user_id,
        entity_id=entity_id,
        refreshed_at=time.time(),
    )


def _apply_profile_traits(
    projection: UserProfileProjection,
    *,
    selected: dict[str, dict[str, Any]],
    field_sources: dict[str, Any],
) -> None:
    for trait_name, field_name in _FIELD_TRAITS.items():
        assertion = selected.get(trait_name)
        if not assertion:
            continue
        _apply_profile_trait(projection, field_name=field_name, assertion=assertion)
        field_sources[field_name] = _source_record(assertion)


def _apply_profile_trait(
    projection: UserProfileProjection,
    *,
    field_name: str,
    assertion: dict[str, Any],
) -> None:
    value = _parse_assertion_value(assertion.get("trait_value"))
    if field_name == "birth_year":
        int_value = _coerce_int(value)
        if int_value is not None:
            projection.birth_year = int_value
        return
    setattr(projection, field_name, _first_text(value))


def _apply_disallowed_forms(
    selected: dict[str, dict[str, Any]],
    *,
    communication: dict[str, Any],
    field_sources: dict[str, Any],
) -> None:
    disallowed = selected.get("communication.address.disallowed")
    if not disallowed:
        return
    communication["disallowed_forms_of_address"] = _as_text_list(
        _parse_assertion_value(disallowed.get("trait_value"))
    )
    field_sources["disallowed_forms_of_address"] = _source_record(disallowed)


def _apply_stated_age(
    projection: UserProfileProjection,
    *,
    selected: dict[str, dict[str, Any]],
    field_sources: dict[str, Any],
) -> None:
    stated_age = selected.get("identity.age.stated")
    if not stated_age or projection.age_years:
        return
    age_value = _coerce_int(_parse_assertion_value(stated_age.get("trait_value")))
    if age_value is None:
        return
    projection.age_years = age_value
    projection.age_as_of = _date_from_timestamp(stated_age.get("last_validated_at"))
    field_sources["age_years"] = _source_record(stated_age)


def _apply_birth_date_derivations(
    projection: UserProfileProjection,
    *,
    field_sources: dict[str, Any],
) -> None:
    birth_date = parse_iso_date(projection.birth_date)
    if birth_date is None:
        return
    projection.birth_year = projection.birth_year or derive_birth_year(birth_date)
    projection.age_years = derive_age_years(birth_date)
    projection.age_as_of = date.today().isoformat()
    field_sources["age_years"] = {
        "source": "derived",
        "derived_from": "identity.birth_date",
        "derivation": "date_diff_years",
        "as_of": projection.age_as_of,
    }
    field_sources.setdefault(
        "birth_year",
        {
            "source": "derived",
            "derived_from": "identity.birth_date",
            "derivation": "birth_date_year",
        },
    )


def _apply_display_name(projection: UserProfileProjection) -> None:
    projection.display_name = (
        projection.preferred_form_of_address or projection.real_name or projection.display_name
    )


def _finalize_projection(
    projection: UserProfileProjection,
    *,
    communication: dict[str, Any],
    field_sources: dict[str, Any],
    conflicts: dict[str, Any],
) -> None:
    communication.update(_communication_section(projection))
    projection.identity = _identity_section(projection)
    projection.communication = communication
    projection.preferences = {}
    projection.state = {}
    projection.field_sources = field_sources
    projection.field_conflicts = conflicts
    projection.completeness_score = _completeness_score(projection)


def _identity_section(projection: UserProfileProjection) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "real_name": projection.real_name,
            "birth_date": projection.birth_date,
            "birth_year": projection.birth_year,
            "age_years": projection.age_years,
            "home_location": projection.home_location,
        }.items()
        if value not in (None, "")
    }


def _communication_section(projection: UserProfileProjection) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "preferred_form_of_address": projection.preferred_form_of_address,
        }.items()
        if value not in (None, "")
    }


def _assertion_score(assertion: dict[str, Any]) -> tuple[int, float, float]:
    source = str(assertion.get("source_domain") or "").strip()
    state = str(assertion.get("validation_state") or "").strip()
    confidence = float(assertion.get("confidence_score") or 0.0)
    updated_at = float(assertion.get("updated_at") or assertion.get("last_validated_at") or 0.0)
    return (
        _SOURCE_PRIORITY.get(source, 0) + _STATE_PRIORITY.get(state, 0),
        confidence,
        updated_at,
    )


def _parse_assertion_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in '[{"':
        return value
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _stable_value(value: Any) -> str:
    parsed = _parse_assertion_value(value)
    return (
        json.dumps(parsed, ensure_ascii=False, sort_keys=True)
        if isinstance(parsed, (dict, list))
        else str(parsed)
    )


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    if value is None:
        return ""
    return str(value).strip()


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        return [text for text in (str(item or "").strip() for item in value) if text]
    return []


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_from_timestamp(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value)).date().isoformat()
    except (TypeError, ValueError, OSError):
        return date.today().isoformat()


def _source_record(assertion: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": assertion.get("source_domain") or "",
        "assertion_id": assertion.get("assertion_id") or "",
        "confidence": assertion.get("confidence_score"),
        "validation_state": assertion.get("validation_state") or "",
        "updated_at": assertion.get("updated_at") or assertion.get("last_validated_at"),
    }


def _completeness_score(projection: UserProfileProjection) -> float:
    fields = [
        projection.real_name,
        projection.birth_date,
        projection.preferred_form_of_address,
        projection.home_location,
    ]
    filled = sum(1 for value in fields if str(value or "").strip())
    return round(filled / len(fields), 2)
