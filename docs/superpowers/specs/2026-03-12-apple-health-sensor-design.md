# Apple Health Sensor Design

## Summary

Add a new timeline sensor plugin (`apple-health`) that reads health data from Apple HealthKit and ingests it into Magi's personal knowledge timeline. The sensor supports multiple health data types with configurable sync strategies and渐进式 authorization flow.

## Goals

- Enable users to sync their Apple Health data into Magi's timeline
- Support multiple health data types with appropriate aggregation strategies
- Provide渐进式 authorization per data type
- Work seamlessly on macOS with graceful degradation on other platforms

## Non-Goals

- Real-time health monitoring (polling-based sync only)
- Writing data back to HealthKit
- Medical diagnosis or health recommendations
- iOS native app support (desktop focus first)

## Platform Support

| Platform | Support Level |
|----------|---------------|
| macOS | Full support (requires iCloud Health sync from iPhone) |
| iOS | Architecture ready, not priority for v1 |
| Windows | Plugin disabled, no errors |
| Linux | Plugin disabled, no errors |

The plugin declares `platforms = ["macos", "ios"]` in manifest. Plugin manager should skip loading on unsupported platforms.

## Architecture

### Plugin Structure

```
plugins/apple-health/
├── plugin.toml           # Plugin manifest with platform declaration
├── plugin.py             # Plugin entry point + settings fields
├── sensor.py             # AppleHealthTimelineSensor implementation
├── reader.py             # HealthKitReader (pyobjc bridge)
├── types.py              # HealthDataType definitions + aggregation config
├── normalizers.py        # Data normalization functions
├── exceptions.py         # Custom exceptions
└── __init__.py
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `plugin.py` | Register sensor, define settings fields, handle platform detection |
| `sensor.py` | Implement TimelineSensorBase, coordinate data collection |
| `reader.py` | Wrap HealthKit framework via pyobjc, handle authorization |
| `types.py` | Define supported health data types and their configurations |
| `normalizers.py` | Convert raw health data to TimelineEvent objects |
| `exceptions.py` | Define domain-specific exceptions |

## Data Model

### HealthDataType Configuration

```python
@dataclass
class HealthDataType:
    key: str                    # Internal identifier (e.g., "steps")
    hk_type: str               # HealthKit type identifier
    display_name: str          # User-facing name (localized via i18n)
    description: str           # User-facing description
    unit: str                  # Display unit
    aggregation: str           # "daily" | "sample" | "session"
    hk_class: str              # "HKQuantityType" | "HKCategoryType" | "HKWorkoutType"
    edge_types: list[str]      # Allowed relation edges
```

### Supported Data Types

| Type | HK Identifier | Aggregation | Description |
|------|---------------|-------------|-------------|
| steps | HKQuantityTypeIdentifierStepCount | daily | Daily step count |
| distance | HKQuantityTypeIdentifierDistanceWalkingRunning | daily | Daily walking/running distance |
| flights | HKQuantityTypeIdentifierFlightsClimbed | daily | Daily flights climbed |
| heart_rate | HKQuantityTypeIdentifierHeartRate | sample | Individual heart rate measurements |
| sleep | HKCategoryTypeIdentifierSleepAnalysis | session | Sleep sessions |
| active_energy | HKQuantityTypeIdentifierActiveEnergyBurned | daily | Daily active energy |
| workout | HKWorkoutTypeIdentifier | session | Workout sessions |

### Aggregation Strategies

| Strategy | Use Case | Output |
|----------|----------|--------|
| `daily` | Cumulative metrics (steps, distance) | One event per day |
| `sample` | Point-in-time measurements (heart rate) | One event per sample |
| `session` | Time-bounded activities (sleep, workout) | One event per session |

### TimelineEvent Schema

Each health data item is normalized into a TimelineEvent with:

- `event_id`: `health_{data_type}_{date_or_timestamp}`
- `source_type`: `apple_health`
- `occurred_at`: Timestamp of the event
- `title`: Localized summary (e.g., "今日步数 8,234")
- `summary`: Detailed description
- `content_blocks`: Structured content
- `tags`: `["health", data_type, ...]`
- `provenance`: Full metadata including HK identifiers

## Authorization Flow

```
User enables sensor
       │
       ▼
┌─────────────────────────┐
│  Show data type toggles │
│  + iCloud sync hint     │
└─────────────────────────┘
       │
       ▼ User toggles a type ON
┌─────────────────────────┐
│  Request authorization  │
│  for that type only     │
│  (system dialog)        │
└─────────────────────────┘
       │
       ▼
┌─────────────────────────┐
│  Show authorization     │
│  status for each type   │
└─────────────────────────┘
```

### Authorization States

| State | Meaning | UI Action |
|-------|---------|-----------|
| `not_determined` | User hasn't been asked | Show enable toggle |
| `sharing_denied` | User denied | Show "denied" status, link to System Settings |
| `sharing_authorized` | User approved | Show "authorized", enable sync |
| `unavailable` | HealthKit not available | Disable plugin |

## Implementation Details

### pyobjc Integration

```python
# Lazy import to avoid errors on non-macOS platforms
def _import_frameworks(self):
    from HealthKit import HKHealthStore, HKQuantityType, HKCategoryType, HKWorkoutType
    from Foundation import NSDate, NSPredicate, NSSortDescriptor
    # ...
```

Key HealthKit API usage:

1. **Check availability**: `HKHealthStore.isHealthDataAvailable()`
2. **Request authorization**: `requestAuthorizationToShareTypes_readTypes_completion_`
3. **Query data**: `HKStatisticsQuery` (daily) or `HKSampleQuery` (samples/sessions)

### Platform Detection

```python
# In plugin.py
def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
    if sys.platform != "darwin":
        logger.info("Apple Health plugin disabled: not running on macOS/iOS")
        return []

    try:
        from apple_health.reader import HealthKitReader
        reader = HealthKitReader()
        if not reader.is_available():
            return []
        # ... proceed with registration
    except ImportError:
        return []
```

### Error Handling

| Error | When | Handling |
|-------|------|----------|
| `PlatformNotSupportedError` | Non-macOS platform | Return empty sensor list |
| `HealthKitNotAvailableError` | HealthKit framework missing | Disable plugin, log warning |
| `AuthorizationDeniedError` | User denied authorization | Skip that data type, show status |
| `HealthKitQueryError` | Query failed | Log error, skip batch, retry next sync |

## Settings

### Plugin Settings Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sensors.apple_health.types.{type}` | switch | varies | Enable/disable each data type |
| `sensors.apple_health.sync_interval_hours` | select | 1 | Sync frequency |
| `sensors.apple_health.lookback_days` | number | 7 | Initial sync lookback |
| `sensors.apple_health.enabled` | switch | false | Master enable toggle |

### Default Enabled Types

- `steps`: Enabled by default
- `sleep`: Enabled by default
- All others: Disabled by default (user opt-in)

## i18n

All user-facing strings use i18n keys:

```json
// zh-CN
{
  "timeline.sources.apple_health.title": "Apple 健康",
  "timeline.sources.apple_health.hints.icloud_sync": "请确保您的 iPhone 已开启 iCloud 健康数据同步..."
}

// en
{
  "timeline.sources.apple_health.title": "Apple Health",
  "timeline.sources.apple_health.hints.icloud_sync": "Make sure iCloud Health sync is enabled..."
}
```

## Testing Strategy

### Unit Tests

- `test_types.py`: HealthDataType configuration validation
- `test_normalizers.py`: Normalize functions for each data type
- `test_sensor.py`: Sensor instantiation, settings parsing

### Integration Tests (macOS only)

- `test_reader.py`: HealthKit availability check, authorization status
- `test_sensor_sync.py`: End-to-end sync with mock HealthKit data

### Platform Tests

- Verify plugin returns empty on non-macOS platforms
- Verify graceful import error handling

## Dependencies

### Runtime (macOS only)

```
pyobjc-framework-HealthKit>=10.0
pyobjc-framework-Foundation>=10.0
```

### Build-time

Dependencies are added to `requirements.txt` but PyInstaller will only include them on macOS builds. Windows/Linux builds naturally exclude them.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| pyobjc import fails on some macOS versions | Lazy import with try/except, clear error message |
| User doesn't have iCloud sync enabled | Show prominent hint in settings UI |
| HealthKit API changes | Pin pyobjc version, test on multiple macOS versions |
| Large data volumes (heart rate samples) | Add limit parameter, default to reasonable batch size |
| Authorization revocation handling | Check status before each sync, update UI accordingly |

## Future Considerations

- iOS native support via Tauri mobile
- More data types (blood oxygen, ECG, etc.)
- Health trend analysis and insights
- Export health data from timeline

## Acceptance Criteria

- [ ] Plugin loads successfully on macOS with HealthKit available
- [ ] Plugin gracefully disables on Windows/Linux without errors
- [ ] User can selectively enable/disable each health data type
- [ ] Authorization is requested per-type when enabled
- [ ] Daily aggregated data (steps, etc.) creates one event per day
- [ ] Session data (sleep, workout) creates one event per session
- [ ] Sample data (heart rate) creates one event per sample
- [ ] All i18n keys are present in zh-CN and en locales
- [ ] Unit tests pass on all platforms
- [ ] Integration tests pass on macOS
