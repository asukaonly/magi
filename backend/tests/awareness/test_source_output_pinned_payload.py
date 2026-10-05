"""SourceOutput.pinned_payload contract (RFC #56 P3).

A source sets ``pinned_payload`` to the capture-time full text (obsidian note
body, git commit text) while keeping ``narration.body`` a lean summary. The
field must survive ``to_dict``/``from_dict`` so it reaches the backend projection
(which reads the serialized dict) and lands in the L1 pinned-payload satellite.
"""
from __future__ import annotations

import pytest

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


@pytest.mark.parametrize(
    "pinned,promotion,mode",
    [(None, None, "full"), ("the full frozen note body", "force_full", "evidence_only")],
)
def test_source_output_keeps_lean_narration_and_optional_wire_fields(pinned, promotion, mode):
    kwargs = (
        {}
        if pinned is None
        else {
            "pinned_payload": pinned,
            "promotion_override": promotion,
            "timeline_presentation": TimelinePresentation(
                mode=mode, title="Code: plugin.toml", summary="Screen capture in Code"
            ),
        }
    )
    output = _minimal_output(**kwargs)
    restored = SourceOutput.from_dict(output.to_dict())
    assert restored.pinned_payload == pinned
    assert restored.promotion_override == promotion
    assert restored.timeline_presentation.mode == mode
    assert restored.narration.body == "lean one-line summary"
    assert (
        restored.source_type,
        restored.source_item_id,
        restored.occurred_at,
        restored.captured_at,
    ) == ("obsidian_vault", "note-1", 1.0, 2.0)
    if mode == "evidence_only":
        assert restored.timeline_presentation.title == "Code: plugin.toml"
        assert restored.timeline_presentation.summary == "Screen capture in Code"
