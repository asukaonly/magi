"""Compact persona-routing brief for the unified ContextDecider router.

ContextDecider runs once per turn and now also picks the persona's
register, active signature triggers, and applicable quiet-hour conditions.
The set of triggers and quiet-hour conditions is **per-persona** (Seven's
triggers are not Echo's), so the menu of options must be injected into the
ContextDecider user prompt at request time. Static ContextDecider system
prompt only knows the fixed product-level register enum and JSON shape.

This helper renders the per-persona menu in a short markdown block. It must
be cheap to build (~200 tokens) and not leak full persona configuration —
the LLM only needs the matching surface (trigger_id + activates_when,
quiet_hour condition strings) to choose from, not the full behavior_shifts
or examples.
"""

from __future__ import annotations

from .loader import PersonalityConfig


def build_persona_routing_brief(config: PersonalityConfig | None) -> str:
    """Render a compact markdown menu of this persona's triggers + quiet hours.

    Returns the empty string when the persona has no triggers and no
    persona-defined quiet hours; in that case the ContextDecider only needs
    the static register menu (already in its system prompt) and the prompt
    builder can omit this section entirely.
    """
    if config is None:
        return ""

    trigger_lines: list[str] = []
    for trigger in config.signature_triggers:
        trigger_id = str(trigger.trigger_id or "").strip()
        condition = str(trigger.activates_when or "").strip()
        if not trigger_id or not condition:
            continue
        trigger_lines.append(f"- {trigger_id}: {condition}")

    quiet_hour_lines: list[str] = []
    for quiet_hour in config.quiet_hours:
        condition = str(quiet_hour.condition or "").strip()
        if not condition:
            continue
        quiet_hour_lines.append(f"- {condition}")

    if not trigger_lines and not quiet_hour_lines:
        return ""

    sections: list[str] = ["## Persona Routing Menu"]

    if trigger_lines:
        sections.append("")
        sections.append(
            "### Available Persona Triggers"
        )
        sections.append(
            "Pick 0-2 trigger_ids from the list below for active_trigger_ids when the"
            " user's turn clearly matches that activation condition. Do not invent IDs"
            " that are not listed."
        )
        sections.extend(trigger_lines)

    if quiet_hour_lines:
        sections.append("")
        sections.append(
            "### Persona-Defined Quiet Hour Conditions"
        )
        sections.append(
            "Return any of the condition strings below in quiet_hour_hints when the"
            " current turn matches that condition. Use the exact wording shown."
        )
        sections.extend(quiet_hour_lines)

    sections.append("")
    return "\n".join(sections)


__all__ = ["build_persona_routing_brief"]
