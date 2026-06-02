"""Typed identifiers for the identity layer.

``MagiUserID`` is the canonical internal identifier for the human user.
It is a ``NewType`` wrapper around ``str`` — at runtime it IS a string,
but type-checkers (mypy / pyright / ruff TC005) treat it as distinct
so a raw ``str`` (e.g. a leaked external WeChat OpenID) cannot
accidentally satisfy a ``MagiUserID`` parameter.

``ExternalIdentity`` is the typed input to ``IdentityResolver.resolve``:
the channel scheme (``"weixin"``, ``"telegram"``, …) paired with the
channel-side user id. This is what flows into the system at ingress
boundaries (channels / api / awareness) and is the ONLY shape allowed
to carry an external identifier; everything downstream sees
``MagiUserID``.

See ``docs/identity-architecture.md`` for the design intent and the
BASELINE+RATCHET adoption strategy for the type discipline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NewType


# At runtime this is just ``str``. The point is the TYPE-CHECKER view:
# functions that accept ``MagiUserID`` reject plain ``str`` callers,
# forcing them to go through ``IdentityResolver.resolve()`` or pull
# the canonical default from ``identity.defaults``.
MagiUserID = NewType("MagiUserID", str)


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """A channel-scoped external identifier (WeChat OpenID, Telegram chat_id, …).

    Pairing the channel scheme with the external id makes the binding
    table key unambiguous: two different channels may legitimately
    share the same ``external_user_id`` string (e.g. a numeric id),
    but ``(channel_type, external_user_id)`` is unique.

    ``channel_type`` matches the SDK ``Channel.channel_type`` scheme
    used everywhere else (``"weixin"``, ``"telegram"``, ``"chat_sse"``).
    """

    channel_type: str
    external_user_id: str

    def __post_init__(self) -> None:
        if not self.channel_type or not self.channel_type.strip():
            raise ValueError("ExternalIdentity.channel_type must be non-empty")
        if not self.external_user_id or not self.external_user_id.strip():
            raise ValueError("ExternalIdentity.external_user_id must be non-empty")


__all__ = ["MagiUserID", "ExternalIdentity"]
