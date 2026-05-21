# Plugin I18n Refactor: Move Translations Out of Host app.json

**Date**: 2026-05-21  
**Status**: Design Phase (Task C1)  
**Related**: Task #34 (investigate), Task #35 (execute)

## Executive Summary

This document designs a refactor to eliminate plugin-specific translation entries from the magi frontend's host `app.json` files. After completion, all plugin translations will be self-contained in each plugin's own `i18n/<lang>.json` file, making plugins fully portable and reducing host coupling.

**Current state**: 11 plugins have 200+ translation entries scattered across host i18n.  
**Target state**: 0 plugin entries in host i18n; all 11 plugins self-describing.  
**Effort**: 3 phases, ~40 backend/frontend file changes, ~8 hours end-to-end.

---

## 1. Current State: Source Files & Paths

### 1.1 Frontend Host I18n (Plugin Entries)

**Location**: `/Users/asuka/code/magi/frontend/src/i18n/locales/{en,zh-CN}/app.json`

**Size**: ~59KB per language file

**Plugin entries (11 plugins)**:
```
settings.plugins.{plugin_id}:
  - name, description (fallback for sensor display name)
  - fields.{field_key}.{label, description}
  - options.{field_key}.{value} (select option labels)
  - sections.{section_key} (section titles: "general", "sync", "storage", etc)
  - section_notes.{section_key}
  - ui_blocks.{block_id}.{title, description}
  - actions.{action_id}.{label, description, button_label}
  - activation.{title, description, confirm_label, cancel_label}

timeline.sources.{source_name}:
  - Plain string (e.g. "Chrome history" for chrome_history)

settings.timeline.sourceDesc.{source_name}:
  - Plain string description

settings.pluginSections.{section_name}:
  - Fallback section titles (e.g. "general", "storage")
```

**Plugins with entries**:
- calendar, chrome-history, core-tools, git-activity, netease-music
- photo-library, screen-time, screenshot_timeline, system-media
- telegram (legacy?), terminal-history

**Example chrome-history entry**:
```json
{
  "settings.plugins.chrome-history": {
    "name": "Chrome History",
    "description": "Local Google Chrome browsing history ingestion...",
    "fields": {
      "sensors.chrome_history.profile": {
        "label": "Profile",
        "description": "Chrome profile directory..."
      },
      "sensors.chrome_history.sync_mode": { ... }
    },
    "options": {
      "sync_mode": {
        "manual": "Manual",
        "interval": "Interval"
      },
      "initial_sync_policy": {
        "full": "Sync full history",
        "lookback_days": "Sync recent days",
        "from_now": "Only new records from now on"
      }
    },
    "sections": {
      "general": "General",
      "sync": "Sync",
      "storage": "Storage",
      "activation": "Activation"
    },
    "activation": {
      "title": "Enable Chrome History",
      "description": "Chrome history contains sensitive...",
      "confirm_label": "Enable source",
      "cancel_label": "Not now"
    }
  }
}
```

### 1.2 Backend API Serialization

**Location**: `/Users/asuka/code/magi/api/routers/plugins_common.py` (lines 54–154)

**Key functions**:
- `_get_plugin_i18n()` (line 54): Loads plugin's i18n helper
- `_serialize_manifest()` (line 65): Translates plugin name/description via i18n
- `_serialize_field()` (line 87): Translates field labels, descriptions, and option labels
- `_serialize_contribution()` (line 110): Translates contribution display_name and description
- `_serialize_settings_action()` (line 144): Translates action label, description, button_label

**Current translation lookup**:
```python
# Example from _serialize_field() line 91–95
label_key = f"fields.{contribution_id}.{field.key}.label"
desc_key = f"fields.{contribution_id}.{field.key}.description"
field_dict["label"] = i18n.t(label_key, fallback=field.label)
field_dict["description"] = i18n.t(desc_key, fallback=field.description)
```

**Limitation**: Already uses plugin i18n (via PluginI18n), but fields have no fallback to host i18n—only SDK fallback.

### 1.3 Backend Sensor Endpoints

**Location**: `/Users/asuka/code/magi/api/routers/sensors.py` (lines 88–220)

**Endpoint**: `GET /sensors/status`

**What's returned** (line 141–220):
```python
{
    "source_name": source_name,
    "plugin_id": item.plugin_id,
    "contribution_id": item.contribution_id,
    "display_name": item.display_name,  # ← Raw from manifest
    "description": item.description,     # ← Raw from manifest
    "fields": [...],                     # ← Raw from ExtensionFieldSpec
    "current_settings": {...},
    "enabled": bool,
    # ... more fields
}
```

**Issue**: `display_name`, `description`, and field labels are **not pre-translated**. Frontend must use host i18n fallback.

### 1.4 Plugin I18n Files (Local)

**Location**: `~/.magi/plugins/{plugin_id}/i18n/{lang}.json`  
**Example**: `/Users/asuka/code/magi/target/release/sidecar-dist/_internal/plugins/chrome-history/i18n/en.json`

**Current shape** (chrome-history example):
```json
{
  "chrome_history": {
    "name": "Chrome History",
    "description": "Local Google Chrome browsing history ingestion for the timeline",
    "activation": {
      "title": "Enable Chrome History",
      "description": "Chrome history contains sensitive local data...",
      "confirm_label": "Enable source",
      "cancel_label": "Not now"
    },
    "initial_sync_policy": {
      "full": "Sync full history",
      "lookback_days": "Sync recent days",
      "from_now": "Only new records from now on"
    }
  },
  "summary": {
    "single_visit": "{title}",
    "multiple_visits": "{title} ({count} visits)"
  }
}
```

**Gap**: Only covers plugin name, description, activation text, and activity summary. Missing:
- Field labels and descriptions (stored in host i18n)
- Field option labels (stored in host i18n)
- Section titles (stored in host i18n)
- Settings actions (stored in host i18n)

### 1.5 Frontend Resolution Paths

#### Timeline Source Display Names
**File**: `/Users/asuka/code/magi/frontend/src/utils/timeline-source-copy.ts` (lines 26–42)

**Lookup order**:
1. `settings.timeline.sources.{source_name}` (host i18n)
2. `settings.tabs.{source_name}` (host i18n, fallback)
3. If source_name == plugin_id: `settings.plugins.{plugin_id}.name` (host i18n)
4. `source.display_name` from API response
5. `source.source_name` raw value

**Current**: Relies entirely on host i18n; never reads from plugin i18n.

#### Plugin Settings Fields
**File**: `/Users/asuka/code/magi/frontend/src/components/settings/PluginSettingsFields.tsx` (lines 17–108)

**Lookup order** (lines 100–108):
1. `settings.plugins.{pluginId}.fields.{candidate}.{property}` (host i18n)
2. Fallback to `field.{property}` from API response

**Lookup order for section titles** (lines 42–54):
1. `settings.plugins.{pluginId}.sections.{section}` (host i18n)
2. `settings.pluginSections.{section}` (host i18n generic)
3. Plain text: `section.replace(/_/g, ' ')`

#### Plugin Settings Actions
**File**: `/Users/asuka/code/magi/frontend/src/components/settings/PluginSettingsActions.tsx` (lines 32–56)

**Lookup order** (line 39):
1. `settings.plugins.{pluginId}.actions.{action_id}.{key}` (host i18n)
2. Fallback to `action[key]` from API response

#### Plugin Custom UI Blocks (Permission status panel, etc)
**File**: `/Users/asuka/code/magi/frontend/src/components/settings/PluginSettingsCustomBlocks.tsx` (lines 21–42)

**Lookup order**:
1. `settings.plugins.{pluginId}.ui_blocks.{block_id}.title` (host i18n)
2. `settings.plugins.{pluginId}.ui_blocks.{block_id}.description` (host i18n)
3. Fallback to `block.title` / `block.description` from API response

#### Activation Flow Text
**File**: `/Users/asuka/code/magi/frontend/src/components/settings/TimelineSourcesSection.tsx` (lines 199–202)

**Lookup order**:
1. `settings.plugins.{pluginId}.activation.{key}` (host i18n)
2. Fallback to `flow[key]` from API response

---

## 2. Target State: Clean Architecture

After refactor, the architecture will be:

```
┌─────────────────────────────────────┐
│  magi Frontend                      │
│  └─ i18n: app.json (NO plugin entries)
└──────────────┬──────────────────────┘
               │
               ├─ API: GET /sensors/status
               │  └─ Response includes TRANSLATED fields:
               │     - display_name_translated
               │     - description_translated
               │     - fields[].label_translated
               │     - fields[].description_translated
               │     - fields[].options[].label_translated
               │
               └─ API: GET /plugins/{id}/manifest
                  └─ Response includes ALL translations
                     (name, description, sections, actions, etc)

┌─────────────────────────────────────┐
│  magi Backend                       │
│  └─ Serializers enhance responses   │
│     with translated metadata from   │
│     plugin i18n (dual-rail during   │
│     transition)                     │
└──────────────┬──────────────────────┘
               │
               ├─ PluginI18n.t() lookups:
               │  - fields.{contribution_id}.{key}.label
               │  - fields.{contribution_id}.{key}.description
               │  - fields.{contribution_id}.{key}.options.{value}
               │  - sections.{section_key}
               │  - ui_blocks.{block_id}.title
               │  - actions.{action_id}.label
               │  (all new paths)
               │
               └─ plugins/{id}/i18n/{lang}.json
                  └─ Contains ALL translations

┌─────────────────────────────────────┐
│  Plugin I18n Schema (NEW)           │
│  ~/.magi/plugins/{id}/i18n/en.json  │
│                                     │
│  {                                  │
│    "{plugin_id}": {                 │
│      "name": "...",                 │
│      "description": "...",          │
│      "activation": { ... },         │
│      "sections": {                  │
│        "general": "General",        │
│        "sync": "Sync"               │
│      },                             │
│      "fields": {                    │
│        "{field_key}": {             │
│          "label": "...",            │
│          "description": "...",      │
│          "options": {               │
│            "{value}": "Label"       │
│          }                          │
│        }                            │
│      },                             │
│      "actions": {                   │
│        "{action_id}": {             │
│          "label": "...",            │
│          "description": "...",      │
│          "button_label": "..."      │
│        }                            │
│      },                             │
│      "ui_blocks": {                 │
│        "{block_id}": {              │
│          "title": "...",            │
│          "description": "..."       │
│        }                            │
│      }                              │
│    },                               │
│    "summary": { ... },              │
│    "activity_types": { ... }        │
│  }                                  │
└─────────────────────────────────────┘
```

**Key properties**:
- Plugin-centric: all plugin translations in plugin i18n
- Host-independent: adding new plugin needs zero host changes
- Backward compatible: during transition, both sources work
- API-first: backend pre-translates when possible, frontend falls back to host i18n

---

## 3. Refactor Approach

### 3.1 Backend Changes

#### Goal
Extend `PluginI18n` to support new lookup paths for fields, options, sections, actions, and UI blocks. Augment API responses with pre-translated values.

#### Changes Needed

**A. SDK PluginI18n (magi_plugin_sdk/i18n.py)**

Add support for nested lookups beyond dot-notation:

```python
# Current (works fine):
i18n.t("summary.played_track")

# New paths needed:
i18n.t("fields.sensors.chrome_history.profile.label")
i18n.t("fields.sensors.chrome_history.sync_mode.options.manual")
i18n.t("sections.sync")
i18n.t("actions.request_auth.label")
i18n.t("ui_blocks.permission_status.title")
```

**Status**: Already works (dot-notation supported). No SDK changes needed.

**B. Backend Serializers (plugins_common.py)**

Extend `_serialize_field()` to look up in plugin i18n:

```python
def _serialize_field(
    field: ExtensionFieldSpec, i18n: PluginI18n, contribution_id: str
) -> dict[str, Any]:
    """Serialize a field with translation."""
    # NEW: Try plugin i18n first, then fallback to existing logic
    label_key = f"fields.{contribution_id}.{field.key}.label"
    field_dict["label_translated"] = i18n.t(label_key, fallback=None)
    
    # ... existing logic unchanged ...
```

**New response shape**: Include both original (for fallback) and translated:
```python
{
    "key": "sensors.chrome_history.profile",
    "label": "Profile",               # from ExtensionFieldSpec
    "label_translated": "Profile",    # from plugin i18n (if exists)
    "description": "Chrome profile...",
    "description_translated": "Chrome profile...",  # from plugin i18n
    "options": [
        {
            "label": "Default",
            "label_translated": "Default",  # NEW
            "value": "Default"
        }
    ]
}
```

**Files changed**:
- `/Users/asuka/code/magi/backend/src/magi/api/routers/plugins_common.py` (±20 lines)

**C. Sensors Endpoint (sensors.py)**

Augment `/sensors/status` response to include translated fields:

```python
# Line 141–220: In the sources.append() dict

sources.append({
    "source_name": source_name,
    "display_name": item.display_name,  # existing
    "display_name_translated": i18n.t(f"{plugin_id}.name", fallback=None),  # NEW
    "description": item.description,    # existing
    "description_translated": i18n.t(f"{plugin_id}.description", fallback=None),  # NEW
    "fields": [
        _serialize_field_with_translation(field, i18n, contribution_id)
        for field in item.fields
    ],
    # ... rest unchanged ...
})
```

**Files changed**:
- `/Users/asuka/code/magi/backend/src/magi/api/routers/sensors.py` (±15 lines)

**D. TypeScript API Schemas (frontend)**

Add translated fields to response types:

```typescript
// plugins.ts
export interface ExtensionFieldSpec {
    key: string;
    label: string;
    label_translated?: string;  // NEW
    description: string;
    description_translated?: string;  // NEW
    // ...
}

// sensors.ts
export interface SensorSourceStatusItem {
    source_name: string;
    display_name: string;
    display_name_translated?: string;  // NEW
    description: string;
    description_translated?: string;  // NEW
    // ... rest unchanged ...
}
```

**Files changed**:
- `/Users/asuka/code/magi/frontend/src/api/modules/plugins.ts` (±10 lines)
- `/Users/asuka/code/magi/frontend/src/api/modules/sensors.ts` (±10 lines)

### 3.2 Frontend Changes

#### Goal
Update resolution paths to prefer API-provided translated values, fall back to host i18n, then fallback to raw values.

#### Changes Needed

**A. Timeline Source Display Names (timeline-source-copy.ts)**

```typescript
export const getTimelineSourceDisplayName = (
  t: TimelineTranslateFn,
  source: Pick<SensorSourceStatusItem, 
    'source_name' | 'plugin_id' | 'display_name' | 'display_name_translated'>
): string =>
  // NEW: Prefer API-translated value
  source.display_name_translated
  || resolveSourceTranslation(t, source.source_name)  // existing host i18n
  || (shouldUsePluginCopy(source) 
      ? resolveTranslation(t, `settings.plugins.${source.plugin_id}.name`) 
      : null)
  || source.display_name
  || source.source_name;
```

**Files changed**:
- `/Users/asuka/code/magi/frontend/src/utils/timeline-source-copy.ts` (±5 lines)

**B. Plugin Settings Fields (PluginSettingsFields.tsx)**

```typescript
const getTranslatedFieldValue = (
  field: ExtensionFieldSpec,
  t: TFunction,
  pluginId: string | undefined,
  property: 'label' | 'description' | 'placeholder'
): string => {
  // NEW: Prefer API-translated
  if (property === 'label' && field.label_translated) {
    return field.label_translated;
  }
  if (property === 'description' && field.description_translated) {
    return field.description_translated;
  }
  
  // Fall back to host i18n
  if (!pluginId || !fallback) {
    return fallback;
  }
  // ... existing host i18n lookup ...
};
```

**Files changed**:
- `/Users/asuka/code/magi/frontend/src/components/settings/PluginSettingsFields.tsx` (±15 lines)

**C. Plugin Settings Actions (PluginSettingsActions.tsx)**

Similar pattern: prefer `action.label_translated` from API, fall back to host i18n.

**Files changed**:
- `/Users/asuka/code/magi/frontend/src/components/settings/PluginSettingsActions.tsx` (±10 lines)

**D. Custom UI Blocks (PluginSettingsCustomBlocks.tsx)**

Similar pattern: prefer `block.title_translated` / `block.description_translated` from API.

**Files changed**:
- `/Users/asuka/code/magi/frontend/src/components/settings/PluginSettingsCustomBlocks.tsx` (±10 lines)

**E. Activation Flow (TimelineSourcesSection.tsx)**

New pattern: Backend returns activation_flow with translated fields in SensorSourceStatusItem, frontend uses them.

```typescript
const getActivationFlowText = (
  flow: ActivationFlowSpec,
  key: 'title' | 'description' | 'confirm_label' | 'cancel_label',
  fallback: string
): string => {
  // NEW: Activation flow from API includes translations
  if (flow[`${key}_translated`]) {
    return flow[`${key}_translated`];
  }
  // Fallback to host i18n
  return getPluginTranslation(t, pluginId, `activation.${key}`, fallback);
};
```

**Files changed**:
- `/Users/asuka/code/magi/frontend/src/components/settings/TimelineSourcesSection.tsx` (±10 lines)

### 3.3 Plugin I18n Schema (NEW)

After migration, each plugin's `i18n/{lang}.json` will use this schema:

```json
{
  "{plugin_id}": {
    "name": "Display name",
    "description": "Long description",
    "sections": {
      "general": "General",
      "sync": "Sync",
      "storage": "Storage"
    },
    "fields": {
      "{contribution_id}.{field_key}": {
        "label": "Field Label",
        "description": "Field description",
        "placeholder": "Field placeholder (optional)",
        "options": {
          "{value}": "Option Label"
        }
      }
    },
    "actions": {
      "{action_id}": {
        "label": "Action Label",
        "description": "Action description",
        "button_label": "Click Me"
      }
    },
    "ui_blocks": {
      "{block_id}": {
        "title": "Block Title",
        "description": "Block description"
      }
    },
    "activation": {
      "title": "Enable {plugin_name}",
      "description": "This source needs setup...",
      "confirm_label": "Enable",
      "cancel_label": "Not now"
    }
  },
  "summary": {
    "played_track": "{title} ({duration}s)",
    "visited_page": "Visited {title}"
  },
  "activity_types": {
    "commit": "Commit",
    "checkout": "Checkout"
  }
}
```

**Example: chrome-history after migration** (NEW):
```json
{
  "chrome_history": {
    "name": "Chrome History",
    "description": "Local Google Chrome browsing history ingestion for the timeline",
    "sections": {
      "general": "General",
      "sync": "Sync",
      "storage": "Storage",
      "activation": "Activation"
    },
    "fields": {
      "sensors.chrome_history.profile": {
        "label": "Profile",
        "description": "Chrome profile directory to read, such as Default or Profile 1."
      },
      "sensors.chrome_history.sync_mode": {
        "label": "Sync Mode",
        "description": "Control how Chrome history should be synchronized.",
        "options": {
          "manual": "Manual",
          "interval": "Interval"
        }
      },
      "sensors.chrome_history.initial_sync_policy": {
        "label": "Initial Sync Policy",
        "description": "How to seed the initial timeline",
        "options": {
          "full": "Sync full history",
          "lookback_days": "Sync recent days",
          "from_now": "Only new records from now on"
        }
      }
    },
    "activation": {
      "title": "Enable Chrome History",
      "description": "Chrome history contains sensitive local data. Choose how the first sync should seed the timeline before this source starts running.",
      "confirm_label": "Enable source",
      "cancel_label": "Not now"
    }
  },
  "summary": {
    "single_visit": "{title}",
    "multiple_visits": "{title} ({count} visits)"
  }
}
```

---

## 4. Migration Plan (3 Phases)

### Phase 1: Backend & API (Dual-Rail)  
**Duration**: 2 hours  
**Plugins affected**: 0 (no plugin changes)

**Tasks**:
1. Extend `_serialize_field()` in `plugins_common.py` to add `label_translated`, `description_translated`, `options[].label_translated` (±25 lines)
2. Extend `_serialize_manifest()` to add `name_translated`, `description_translated` (±10 lines)
3. Update `/sensors/status` endpoint to pre-translate display_name, description (±15 lines)
4. Update TypeScript API schemas: `ExtensionFieldSpec`, `SensorSourceStatusItem`, `ActivationFlowSpec` (±30 lines)

**Files changed** (4):
- `backend/src/magi/api/routers/plugins_common.py`
- `backend/src/magi/api/routers/sensors.py`
- `frontend/src/api/modules/plugins.ts`
- `frontend/src/api/modules/sensors.ts`

**Backward compatibility**: Old fields still present; new `*_translated` fields optional.

**Verification**:
```bash
# Ensure /sensors/status still returns all old fields
curl http://localhost:5173/api/sensors/status | jq '.[] | {display_name, display_name_translated}'

# Ensure plugins manifest returns translations
curl http://localhost:5173/api/plugins/chrome-history | jq '.manifest | {name, name_translated}'
```

### Phase 2: Frontend Resolution (Dual-Rail)  
**Duration**: 2.5 hours  
**Plugins affected**: 11 (no changes, just frontend fallback logic)

**Tasks**:
1. Update `timeline-source-copy.ts`: prefer API translated over host i18n (±5 lines)
2. Update `PluginSettingsFields.tsx`: prefer `field.label_translated` over host i18n (±20 lines)
3. Update `PluginSettingsActions.tsx`: prefer `action.label_translated` over host i18n (±15 lines)
4. Update `PluginSettingsCustomBlocks.tsx`: prefer `block.title_translated` over host i18n (±15 lines)
5. Update `TimelineSourcesSection.tsx`: handle activation_flow translations (±15 lines)

**Files changed** (5):
- `frontend/src/utils/timeline-source-copy.ts`
- `frontend/src/components/settings/PluginSettingsFields.tsx`
- `frontend/src/components/settings/PluginSettingsActions.tsx`
- `frontend/src/components/settings/PluginSettingsCustomBlocks.tsx`
- `frontend/src/components/settings/TimelineSourcesSection.tsx`

**Backward compatibility**: Host i18n still consulted; API translations take priority.

**Verification**:
```bash
# UI should still render correctly (translations from backend first, then host i18n fallback)
npm run dev  # Test settings page for each plugin
```

### Phase 3: Plugin I18n Migration & Cleanup (Per-Plugin)  
**Duration**: 3 hours (8 plugins × 15 min each)  
**Plugins to migrate** (in order):
1. chrome-history
2. git-activity
3. calendar
4. photo-library
5. screen-time
6. system-media
7. terminal-history
8. core-tools

**For each plugin** (repeat 8 times):

**3a. Extract from host i18n** (2 min):
```bash
jq '.settings.plugins."{plugin_id}"' frontend/src/i18n/locales/en/app.json > /tmp/{plugin_id}-en.json
jq '.settings.plugins."{plugin_id}"' frontend/src/i18n/locales/zh-CN/app.json > /tmp/{plugin_id}-zh.json
```

**3b. Reformat into plugin schema** (5 min):
```json
// Transform from:
{
  "name": "...",
  "fields": {
    "sensors.chrome_history.profile": { "label": "...", "description": "..." }
  }
}

// Into:
{
  "chrome_history": {
    "name": "...",
    "fields": {
      "sensors.chrome_history.profile": { "label": "...", "description": "..." }
    }
  }
}
```

**3c. Merge with existing plugin i18n** (3 min):
```bash
jq -s 'reduce .[] as $item ({}; . * $item)' \
  existing_plugin/i18n/en.json /tmp/en-new.json > plugin/i18n/en.json.new
mv plugin/i18n/en.json.new plugin/i18n/en.json
```

**3d. Test plugin loads** (3 min):
```bash
# Verify no i18n errors in backend logs
# Test that plugin settings UI still renders correctly
```

**3e. Delete host i18n entries** (1 min):
```bash
jq 'del(.settings.plugins."{plugin_id}", .timeline.sources."{source_name}", .settings.timeline.sourceDesc."{source_name}")' \
  frontend/src/i18n/locales/en/app.json > app.json.tmp
mv app.json.tmp frontend/src/i18n/locales/en/app.json
# Repeat for zh-CN
```

**Files changed** (per plugin, 2×):
- `~/.magi/plugins/{plugin_id}/i18n/en.json`
- `~/.magi/plugins/{plugin_id}/i18n/zh-CN.json`
- `frontend/src/i18n/locales/en/app.json` (delete entries)
- `frontend/src/i18n/locales/zh-CN/app.json` (delete entries)

**Total files modified in Phase 3**: 8 plugins × 4 files = 32 file updates

**Verification per plugin**:
```bash
# After migrating chrome-history:
curl http://localhost:5173/api/plugins/chrome-history | jq '.manifest'
# Should show name, description translated from plugin i18n

# Frontend should still work:
# 1. Check settings page renders field labels
# 2. Check activation dialog shows correct text
# 3. Check plugin is enabled/disabled correctly
```

### Phase 4: Final Cleanup (1 hour)
**Duration**: 1 hour

**Tasks**:
1. Remove fallback logic from frontend components (all host i18n lookups can be deleted)
2. Verify all plugin tests pass
3. Update documentation: `/docs/plugin-i18n.md` with new schema
4. Verify no `settings.plugins.*` entries remain in host `app.json`

**Files changed**:
- `frontend/src/utils/timeline-source-copy.ts` (simplify, -3 lines)
- `frontend/src/components/settings/PluginSettingsFields.tsx` (simplify, -10 lines)
- `frontend/src/components/settings/PluginSettingsActions.tsx` (simplify, -5 lines)
- `frontend/src/components/settings/PluginSettingsCustomBlocks.tsx` (simplify, -5 lines)
- `frontend/src/components/settings/TimelineSourcesSection.tsx` (simplify, -5 lines)
- `docs/plugin-i18n.md` (new, +50 lines)

**After Phase 4**: Zero plugin entries in host i18n; all plugins self-describing.

---

## 5. Files Affected Summary

### Backend (Phase 1)
- `/backend/src/magi/api/routers/plugins_common.py` (+25 lines)
- `/backend/src/magi/api/routers/sensors.py` (+15 lines)

### Frontend (Phase 2)
- `/frontend/src/api/modules/plugins.ts` (+10 lines)
- `/frontend/src/api/modules/sensors.ts` (+10 lines)
- `/frontend/src/utils/timeline-source-copy.ts` (+5 lines)
- `/frontend/src/components/settings/PluginSettingsFields.tsx` (+20 lines)
- `/frontend/src/components/settings/PluginSettingsActions.tsx` (+15 lines)
- `/frontend/src/components/settings/PluginSettingsCustomBlocks.tsx` (+15 lines)
- `/frontend/src/components/settings/TimelineSourcesSection.tsx` (+15 lines)

### Plugin I18n (Phase 3)
- `~/.magi/plugins/chrome-history/i18n/en.json` (expand)
- `~/.magi/plugins/chrome-history/i18n/zh-CN.json` (expand)
- `~/.magi/plugins/git-activity/i18n/en.json` (expand)
- `~/.magi/plugins/git-activity/i18n/zh-CN.json` (expand)
- ... (repeat for all 8 plugins, 16 files total)

### Host I18n (Phase 3)
- `/frontend/src/i18n/locales/en/app.json` (delete ~100 lines)
- `/frontend/src/i18n/locales/zh-CN/app.json` (delete ~100 lines)

### Documentation (Phase 4)
- `/docs/plugin-i18n.md` (new, 50 lines)

**Total files touched**: ~35 files across 4 phases.

---

## 6. Risks & Rollback

### Risk 1: Incomplete plugin i18n during migration
**Symptom**: Plugin settings page shows untranslated text (e.g. "Field Label" instead of "标签").

**Cause**: Field translation not included in plugin i18n during Phase 3 migration.

**Mitigation**:
- Audit each plugin's `app.json` entries before deletion
- Verify plugin i18n file loads correctly after migration
- Test UI renders translated text before committing host i18n deletion

**Rollback**: If detected after commit, restore host i18n entry and re-run plugin i18n migration.

### Risk 2: Backend API changes break frontend
**Symptom**: Frontend expects `label_translated` but backend doesn't provide it.

**Cause**: API changes in Phase 1 incomplete or incompatible.

**Mitigation**:
- API changes are additive (new fields only, existing fields unchanged)
- Frontend fallback logic ensures graceful degradation
- Test with both old and new API responses

**Rollback**: Remove Phase 2 frontend changes; revert to host i18n-only lookups.

### Risk 3: Plugin not loaded during backend serialization
**Symptom**: Backend can't access plugin's PluginI18n instance, returns raw English only.

**Cause**: Plugin installed but not yet loaded by PluginManager.

**Mitigation**:
- `_get_plugin_i18n()` falls back to file-based PluginI18n if plugin not in manager
- File-based PluginI18n reads directly from `plugin_dir/i18n/*.json`
- Both paths produce identical results

**Rollback**: None needed; fallback is built-in.

### Risk 4: Missing activation_flow in API response during transition
**Symptom**: Activation dialog doesn't render (missing activation_flow).

**Cause**: Older plugin version without `metadata.activation_flow` field.

**Mitigation**:
- Activation flow is optional; if missing, dialog simply doesn't appear
- API response always includes activation_flow if defined in manifest
- No new activation_flow data during transition

**Rollback**: Frontend activation dialog renders with host i18n fallback during Phase 2.

### Risk 5: Translation keys don't match between host and plugin i18n
**Symptom**: Field "Sync Interval" in host i18n doesn't match plugin i18n "Sync Interval (minutes)".

**Cause**: Copy-paste error or inconsistency during Phase 3 migration.

**Mitigation**:
- Script to extract and validate host → plugin mapping
- Diff host vs. plugin entries before deletion
- Manual review per plugin

**Rollback**: Keep host i18n entries for that plugin; re-run migration.

### Rollback Strategy (Any Phase)

If critical issue found:

**Phase 1 rollback**: Revert backend API changes (1 commit).
```bash
git revert <phase1-commit>
```

**Phase 2 rollback**: Revert frontend changes (1 commit).
```bash
git revert <phase2-commit>
```

**Phase 3 rollback** (per plugin): Restore host i18n entries and reset plugin i18n.
```bash
git checkout frontend/src/i18n/locales/en/app.json
git checkout ~/.magi/plugins/{plugin_id}/i18n/en.json
```

**Full rollback** (all phases): Revert all commits up to Phase 0.
```bash
git revert <phase1-commit>..<phase4-commit>
```

---

## 7. Conclusion

This refactor decouples plugins from the host's i18n system, enabling:
- **Portability**: Plugins are fully self-describing; zero host changes to add new plugins.
- **Maintainability**: Translation updates don't require host app rebuild.
- **Scalability**: Per-plugin i18n naturally scales with more plugins.

**Timeline**: 8 hours total (2+2.5+3+1 for phases).  
**Risk**: Low (dual-rail design, backward compatible).  
**Effort**: ~40 file changes across backend, frontend, and 8 plugins.

The design follows the "seed map refactor" pattern: Phase 1 adds new data, Phase 2 consumes it preferentially, Phase 3 migrates old data, Phase 4 removes old code.

