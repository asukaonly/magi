# Terminal History Sensor Design

## Summary

Add a new timeline sensor (`terminal_history`) that reads shell command history from zsh/bash and ingests them into Magi's personal knowledge timeline. The plugin supports automatic shell detection, sensitive command filtering/redaction, and session-based deduplication.

## Goals
- Enable users to sync their terminal command history into Magi's timeline
- Support zsh and bash shells with automatic detection via $SHELL
- Handle initial sync with configurable lookback period
- Protect sensitive commands via filtering or redaction

## Non-Goals
- Working directory tracking (future consideration)
- Real-time command capture (polling-based only)
- Windows/Linux support
- Shell session reconstruction

## Platform Support

| Platform | Support Level |
|----------|---------------|
| macOS | Full support (zsh, bash) |
| Linux | Architecture ready, not priority for v1 |
| Windows | Not supported |

## Architecture

### Plugin Structure
```
plugins/terminal_history/
├── plugin.toml           # Plugin manifest
├── plugin.py             # Plugin entry point + settings fields
├── sensor.py             # TerminalHistorySensor implementation
├── reader.py             # History file reader (zsh/bash)
├── normalizers.py        # Data normalization functions
├── filters.py            # Sensitive command filter/redact
├── types.py              # Data type definitions
└── __init__.py           # Package init
```

### Data Model

#### TerminalCommand
```python
@dataclass
class TerminalCommand:
    command: str              # Executed command
    executed_at: datetime     # Execution timestamp
    shell: str                # Shell type: zsh / bash
    history_line: int         # Line number in history file
```

#### TimelineEvent Mapping
| TerminalCommand Field | TimelineEvent Field |
|----------------------|---------------------|
| command | title |
| executed_at | occurred_at |
| shell | tags |
| - | summary (command + time) |

### History File Reading

| Shell | History File | Timestamp Source |
|-------|--------------|------------------|
| zsh | `~/.zsh_history` | Extended history format `: timestamp:0;command` |
| bash | `~/.bash_history` | No timestamp, use file mtime as approximation |

### Sensitive Command Handling

**Built-in Blacklist Keywords**:
```
password, passwd, secret, token, api_key, apikey,
access_key, private_key, credential, auth,
mysql_pass, db_pass, aws_secret, ssh_key, etc.
```

**Processing Modes**:
| Mode | Behavior |
|------|----------|
| `block` | Skip completely, don't record |
| `redact` | Redact sensitive parts, e.g., `export API_KEY=***` |

### Settings Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sensors.terminal_history.enabled` | switch | false | Master enable toggle |
| `sensors.terminal_history.sync_interval_minutes` | number | 15 | Polling interval |
| `sensors.terminal_history.initial_sync_policy` | select | lookback_days | First sync strategy |
| `sensors.terminal_history.initial_sync_lookback_days` | number | 7 | Days to look back on first sync |
| `sensors.terminal_history.sensitive_mode` | select | redact | Sensitive command handling |
| `sensors.terminal_history.sensitive_keywords` | tags | built-in | Additional sensitive keywords |
| `sensors.terminal_history.dedup_window_seconds` | number | 60 | Deduplication time window |
| `sensors.terminal_history.default_retention_mode` | select | analyze_only | Retention policy |

### Sync Strategy
- **Initial sync**: Configurable (full / lookback N days / from now)
- **Incremental sync**: Polling every N minutes
- **Deduplication**: Same command within dedup window (default 60s) is merged

### Activation Flow (like chrome-history)
1. User enables the sensor
2. Prompt for initial sync scope:
   - "Sync full history"
   - "Sync recent 7 days" (default)
   - "Only new commands from now"
3. Store `initial_sync_configured` flag

## Dependencies
None (pure Python, uses standard library only)

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Large history files | Pagination and limit per sync |
| Missing timestamps in bash | Use file mtime as fallback |
| Sensitive data exposure | Built-in filter + user configurable blacklist |
| History file format variations | Graceful degradation, skip unparseable lines |

## Future Considerations
- Working directory inference via cd command tracking
- Real-time capture via shell hooks
- Cross-platform support (Linux)
- Command frequency analytics

## Acceptance Criteria
- [x] Plugin loads successfully on macOS
- [x] Plugin gracefully disables on unsupported platforms
- [x] zsh history with extended format is parsed correctly
- [x] bash history is parsed (with mtime approximation)
- [x] Sensitive commands are filtered or redacted based on settings
- [x] Session-based deduplication works within configured window
- [x] Initial sync respects configured policy (full/lookback/from_now)
- [x] All i18n keys are present in zh-CN and en locales
- [x] Unit tests pass
