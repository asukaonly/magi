# Screen Time Sensor Design

## Summary

Add a new timeline sensor (`screen_time`) that reads Screen Time data from macOS and ingests them into Magi's personal knowledge timeline.
 The plugin supports full event information (title, time, location, calendar name, calendar color) with graceful degradation on other platforms.

## Goals
- Enable users to sync their Screen Time data into Magi's timeline
- Support total usage duration and per-application usage details
- Handle initial sync with 30-day lookback
- All data permanently retained

## Non-Goals
- Windows/Linux support
- Real-time notifications
- Cross-application comparison
- Detailed breakdown by app

## Platform Support

| Platform | Support Level |
|----------|---------------|
| macOS | Full support (SQLite database) |
| iOS | Architecture ready, not priority for v1 |
| Windows | Plugin disabled, no errors |
| Linux | Plugin disabled, no errors |

## Architecture
### Plugin Structure
```
plugins/screen_time/
├── plugin.toml           # Plugin manifest
├── plugin.py             # Plugin entry point + settings fields
├── sensor.py             # ScreenTimeTimelineSensor implementation
├── reader.py             # SQLite database reader
├── normalizers.py        # Data normalization functions
├── exceptions.py         # Custom exceptions
└── __init__.py           # Package init
```

### Data Model
#### DailyScreenTime
```python
@dataclass
class DailyScreenTime:
    date: date                          # 日期
    total_duration: int                 # 总使用时长（秒）
    app_usages: list[AppUsage]       # 应用使用列表
```

#### AppUsage
```python
@dataclass
class AppUsage:
    bundle_id: str                    # 应用 ID
    app_name: str                  # 应用名称
    usage_seconds: int              # 使用时长（秒）
    category: str | None           # 分类（社交网络、生产力、娱乐等)
```

#### TimelineEvent Mapping
| ScreenTime Field | TimelineEvent Field |
|----------------|---------------------|
| date | occurred_at |
| title | summary |
| total_duration | content_blocks |
| app_usages | provenance |

### Settings Fields
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sensors.screen_time.enabled` | switch | false | Master enable toggle |
| `sensors.screen_time.sync_interval_hours` | select | 1 | Sync frequency |
| `sensors.screen_time.lookback_days` | number | 30 | Initial sync lookback |
| `sensors.screen_time.default_retention_mode` | select | analyze_only | Retention policy |

### Sync Strategy
- Initial sync: 30 days history
- Incremental sync: 每小时
- Data permanently retained

## Database Location
`~/Library/Application Support/com.apple.screentime/ScreenTime.db`

## Dependencies
None (pure Python with SQLite3)

## Risks and Mitigations
| Risk | Mitigation |
|------|------------|
| EventKit import fails on some macOS versions | Lazy import with try/except |
| Large event volumes | Pagination and date range limits |
| Private calendar data | Clear privacy documentation, local-only processing |

## Future Considerations
- Screen Time API integration (实时)
- Cross-application comparison
- Notification-based sync

- More detailed breakdown by app category

## Acceptance Criteria
- [ ] Plugin loads successfully on macOS with SQLite database accessible
- [ ] Plugin gracefully disables on Windows/Linux without errors
- [ ] User can view their Screen Time data
- [ ] Total usage duration and per-application usage details are captured
- [ ] All i18n keys are present in zh-CN and en locales
- [ ] Initial sync covers the past 30 days
- [ ] Unit tests pass on all platforms
