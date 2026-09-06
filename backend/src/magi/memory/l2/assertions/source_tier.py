"""Source-tier classification for ToM assertions.

Two tiers decide conflict precedence in the source-aware upsert:
- "authoritative": the user said it (user_authored / settings_profile) or
  explicitly confirmed any assertion (user_feedback == "confirmed").
- "inferred": everything else, notably source/behavioral observations
  (source_domain == "external_activity").

inferred MUST NEVER supersede authoritative (see write.py upsert).
"""
from __future__ import annotations

# Source domains that represent the user's own statements. NOTE: if a chat
# user-message turns out to carry memory_domain "interaction" (verify against
# real conversation events), add "interaction" here.
_AUTHORITATIVE_SOURCE_DOMAINS = frozenset({"user_authored", "settings_profile"})


def source_tier(*, source_domain: str | None, user_feedback: str | None) -> str:
    """Return "authoritative" or "inferred" for an assertion's provenance."""
    if str(user_feedback or "").strip().casefold() == "confirmed":
        return "authoritative"
    if str(source_domain or "").strip().casefold() in _AUTHORITATIVE_SOURCE_DOMAINS:
        return "authoritative"
    return "inferred"
