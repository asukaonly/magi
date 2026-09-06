"""SourceOutput.pinned_payload contract (RFC #56 P3).

A source sets ``pinned_payload`` to the capture-time full text (obsidian note
body, git commit text) while keeping ``narration.body`` a lean summary. The
field must survive ``to_dict``/``from_dict`` so it reaches the backend projection
(which reads the serialized dict) and lands in the L1 pinned-payload satellite.
"""
from __future__ import annotations

from magi_plugin_sdk.sources import (
    ActivityFacet,
    SourceActivity,
    SourceNarration,
    SourceOutput,
    TimelinePresentation,
)


def _minimal_output(**kwargs) -> SourceOutput:
    return SourceOutput(
        source_type="obsidian_vault",
        source_item_id="note-1",
        occurred_at=1.0,
        captured_at=2.0,
        activity=SourceActivity(
            source=ActivityFacet(code="vault", i18n_key="src.vault"),
            action=ActivityFacet(code="noted", i18n_key="act.noted"),
        ),
        narration=SourceNarration(body="lean one-line summary"),
        **kwargs,
    )


def test_pinned_payload_defaults_to_none() -> None:
    assert _minimal_output().pinned_payload is None


def test_pinned_payload_round_trips_through_dict() -> None:
    out = _minimal_output(pinned_payload="the full frozen note body")
    restored = SourceOutput.from_dict(out.to_dict())
    assert restored.pinned_payload == "the full frozen note body"


def test_promotion_override_defaults_to_none() -> None:
    # RFC #56 P4 escape hatch field.
    assert _minimal_output().promotion_override is None


def test_promotion_override_round_trips_through_dict() -> None:
    out = _minimal_output(promotion_override="force_full")
    restored = SourceOutput.from_dict(out.to_dict())
    assert restored.promotion_override == "force_full"


def test_timeline_presentation_defaults_to_full() -> None:
    assert _minimal_output().timeline_presentation.mode == "full"


def test_timeline_presentation_round_trips_through_dict() -> None:
    out = _minimal_output(
        timeline_presentation=TimelinePresentation(
            mode="evidence_only",
            title="Code: plugin.toml",
            summary="Screen capture in Code",
        )
    )
    restored = SourceOutput.from_dict(out.to_dict())
    assert restored.timeline_presentation.mode == "evidence_only"
    assert restored.timeline_presentation.title == "Code: plugin.toml"
    assert restored.timeline_presentation.summary == "Screen capture in Code"
