"""Helpers for working with strongly-typed payloads carried in Event.data.

These do not change the Event class. The convention is: when an event type
is a domain event, Event.data contains exactly one of the payload dataclasses
defined in magi.events.domain_payloads.
"""
from __future__ import annotations
import logging
from typing import Type, TypeVar
from .events import Event

logger = logging.getLogger(__name__)
T = TypeVar("T")


class PayloadTypeError(TypeError):
    """Raised when Event.data is not the expected payload type."""


def expect_payload(event: Event, expected: Type[T]) -> T:
    """Return event.data cast to `expected`, raising PayloadTypeError on mismatch."""
    if not isinstance(event.data, expected):
        raise PayloadTypeError(
            f"event {event.type!r} expected payload {expected.__name__}, "
            f"got {type(event.data).__name__}"
        )
    return event.data
