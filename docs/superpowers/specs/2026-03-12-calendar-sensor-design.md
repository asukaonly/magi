# Calendar Sensor Design

## Summary

Add a new timeline sensor plugin (`calendar`) that reads calendar events from macOS Calendar via EventKit and ingests them into Magi's personal knowledge timeline. The sensor supports full event information (title, time, location, participants, notes, calendar name) with recurring event expansion.

## Goals

- Enable users to sync their macOS Calendar events into Magi's timeline
- Support full event information including location, participants, and notes
- Handle recurring events by expanding them within a configurable time range
- Work seamlessly on macOS with graceful degradation on other platforms

## Non-Goals

- Google Calendar support (Phase 2)
- Calendar write operations (only read)
- Real-time event notifications
- Windows/Linux support

## Platform Support

| Platform | Support Level |
|----------|---------------|
| macOS | Full support (EventKit) |
| iOS | Architecture ready, not priority for v1 |
| Windows | Plugin disabled, no errors |
| Linux | Plugin disabled, no errors |

The plugin declares `platforms = ["macos", "ios"]` in manifest.

## Architecture

### Plugin Structure

```
plugins/calendar/
├── plugin.toml           # Plugin manifest with platform declaration
├── plugin.py             # Plugin entry point + settings fields
├── sensor.py             # CalendarTimelineSensor implementation
├── reader.py             # EventKitReader (pyobjc bridge)
├── normalizers.py        # Event normalization functions
├── exceptions.py         # Custom exceptions
└── __init__.py           # Package init
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `plugin.py` | Register sensor, define settings fields, handle platform detection |
| `sensor.py` | Implement TimelineSensorBase, coordinate data collection |
| `reader.py` | Wrap EventKit framework via pyobjc, handle authorization |
| `normalizers.py` | Convert raw calendar events to TimelineEvent objects |
| `exceptions.py` | Define domain-specific exceptions |

## Data Model

### CalendarEvent Schema

Each calendar event contains:

```python
@dataclass
class CalendarEvent:
    event_id: str              # Unique identifier (EKEvent.eventIdentifier)
    title: str                 # Event title
    start_time: datetime       # Start datetime
    end_time: datetime         # End datetime
    is_all_day: bool           # All-day event flag
    location: str | None       # Location string
    notes: str | None          # Event notes/description
    calendar_name: str         # Source calendar name
    calendar_color: str        # Calendar color (hex)
    participants: list[dict]   # List of participants
    is_recurring: bool         # Is this a recurring event
    recurrence_rule: str | None # Recurrence rule (if recurring)
    url: str | None            # Event URL (if any)
```

### TimelineEvent Mapping

| Calendar Field | TimelineEvent Field |
|----------------|---------------------|
| title | title |
| "{title} - {location}" | summary (if location) |
| start_time | occurred_at |
| All fields | provenance |
| ["calendar", "event"] | tags |
| Content blocks | content_blocks (time, location, participants, notes) |

### Participant Schema

```python
@dataclass
class Participant:
    name: str           # Display name
    email: str | None   # Email address
    status: str         # "accepted", "declined", "tentative", "pending"
```

## Sync Strategy

### Initial Sync

- Sync events from the past 30 days
- Expand recurring events up to 30 days into the future
- All synced data is permanently retained (no automatic deletion)

### Incremental Sync

- Check for new/modified/deleted events since last sync
- Use EKEventStore's eventChangedNotifications for change detection
- Poll interval: configurable, default 30 minutes

### Recurring Event Handling

```
Recurring Event Template (stored once)
       │
       ▼ Expand to future 30 days
┌─────────────────────────────────────┐
│  Week 1: Monday站会                 │
│  Week 2: Monday站会                 │
│  Week 3: Monday站会                 │
│  Week 4: Monday站会                 │
└─────────────────────────────────────┘
```

Each expanded instance gets a unique ID: `{original_id}_{occurrence_date}`

## EventKit Integration

### Authorization

```python
# Request calendar access
EKEventStore.requestAccessToEntityType_completion_(
    EKEntityTypeEvent,
    lambda granted, error: ...
)
```

### Reading Events

```python
# Create predicate for date range
predicate = EKEventStore.predicateForEventsWithStartDate_endDate_calendars_(
    start_date,
    end_date,
    None  # All calendars
)

# Fetch events
events = EKEventStore.eventsMatchingPredicate_(predicate)
```

### Key EventKit Types

| EKType | Purpose |
|--------|---------|
| `EKEventStore` | Main interface to calendar database |
| `EKEvent` | Individual calendar event |
| `EKCalendar` | Calendar container |
| `EKParticipant` | Meeting participant |
| `EKRecurrenceRule` | Recurrence pattern |

## Settings

### Plugin Settings Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sensors.calendar.enabled` | switch | false | Master enable toggle |
| `sensors.calendar.sync_interval_minutes` | select | 30 | Sync frequency |
| `sensors.calendar.lookback_days` | number | 30 | Initial sync lookback |
| `sensors.calendar.recurring_expansion_days` | number | 30 | Days to expand recurring events |
| `sensors.calendar.default_retention_mode` | select | analyze_only | Retention policy |

### No Calendar Filtering

All calendars are synced by default. No per-calendar toggle in v1.

## Error Handling

| Error | When | Handling |
|-------|------|----------|
| `PlatformNotSupportedError` | Non-macOS platform | Return empty sensor list |
| `CalendarNotAvailableError` | EventKit not available | Disable plugin, log warning |
| `AuthorizationDeniedError` | User denied calendar access | Skip sync, show status |
| `EventKitQueryError` | Query failed | Log error, retry next sync |

## i18n

All user-facing strings use i18n keys:

```json
// zh-CN
{
  "timeline.sources.calendar": "日历",
  "timeline.sources.calendar.description": "从 macOS 日历同步您的日程安排",
  "calendar.hints.authorization_required": "启用此传感器需要日历访问授权"
}

// en
{
  "timeline.sources.calendar": "Calendar",
  "timeline.sources.calendar.description": "Sync your schedule from macOS Calendar",
  "calendar.hints.authorization_required": "Calendar access authorization is required to enable this sensor"
}
```

## Dependencies

### Runtime (macOS only)

```
pyobjc-framework-EventKit>=10.0
pyobjc-framework-Foundation>=10.0
```

These are already included via the apple_health plugin dependencies.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| EventKit import fails on some macOS versions | Lazy import with try/except |
| Large event volumes | Pagination and date range limits |
| Private calendar data | Clear privacy documentation, local-only processing |
| Recurring event edge cases | Handle exceptions gracefully, log warnings |

## Future Considerations

- Google Calendar support
- Calendar write operations (create/update events)
- Real-time event notifications
- Calendar-based reminders and suggestions

## Acceptance Criteria

- [ ] Plugin loads successfully on macOS with EventKit available
- [ ] Plugin gracefully disables on Windows/Linux without errors
- [ ] User can authorize calendar access
- [ ] Events from all calendars are synced
- [ ] Full event information (title, time, location, participants, notes) is captured
- [ ] Recurring events are expanded for the configured time range
- [ ] Initial sync covers the past 30 days
- [ ] All i18n keys are present in zh-CN and en locales
- [ ] Unit tests pass on all platforms
