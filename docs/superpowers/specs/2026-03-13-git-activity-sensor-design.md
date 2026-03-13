# Git Activity Sensor Design

## Summary

Add a new timeline sensor (`git_activity`) that reads git reflog entries from configured repositories and ingests them into Magi's personal knowledge timeline. The plugin supports all reflog activity types (commit, checkout, merge, rebase, reset, etc.) across macOS, Linux, and Windows.

## Goals
- Enable users to sync their git activity history into Magi's timeline
- Support multiple configured repositories
- Capture all reflog activity types (commit, checkout, merge, rebase, reset, clone, pull, etc.)
- Handle sensitive commit messages with filtering/redaction
- Cross-platform support (macOS, Linux, Windows)

## Non-Goals
- Real-time git hook integration
- Automatic repository discovery
- Detailed diff content capture
- Remote repository sync status

## Platform Support

| Platform | Support Level |
|----------|---------------|
| macOS | Full support |
| Linux | Full support |
| Windows | Full support |

## Architecture

### Plugin Structure
```
plugins/git_activity/
├── plugin.toml           # Plugin manifest
├── plugin.py             # Plugin entry point + settings fields
├── sensor.py             # GitActivitySensor implementation
├── reader.py             # Reflog file reader
├── normalizers.py        # Data normalization functions
├── filters.py            # Sensitive message filter (reuses terminal_history logic)
├── types.py              # Data type definitions
└── __init__.py           # Package init
```

### Data Model

#### GitActivity
```python
@dataclass
class GitActivity:
    repo_path: str              # Repository path
    activity_type: str          # commit/checkout/merge/rebase/reset/clone/pull
    old_sha: str                # Previous commit SHA
    new_sha: str                # New commit SHA
    message: str                # Operation message
    author: str                 # Author name and email
    timestamp: datetime         # Operation timestamp
    raw_line: str               # Original reflog line
```

#### TimelineEvent Mapping
| GitActivity Field | TimelineEvent Field |
|-------------------|---------------------|
| message | title |
| timestamp | occurred_at |
| activity_type | tags |
| repo_path | provenance |

### Reflog Format

**`.git/logs/HEAD` format**:
```
<old_sha> <new_sha> <author> <timestamp> <tz>\t<action>: <message>
```

**Example**:
```
abc123def def456abc John <john@example.com> 1741887000 +0800	commit: Add feature
```

**Supported Activity Types**:
| Type | Description |
|------|-------------|
| `commit` | Commit changes |
| `checkout` | Switch branches |
| `merge` | Merge branches |
| `rebase` | Rebase commits |
| `reset` | Reset HEAD |
| `clone` | Clone repository |
| `pull` | Pull from remote |

### Settings Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sensors.git_activity.enabled` | switch | false | Master enable toggle |
| `sensors.git_activity.repos` | tags | [] | Repository paths to monitor |
| `sensors.git_activity.sync_interval_minutes` | number | 30 | Polling interval |
| `sensors.git_activity.initial_sync_policy` | select | lookback_days | First sync strategy |
| `sensors.git_activity.initial_sync_lookback_days` | number | 30 | Days to look back on first sync |
| `sensors.git_activity.sensitive_mode` | select | redact | Sensitive message handling |
| `sensors.git_activity.sensitive_keywords` | tags | built-in | Additional sensitive keywords |
| `sensors.git_activity.default_retention_mode` | select | analyze_only | Retention policy |

### Sync Strategy
- **Initial sync**: Configurable (full / lookback N days / from now)
- **Incremental sync**: Polling every N minutes
- **Multi-repo support**: Iterate through configured repos, track each independently

### Sensitive Message Handling
- Reuses filter logic from `terminal_history` plugin
- Built-in blacklist: password, secret, api_key, token, etc.
- Two modes: `block` (skip) or `redact` (mask sensitive parts)

## Dependencies
None (pure Python, uses standard library only)

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Missing reflog files | Graceful skip with warning |
| Large reflog files | Limit per-sync entries |
| Invalid repo paths | Validate on config, skip invalid |
| Sensitive commit messages | Filter/redact based on settings |

## Future Considerations
- Automatic repository discovery
- Real-time git hooks integration
- Branch visualization
- Author statistics

## Acceptance Criteria
- [x] Plugin loads successfully on all platforms
- [x] Multiple repositories can be configured
- [x] Reflog entries are parsed correctly
- [x] All activity types are captured (commit, checkout, merge, etc.)
- [x] Sensitive messages are filtered or redacted
- [x] Initial sync respects configured policy
- [x] All i18n keys are present in zh-CN and en locales
- [x] Unit tests pass
