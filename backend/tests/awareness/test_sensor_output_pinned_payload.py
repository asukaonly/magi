"""SensorOutput.pinned_payload contract (RFC #56 P3).

A sensor sets ``pinned_payload`` to the capture-time full text (obsidian note
body, git commit text) while keeping ``narration.body`` a lean summary. The
field must survive ``to_dict``/``from_dict`` so it reaches the backend projection
(which reads the serialized dict) and lands in the L1 pinned-payload satellite.
"""
from __future__ import annotations

from magi_plugin_sdk.sensors import (
    ActivityFacet,
    SensorActivity,
    SensorNarration,
    SensorOutput,
)


def _minimal_output(**kwargs) -> SensorOutput:
    return SensorOutput(
        source_type="obsidian_vault",
        source_item_id="note-1",
        occurred_at=1.0,
        captured_at=2.0,
        activity=SensorActivity(
            source=ActivityFacet(code="vault", i18n_key="src.vault"),
            action=ActivityFacet(code="noted", i18n_key="act.noted"),
        ),
        narration=SensorNarration(body="lean one-line summary"),
        **kwargs,
    )


def test_pinned_payload_defaults_to_none() -> None:
    assert _minimal_output().pinned_payload is None


def test_pinned_payload_round_trips_through_dict() -> None:
    out = _minimal_output(pinned_payload="the full frozen note body")
    restored = SensorOutput.from_dict(out.to_dict())
    assert restored.pinned_payload == "the full frozen note body"
