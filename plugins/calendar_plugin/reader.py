"""EventKit data reader using pyobjc bridge."""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from magi.core.logger import get_logger

from .exceptions import PlatformNotSupportedError
from .types import CalendarEvent, CalendarListEntry, Participant

logger = get_logger(__name__)


class EventKitReader:
    """EventKit data reader using pyobjc bridge."""

    def __init__(self) -> None:
        self._event_store: Any = None
        self._is_available: Optional[bool] = None
        self._ek_module: dict[str, Any] | None = None
        self._foundation_module: dict[str, Any] | None = None

    def _ensure_platform(self) -> None:
        """Raise error if not running on macOS."""
        if sys.platform != "darwin":
            raise PlatformNotSupportedError()

    def _import_frameworks(self) -> None:
        """Import EventKit and Foundation frameworks lazily."""
        if self._ek_module is not None:
            return

        try:
            import EventKit as eventkit  # type: ignore[import-not-found]

            self._ek_module = {
                "EKEventStore": getattr(eventkit, "EKEventStore", None),
                "EKEntityTypeEvent": getattr(eventkit, "EKEntityTypeEvent", None),
                "EKAuthorizationStatusNotDetermined": getattr(eventkit, "EKAuthorizationStatusNotDetermined", None),
                "EKAuthorizationStatusRestricted": getattr(eventkit, "EKAuthorizationStatusRestricted", None),
                "EKAuthorizationStatusDenied": getattr(eventkit, "EKAuthorizationStatusDenied", None),
                "EKAuthorizationStatusAuthorized": getattr(eventkit, "EKAuthorizationStatusAuthorized", None),
                "EKAuthorizationStatusFullAccess": getattr(eventkit, "EKAuthorizationStatusFullAccess", None),
                "EKAuthorizationStatusWriteOnly": getattr(eventkit, "EKAuthorizationStatusWriteOnly", None),
                "EKParticipantStatusAccepted": getattr(eventkit, "EKParticipantStatusAccepted", None),
                "EKParticipantStatusDeclined": getattr(eventkit, "EKParticipantStatusDeclined", None),
                "EKParticipantStatusTentative": getattr(eventkit, "EKParticipantStatusTentative", None),
                "EKParticipantStatusPending": getattr(eventkit, "EKParticipantStatusPending", None),
            }
        except ImportError:
            self._ek_module = {}

        try:
            import Foundation as foundation  # type: ignore[import-not-found]

            self._foundation_module = {
                "NSDate": getattr(foundation, "NSDate", None),
                "NSRunLoop": getattr(foundation, "NSRunLoop", None),
            }
        except ImportError:
            self._foundation_module = {}

    def _read_value(self, target: Any, *names: str, default: Any = None) -> Any:
        """Read the first available attribute or method result from an ObjC proxy."""
        for name in names:
            attribute = getattr(target, name, None)
            if attribute is None:
                continue
            if callable(attribute):
                try:
                    return attribute()
                except TypeError:
                    continue
            return attribute
        return default

    def _call_selector(self, target: Any, selector_names: list[str], *args: Any) -> Any:
        """Call the first available selector."""
        for selector_name in selector_names:
            method = getattr(target, selector_name, None)
            if callable(method):
                return method(*args)
        raise AttributeError(f"Unable to find selector on {target!r}: {selector_names}")

    def _to_nsdate(self, value: datetime) -> Any:
        """Convert Python datetime into NSDate."""
        NSDate = (self._foundation_module or {}).get("NSDate")
        if NSDate is None:
            return None
        return self._call_selector(NSDate, ["dateWithTimeIntervalSince1970_"], float(value.timestamp()))

    def _to_datetime(self, value: Any) -> datetime | None:
        """Convert NSDate-like objects into Python datetimes."""
        if isinstance(value, datetime):
            return value
        if value is None:
            return None
        timestamp_getter = getattr(value, "timeIntervalSince1970", None)
        if callable(timestamp_getter):
            try:
                return datetime.fromtimestamp(float(timestamp_getter()))
            except Exception:
                return None
        return None

    def _drain_run_loop(self, state: dict[str, bool], *, timeout_seconds: float = 5.0) -> bool:
        """Wait for an asynchronous EventKit callback to complete."""
        NSRunLoop = (self._foundation_module or {}).get("NSRunLoop")
        NSDate = (self._foundation_module or {}).get("NSDate")
        if NSRunLoop is None or NSDate is None:
            return False
        run_loop = self._call_selector(NSRunLoop, ["currentRunLoop"])
        deadline = datetime.now().timestamp() + timeout_seconds
        while not state["done"] and datetime.now().timestamp() < deadline:
            self._call_selector(
                run_loop,
                ["runUntilDate_"],
                self._call_selector(NSDate, ["dateWithTimeIntervalSinceNow_"], 0.05),
            )
        return state["done"]

    @property
    def event_store(self) -> Any:
        """Get or create EKEventStore instance."""
        if self._event_store is None:
            self._ensure_platform()
            self._import_frameworks()
            ek_event_store = (self._ek_module or {}).get("EKEventStore")
            if ek_event_store is None:
                return None
            self._event_store = ek_event_store.alloc().init()
        return self._event_store

    def is_available(self) -> bool:
        """Check if EventKit is available on this device."""
        if self._is_available is not None:
            return self._is_available

        if sys.platform != "darwin":
            logger.warning(
                "Calendar EventKit bridge unavailable",
                reason="platform_not_supported",
                platform=sys.platform,
            )
            self._is_available = False
            return False

        try:
            self._import_frameworks()
            self._is_available = (self._ek_module or {}).get("EKEventStore") is not None
            if not self._is_available:
                logger.warning(
                    "Calendar EventKit bridge unavailable",
                    reason="missing_eventkit_bridge",
                    platform=sys.platform,
                )
            return bool(self._is_available)
        except Exception as exc:
            logger.warning(
                "Calendar EventKit bridge unavailable",
                reason="eventkit_import_failed",
                platform=sys.platform,
                error=str(exc),
            )
            self._is_available = False
            return False

    def get_authorization_status(self) -> str:
        """
        Get authorization status for calendar access.

        Returns:
            One of: "not_determined", "denied", "authorized", "unavailable"
        """
        if not self.is_available():
            logger.warning(
                "Calendar authorization status unavailable",
                reason="eventkit_unavailable",
            )
            return "unavailable"

        try:
            entity_type = (self._ek_module or {}).get("EKEntityTypeEvent")
            if entity_type is None:
                logger.warning(
                    "Calendar authorization status unavailable",
                    reason="missing_event_entity_type",
                )
                return "unavailable"
            ek_event_store = (self._ek_module or {}).get("EKEventStore")
            if ek_event_store is None:
                logger.warning(
                    "Calendar authorization status unavailable",
                    reason="missing_event_store_class",
                )
                return "unavailable"
            status = self._call_selector(
                ek_event_store,
                ["authorizationStatusForEntityType_"],
                entity_type,
            )
            if status in {
                (self._ek_module or {}).get("EKAuthorizationStatusAuthorized"),
                (self._ek_module or {}).get("EKAuthorizationStatusFullAccess"),
            }:
                return "authorized"
            if status == (self._ek_module or {}).get("EKAuthorizationStatusNotDetermined"):
                return "not_determined"
            if status in {
                (self._ek_module or {}).get("EKAuthorizationStatusDenied"),
                (self._ek_module or {}).get("EKAuthorizationStatusRestricted"),
                (self._ek_module or {}).get("EKAuthorizationStatusWriteOnly"),
            }:
                return "denied"
            logger.warning(
                "Calendar authorization status unavailable",
                reason="unknown_authorization_status",
                status_value=status,
            )
            return "unavailable"
        except Exception as exc:
            logger.warning(
                "Calendar authorization status unavailable",
                reason="authorization_status_query_failed",
                error=str(exc),
            )
            return "unavailable"

    def _request_calendar_access(self) -> tuple[bool, Any]:
        """Request full calendar access from EventKit."""
        completion_state = {"done": False}
        result = {"granted": False, "error": None}

        def completion_handler(granted: bool, error: Any) -> None:
            result["granted"] = bool(granted)
            result["error"] = error
            completion_state["done"] = True

        self._call_selector(
            self.event_store,
            ["requestFullAccessToEventsWithCompletion_"],
            completion_handler,
        )
        completed = self._drain_run_loop(completion_state)
        if not completed:
            return False, "timeout"
        return bool(result["granted"]), result["error"]

    def request_authorization(self) -> bool:
        """
        Request calendar access authorization.

        Returns:
            True if authorization was granted, False otherwise.
        """
        if not self.is_available():
            logger.warning(
                "Calendar authorization request skipped",
                reason="eventkit_unavailable",
            )
            return False

        try:
            granted, error = self._request_calendar_access()
            if error is not None or not granted:
                logger.warning(
                    "Calendar authorization request was not granted",
                    granted=bool(granted),
                    error=str(error) if error is not None else None,
                )
            return bool(granted) and error is None
        except Exception as exc:
            logger.warning(
                "Calendar authorization request failed",
                error=str(exc),
            )
            return False

    def _extract_participants(self, event: Any) -> list[Participant]:
        """Extract participants from an EventKit event."""
        attendees = self._read_value(event, "attendees", default=[]) or []
        participant_status_map = {
            (self._ek_module or {}).get("EKParticipantStatusAccepted"): "accepted",
            (self._ek_module or {}).get("EKParticipantStatusDeclined"): "declined",
            (self._ek_module or {}).get("EKParticipantStatusTentative"): "tentative",
            (self._ek_module or {}).get("EKParticipantStatusPending"): "pending",
        }
        participants: list[Participant] = []
        for attendee in attendees:
            name = self._read_value(attendee, "name", default="Unknown")
            raw_status = self._read_value(attendee, "participantStatus")
            url_value = self._read_value(attendee, "URL")
            url_string = self._read_value(url_value, "absoluteString", default=None) if url_value is not None else None
            email = None
            if isinstance(url_string, str):
                parsed = urlparse(url_string)
                email = parsed.path or None
            participants.append(
                Participant(
                    name=str(name),
                    email=email,
                    status=participant_status_map.get(raw_status, "pending"),
                )
            )
        return participants

    def _serialize_event(self, event: Any) -> dict[str, Any] | None:
        """Convert an EventKit event into a Python dict."""
        event_id = self._read_value(event, "eventIdentifier")
        start_time = self._to_datetime(self._read_value(event, "startDate"))
        end_time = self._to_datetime(self._read_value(event, "endDate"))
        if not event_id or start_time is None or end_time is None:
            return None

        calendar = self._read_value(event, "calendar")
        calendar_name = self._read_value(calendar, "title", default="Calendar") if calendar is not None else "Calendar"
        recurrence_rules = self._read_value(event, "recurrenceRules", default=[]) or []
        recurrence_rule = None
        if recurrence_rules:
            recurrence_rule = str(recurrence_rules[0])

        url_value = self._read_value(event, "URL")
        url = self._read_value(url_value, "absoluteString", default=None) if url_value is not None else None

        serialized = {
            "event_id": str(event_id),
            "title": str(self._read_value(event, "title", default="Untitled Event")),
            "start_time": start_time,
            "end_time": end_time,
            "is_all_day": bool(self._read_value(event, "isAllDay", default=False)),
            "location": self._read_value(event, "location"),
            "notes": self._read_value(event, "notes"),
            "calendar_name": str(calendar_name),
            "calendar_color": "",
            "participants": [
                {"name": participant.name, "email": participant.email, "status": participant.status}
                for participant in self._extract_participants(event)
            ],
            "is_recurring": bool(recurrence_rules),
            "recurrence_rule": recurrence_rule,
            "url": url,
        }
        logger.info(
            "Calendar event serialized",
            event_id=serialized["event_id"],
            title=serialized["title"],
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            is_all_day=serialized["is_all_day"],
            calendar_name=serialized["calendar_name"],
            location=serialized["location"],
            has_notes=bool(serialized["notes"]),
            participant_count=len(serialized["participants"]),
            is_recurring=serialized["is_recurring"],
        )
        return serialized

    def list_calendars(self) -> list[CalendarListEntry]:
        """List calendars available to the current user."""
        if not self.is_available():
            return []

        entity_type = (self._ek_module or {}).get("EKEntityTypeEvent")
        if entity_type is None:
            return []

        available_calendars = self._call_selector(
            self.event_store,
            ["calendarsForEntityType_"],
            entity_type,
        ) or []

        calendars: list[CalendarListEntry] = []
        for calendar in available_calendars:
            calendar_id = self._read_value(calendar, "calendarIdentifier")
            title = self._read_value(calendar, "title", default="Calendar")
            source = self._read_value(calendar, "source")
            source_id = self._read_value(source, "sourceIdentifier", default=None) if source is not None else None
            source_title = self._read_value(source, "title", default="Other") if source is not None else "Other"
            if not calendar_id or not title:
                continue
            calendars.append(
                CalendarListEntry(
                    calendar_id=str(calendar_id),
                    title=str(title),
                    source_id=str(source_id or source_title),
                    source_title=str(source_title),
                    accent_color=None,
                )
            )
        return calendars

    def _execute_events_query(
        self,
        start_date: datetime,
        end_date: datetime,
        calendar_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute an EventKit query for the provided time range."""
        if not self.is_available():
            return []

        entity_type = (self._ek_module or {}).get("EKEntityTypeEvent")
        start_nsdate = self._to_nsdate(start_date)
        end_nsdate = self._to_nsdate(end_date)
        if entity_type is None or start_nsdate is None or end_nsdate is None:
            return []

        selected_calendars = None
        if calendar_ids:
            available_calendars = self._call_selector(
                self.event_store,
                ["calendarsForEntityType_"],
                entity_type,
            ) or []
            selected_calendars = [
                calendar
                for calendar in available_calendars
                if (
                    self._read_value(calendar, "calendarIdentifier") in set(calendar_ids)
                    or self._read_value(calendar, "title") in set(calendar_ids)
                )
            ]

        predicate = self._call_selector(
            self.event_store,
            ["predicateForEventsWithStartDate_endDate_calendars_"],
            start_nsdate,
            end_nsdate,
            selected_calendars,
        )
        native_events = self._call_selector(
            self.event_store,
            ["eventsMatchingPredicate_"],
            predicate,
        ) or []
        rows: list[dict[str, Any]] = []
        for event in native_events:
            serialized = self._serialize_event(event)
            if serialized is not None:
                rows.append(serialized)
        return rows

    def read_events(
        self,
        start_date: datetime,
        end_date: datetime,
        calendar_ids: Optional[list[str]] = None,
    ) -> list[CalendarEvent]:
        """
        Read calendar events within a date range.

        Args:
            start_date: Start date for the query.
            end_date: End date for the query.
            calendar_ids: Optional list of calendar identifiers to filter.

        Returns:
            List of CalendarEvent objects.
        """
        if not self.is_available():
            return []

        rows = self._execute_events_query(start_date, end_date, calendar_ids)
        logger.info(
            "Calendar events query completed",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            requested_calendar_count=len(calendar_ids or []),
            row_count=len(rows),
        )
        events: list[CalendarEvent] = []
        for row in rows:
            start_time = row.get("start_time")
            end_time = row.get("end_time")
            if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
                continue
            participants = [
                Participant(
                    name=str(participant.get("name", "Unknown")),
                    email=participant.get("email"),
                    status=str(participant.get("status", "pending")),
                )
                for participant in row.get("participants", [])
            ]
            events.append(
                CalendarEvent(
                    event_id=str(row.get("event_id", "")),
                    title=str(row.get("title", "Untitled Event")),
                    start_time=start_time,
                    end_time=end_time,
                    is_all_day=bool(row.get("is_all_day", False)),
                    location=row.get("location"),
                    notes=row.get("notes"),
                    calendar_name=str(row.get("calendar_name", "Calendar")),
                    calendar_color=str(row.get("calendar_color", "")),
                    participants=participants,
                    is_recurring=bool(row.get("is_recurring", False)),
                    recurrence_rule=row.get("recurrence_rule"),
                    url=row.get("url"),
                )
            )
        return events
