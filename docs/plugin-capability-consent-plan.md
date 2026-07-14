# Plugin Capability Declaration + Install Consent Implementation Plan

**Status:** Complete — both repository phases shipped and are covered by backend/frontend checks.

> Historical execution record: every task below is complete; the checked steps preserve the rollout and its validation sequence.

**Goal:** Formalize plugin capability declarations (`[[plugin.permissions.capabilities]]`), carry them through the registry like `official`, and gate install / update / sideload behind a grouped consent dialog. Declaration + disclosure + consent + review-checklist only — NO runtime enforcement (sandbox parked).

**Architecture:** `magi-plugins` gains a structured `[[plugin.permissions.capabilities]]` block per plugin; `build-registry.py` validates against a known-capability set and copies the declarations verbatim into each `registry.json` entry. `magi` parses capabilities into the SDK manifest/registry models, surfaces them on the registry API, persists the user-consented set into `PluginSettings` at registry install/update, and renders a grouped `PluginConsentDialog` before install (registry + sideload via a new inspect endpoint) and before update when the new declaration exceeds what the user already consented to.

**Tech Stack:** Python (build-registry.py, pydantic SDK models, FastAPI routes, pytest), TypeScript/React (shadcn Dialog, vitest), JSON registry, bilingual i18n (en + zh-CN).

**Spec reference:** `docs/plugin-capability-consent-design.md` (committed `87f56f22`).

**Refinement vs spec §4.1:** `PluginCapability.capability` is typed `str` (not `Literal`) for forward-compat — an unknown capability in a newer `registry.json` must not break `model_validate` and bring down the whole marketplace. The known-enum is enforced authoritatively at build time (`build-registry.py` `KNOWN_CAPABILITIES` gate, CI-checked) and rendered with a known-category map + graceful fallback in the frontend.

**Two repos, two phases:**
- **Phase A** (Tasks A1–A3) — `/Users/asuka/code/magi-plugins`: build-registry capability gate + propagation; migrate 15 plugins; regenerate registry.json.
- **Phase B** (Tasks B1–B6) — `/Users/asuka/code/magi`: SDK models; backend schemas/route/persist; sideload inspect endpoint; frontend capability lib + consent dialog + wiring + i18n + type-gen; verification.

---

## File Structure

| Path | Repo | Action | Responsibility |
|------|------|--------|----------------|
| `scripts/build-registry.py` | magi-plugins | Modify | Validate capabilities vs known set; copy into entry |
| `plugins/*/plugin.toml` (14) | magi-plugins | Modify | Add `[[plugin.permissions.capabilities]]` |
| `registry.json` | magi-plugins | Regenerate | Now carries `capabilities` per entry |
| `agents.md` | magi-plugins | Modify | Document the capability declaration convention |
| `sdk/src/magi_plugin_sdk/contracts.py` | magi | Modify | `PluginCapability`, `PluginPermissions`, manifest/entry fields |
| `backend/src/magi/plugins/contracts.py` | magi | Modify | Re-export the two new models |
| `backend/src/magi/config/plugin_models.py` | magi | Modify | `PluginSettings.consented_capabilities` |
| `backend/src/magi/api/routers/plugins_schemas.py` | magi | Modify | capabilities on manifest + registry response |
| `backend/src/magi/api/routers/plugins_registry_routes.py` | magi | Modify | Map `capabilities`; persist on update |
| `backend/src/magi/api/routers/plugins_common.py` | magi | Modify | Persist consented set on install; projection |
| `backend/src/magi/api/routers/plugins_install_jobs.py` | magi | Modify | Persist consented set on update job |
| `backend/src/magi/api/routers/plugins_install_routes.py` | magi | Modify | `/install/upload/inspect` endpoint |
| `backend/src/magi/plugins/installation.py` | magi | Modify | `inspect_plugin_archive` |
| `backend/tests/plugins/test_capability_contracts.py` | magi | Create | SDK model parsing tests |
| `backend/tests/plugins/test_capability_consent.py` | magi | Create | Config field + projection + inspect |
| `frontend/src/api/modules/plugins.ts` | magi | Modify | Types + `inspectUpload` |
| `frontend/src/lib/pluginCapabilities.ts` | magi | Create | Category meta map + consent-diff helper |
| `frontend/src/components/plugins/PluginConsentDialog.tsx` | magi | Create | Grouped consent dialog |
| `frontend/src/components/settings/PluginMarketplace.tsx` | magi | Modify | Wire dialog into install/update/upload |
| `frontend/src/i18n/locales/{en,zh-CN}/app.json` | magi | Modify | Consent + capability strings |
| `frontend/src/types/api/generated.ts` | magi | Regenerate | `npm run gen:api-types` |
| `frontend/src/__tests__/pluginCapabilities.test.ts` | magi | Create | vitest for the helper |
| `frontend/src/__tests__/PluginConsentDialog.test.tsx` | magi | Create | vitest render test |

---

# PHASE A — magi-plugins (capability schema + registry propagation + migration)

All Phase A tasks run from `/Users/asuka/code/magi-plugins`.

## Task A1: build-registry.py — known-capability gate + propagation

**Files:**
- Modify: `scripts/build-registry.py`

- [x] **Step 1: Read the current build_entry + main**

Run: `sed -n '46,114p' scripts/build-registry.py`
Confirm: `build_entry(plugin_dir, official_ids)` builds `entry`, sets `entry["contribution_types"]` (~:79); `main()` loops `build_entry(child, official_ids)` and writes `registry.json`.

- [x] **Step 2: Add the known-capability set + a copy/validate helper**

In `scripts/build-registry.py`, after the `OFFICIAL_ALLOWLIST_PATH` constant (~:21), add:

```python
# Authoritative known-capability enum. The wire model (magi SDK) is permissive
# (str) for forward-compat; THIS is the gate that keeps typos / unknown
# capabilities out of registry.json. Adding a capability is a deliberate act:
# update this set AND the magi SDK + frontend category map together.
KNOWN_CAPABILITIES = {
    "screen_recording", "accessibility", "calendar", "photos",
    "contacts", "system_media",
    "filesystem_read", "filesystem_write", "network", "subprocess",
}
```

- [x] **Step 3: Copy capabilities in build_entry**

In `build_entry`, right after the `entry["contribution_types"] = ...` line (~:79), add:

```python
    permissions = meta.get("permissions", {}) or {}
    capabilities = permissions.get("capabilities", [])
    if capabilities:
        entry["capabilities"] = capabilities  # verbatim; validated in main()
```

- [x] **Step 4: Validate against the known set in main() before writing**

In `main()`, after the `for child in ...` loop builds `entries` and before constructing `registry`, add:

```python
    unknown: list[str] = []
    for entry in entries:
        for cap in entry.get("capabilities", []):
            name = cap.get("capability")
            if name not in KNOWN_CAPABILITIES:
                unknown.append(f"{entry['plugin_id']}: {name!r}")
    if unknown:
        print("\nERROR: unknown capability(ies) declared:", file=sys.stderr)
        for u in unknown:
            print(f"  ! {u}", file=sys.stderr)
        print(
            "Allowed: " + ", ".join(sorted(KNOWN_CAPABILITIES)),
            file=sys.stderr,
        )
        sys.exit(1)
```

(`sys` is already imported.)

- [x] **Step 5: Verify build still runs clean (no capabilities yet)**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/build-registry.py && python scripts/gen_registry.py
git diff --exit-code -- registry.json && echo "NEUTRAL: no plugin declares capabilities yet"
```
Expected: `NEUTRAL: ...` (registry.json unchanged — no plugin declares capabilities until Task A2).

- [x] **Step 6: Verify the gate rejects an unknown capability**

```bash
cd /Users/asuka/code/magi-plugins
# Temporarily add a bogus capability to any plugin, then build:
python3 - <<'PY'
import pathlib
p = pathlib.Path("plugins/git_activity/plugin.toml")
p.write_text(p.read_text() + '\n[[plugin.permissions.capabilities]]\ncapability = "bogus_xyz"\n')
PY
python scripts/build-registry.py; echo "exit=$?"
git checkout -- plugins/git_activity/plugin.toml
```
Expected: prints `! git-activity: 'bogus_xyz'` and `exit=1`. Then the checkout reverts it.

- [x] **Step 7: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add scripts/build-registry.py
git commit -m "feat(registry): validate + propagate plugin capability declarations"
```

---

## Task A2: Migrate 15 plugins' capability declarations + regenerate

**Files:**
- Modify: `plugins/<id>/plugin.toml` (14 plugins; `browser_history_core` declares none)
- Regenerate: `registry.json`

> **TOML placement rule:** `[[plugin.permissions.capabilities]]` is a fully-qualified array-of-tables. Append the blocks at the **end of the file** (after any existing `[plugin.*]` subtables) — this never breaks the `[plugin]` scalar keys. For `screenshot_timeline`, also delete the legacy `declares = [...]` line and KEEP `memory_access`.

- [x] **Step 1: Append capability blocks to each plugin.toml**

Add the following block to the END of each file (exact `reason_i18n` text included; adjust a `scope` path only if it contradicts the plugin's actual reader):

`plugins/calendar_plugin/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "calendar"
reason_i18n = { en = "Read your calendar events and reminders", "zh-CN" = "读取你的日历事件与提醒事项" }

[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Library/Calendars"]
reason_i18n = { en = "Parse the local calendar store", "zh-CN" = "解析本地日历数据" }
```

`plugins/chrome-history/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Library/Application Support/Google/Chrome", "%LOCALAPPDATA%\\Google\\Chrome"]
reason_i18n = { en = "Read the local Chrome history database", "zh-CN" = "读取本地 Chrome 历史数据库" }
```

`plugins/firefox-history/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Library/Application Support/Firefox", "%APPDATA%\\Mozilla\\Firefox"]
reason_i18n = { en = "Read the local Firefox history database", "zh-CN" = "读取本地 Firefox 历史数据库" }
```

`plugins/edge-history/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["%LOCALAPPDATA%\\Microsoft\\Edge"]
reason_i18n = { en = "Read the local Edge history database", "zh-CN" = "读取本地 Edge 历史数据库" }
```

`plugins/terminal_history/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/.zsh_history", "~/.bash_history", "~/.local/share/fish"]
reason_i18n = { en = "Read your shell command history files", "zh-CN" = "读取你的 shell 命令历史文件" }
```

`plugins/netease_music/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Library/Containers/com.netease.163music"]
reason_i18n = { en = "Read the NetEase Music local play history", "zh-CN" = "读取网易云音乐本地播放历史" }
```

`plugins/steam_play_history/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Library/Application Support/Steam", "C:\\Program Files (x86)\\Steam"]
reason_i18n = { en = "Read local Steam files to infer play sessions", "zh-CN" = "读取本地 Steam 文件以推断游戏时段" }
```

`plugins/screen_time/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Library/Application Support/Knowledge"]
reason_i18n = { en = "Read the local app-usage data source", "zh-CN" = "读取本地应用用量数据源" }
```

`plugins/git_activity/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "subprocess"
scope = ["git"]
reason_i18n = { en = "Run git to read commit and checkout history", "zh-CN" = "调用 git 读取提交与检出历史" }

[[plugin.permissions.capabilities]]
capability = "filesystem_read"
reason_i18n = { en = "Discover and read local git repositories", "zh-CN" = "发现并读取本地 git 仓库" }
```

`plugins/photo-library/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "photos"
reason_i18n = { en = "Access your photo library and its metadata", "zh-CN" = "访问你的照片库及其元数据" }

[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Pictures"]
reason_i18n = { en = "Scan local photo files for metadata", "zh-CN" = "扫描本地照片文件的元数据" }
```

`plugins/telegram/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "network"
scope = ["api.telegram.org"]
reason_i18n = { en = "Connect to the Telegram Bot API", "zh-CN" = "连接 Telegram Bot API" }
```

`plugins/weixin/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "network"
reason_i18n = { en = "Connect to the iLink bot gateway", "zh-CN" = "连接 iLink 机器人网关" }
```

`plugins/system_media/plugin.toml`:
```toml
[[plugin.permissions.capabilities]]
capability = "system_media"
reason_i18n = { en = "Read system media playback (now-playing) info", "zh-CN" = "读取系统媒体播放（正在播放）信息" }
```

`plugins/screenshot_timeline/plugin.toml` — **delete** the `declares = [...]` line (keep `memory_access`), then add:
```toml
[[plugin.permissions.capabilities]]
capability = "screen_recording"
reason_i18n = { en = "Capture screenshots of your screen", "zh-CN" = "截取你的屏幕画面" }

[[plugin.permissions.capabilities]]
capability = "accessibility"
optional = true
reason_i18n = { en = "Read the active window for context (optional)", "zh-CN" = "读取活动窗口作为上下文（可选）" }

[[plugin.permissions.capabilities]]
capability = "filesystem_write"
scope = ["~/.magi"]
reason_i18n = { en = "Save screenshots and thumbnails", "zh-CN" = "保存截图与缩略图" }

[[plugin.permissions.capabilities]]
capability = "subprocess"
scope = ["magi-vision-helper"]
reason_i18n = { en = "Run the bundled OCR/vision helper", "zh-CN" = "运行随附的 OCR/视觉助手" }
```

(`browser_history_core` — no change; it is a hidden library.)

- [x] **Step 2: Regenerate the registry (two-step pipeline)**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/build-registry.py && python scripts/gen_registry.py
echo "exit=$?"
```
Expected: `exit=0` (no unknown-capability error), 15 plugins printed.

- [x] **Step 3: Verify capabilities landed + behavior-neutral elsewhere**

```bash
cd /Users/asuka/code/magi-plugins
python3 - <<'PY'
import json
d = json.load(open("registry.json"))
by = {p["plugin_id"]: p for p in d["plugins"]}
assert by["telegram"]["capabilities"][0]["capability"] == "network", "telegram network missing"
assert by["calendar"]["capabilities"][0]["capability"] == "calendar"
assert "capabilities" not in by["browser_history_core"], "library should declare none"
# screenshot_timeline: 4 caps, accessibility optional
caps = {c["capability"]: c for c in by["screenshot_timeline"]["capabilities"]}
assert caps["accessibility"].get("optional") is True
print("OK capabilities:", {k: len(v.get("capabilities", [])) for k, v in by.items()})
PY
git diff --stat -- registry.json
```
Expected: assertions pass; `git diff --stat` shows registry.json changed (only `capabilities` added — other fields untouched).

- [x] **Step 4: Document the convention in agents.md**

In `/Users/asuka/code/magi-plugins/agents.md`, under the **Do** list, add:
```markdown
- Declare what a plugin accesses with `[[plugin.permissions.capabilities]]` (capability from the known set: screen_recording, accessibility, calendar, photos, contacts, system_media, filesystem_read, filesystem_write, network, subprocess; optional `scope`, `optional`, `reason_i18n`). Users see these at install for consent; reviewers use them as a checklist.
```
And under **Don't**:
```markdown
- Don't declare a capability outside the known set — `build-registry.py` will fail the build. Adding a new capability requires updating the SDK + frontend too.
```

- [x] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/build-registry.py && python scripts/gen_registry.py
git add plugins/*/plugin.toml registry.json agents.md
git status --short
git commit -m "feat(plugins): declare capabilities for all plugins; regenerate registry"
```

---

## Task A3: Phase A verification

- [x] **Step 1: Registry consistent, CI-equivalent green**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/build-registry.py && python scripts/gen_registry.py
git diff --exit-code -- registry.json && echo "registry in sync"
git log --oneline -3 | cat
```
Expected: `registry in sync` (regeneration is idempotent after commit), the two Phase A commits present. This mirrors what CI `registry-in-sync` enforces.

---

# PHASE B — magi (SDK + backend + consent UI)

All Phase B tasks run from `/Users/asuka/code/magi`. Backend tests: `cd backend && ../.venv/bin/python -m pytest …`. Frontend: `cd frontend && npx vitest run …`.

## Task B1: SDK capability models

**Files:**
- Modify: `sdk/src/magi_plugin_sdk/contracts.py`
- Modify: `backend/src/magi/plugins/contracts.py`
- Test: `backend/tests/plugins/test_capability_contracts.py` (create)

- [x] **Step 1: Write failing tests**

Create `backend/tests/plugins/test_capability_contracts.py`:
```python
from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginRegistryEntry,
)


def test_capability_parses_all_fields():
    c = PluginCapability.model_validate(
        {
            "capability": "filesystem_read",
            "scope": ["~/Library/Calendars"],
            "optional": True,
            "reason_i18n": {"en": "read cal", "zh-CN": "读日历"},
        }
    )
    assert c.capability == "filesystem_read"
    assert c.scope == ["~/Library/Calendars"]
    assert c.optional is True
    assert c.reason_i18n["zh-CN"] == "读日历"


def test_capability_defaults():
    c = PluginCapability.model_validate({"capability": "network"})
    assert c.scope == []
    assert c.optional is False
    assert c.reason == ""


def test_unknown_capability_string_still_parses():
    # Forward-compat: wire model is permissive str, not Literal.
    c = PluginCapability.model_validate({"capability": "future_thing"})
    assert c.capability == "future_thing"


def test_manifest_reads_permissions_capabilities():
    m = PluginManifest.model_validate(
        {
            "id": "x",
            "name": "X",
            "version": "1.0.0",
            "permissions": {
                "capabilities": [{"capability": "network", "scope": ["a.com"]}],
                "declares": ["legacy"],          # legacy key tolerated
                "memory_access": ["write_l1"],   # legacy key tolerated
            },
        }
    )
    assert [c.capability for c in m.capabilities] == ["network"]


def test_manifest_without_permissions_has_empty_capabilities():
    m = PluginManifest.model_validate({"id": "y", "name": "Y", "version": "1.0.0"})
    assert m.capabilities == []


def test_registry_entry_top_level_capabilities():
    e = PluginRegistryEntry.model_validate(
        {
            "plugin_id": "x",
            "name": "X",
            "version": "1.0.0",
            "capabilities": [{"capability": "calendar"}],
        }
    )
    assert e.capabilities[0].capability == "calendar"
```

- [x] **Step 2: Run, verify failure**

Run: `cd backend && ../.venv/bin/python -m pytest tests/plugins/test_capability_contracts.py -v`
Expected: FAIL (`ImportError: PluginCapability`).

- [x] **Step 3: Add the models to the SDK**

In `sdk/src/magi_plugin_sdk/contracts.py`, after `class LocalizedText` (~:214), add:
```python
class PluginCapability(BaseModel):
    """A single self-declared capability shown to the user for install-time
    consent. NOT enforced at runtime (no sandbox this iteration).

    ``capability`` is a permissive ``str`` for forward-compat: a newer
    registry may declare a capability an older app doesn't know, and that must
    not break parsing. The authoritative known set is enforced at build time in
    magi-plugins ``scripts/build-registry.py`` and rendered with a known map +
    graceful fallback in the frontend. Known values: screen_recording,
    accessibility, calendar, photos, contacts, system_media, filesystem_read,
    filesystem_write, network, subprocess.
    """

    capability: str
    scope: list[str] = Field(default_factory=list)
    """For filesystem_read/write/network/subprocess: path prefixes / hosts /
    executables. Empty = unspecified (broadest). Ignored for OS permissions."""
    optional: bool = False
    reason: str = ""
    reason_i18n: dict[str, str] = Field(default_factory=dict)


class PluginPermissions(BaseModel):
    """The ``[plugin.permissions]`` table. ``extra='allow'`` tolerates legacy
    keys (``declares``, ``memory_access``) so existing manifests still parse."""

    capabilities: list[PluginCapability] = Field(default_factory=list)
    model_config = {"extra": "allow"}
```

In `class PluginManifest`, after the `suggestion_descriptor` field (~:321), add:
```python
    permissions: Optional[PluginPermissions] = None
    """Declared capabilities + legacy permission keys, from the
    ``[plugin.permissions]`` table. See :class:`PluginCapability`."""

    @property
    def capabilities(self) -> list[PluginCapability]:
        return self.permissions.capabilities if self.permissions else []
```
(`Optional` is already imported.)

In `class PluginRegistryEntry`, after the `suggestion_descriptor` field (~:383), add:
```python
    capabilities: list[PluginCapability] = Field(default_factory=list)
    """Self-declared capabilities, copied verbatim from the plugin's
    ``[[plugin.permissions.capabilities]]`` by build-registry.py."""
```

- [x] **Step 4: Re-export from the backend contracts module**

In `backend/src/magi/plugins/contracts.py`, add `PluginCapability,` and `PluginPermissions,` to the import list from `magi_plugin_sdk.contracts` (alphabetical-ish, near `PluginContribution`).

- [x] **Step 5: Run tests, verify pass**

Run: `cd backend && ../.venv/bin/python -m pytest tests/plugins/test_capability_contracts.py -v`
Expected: all 6 PASS.

- [x] **Step 6: Commit**

```bash
cd /Users/asuka/code/magi
git add sdk/src/magi_plugin_sdk/contracts.py backend/src/magi/plugins/contracts.py backend/tests/plugins/test_capability_contracts.py
git commit -m "feat(sdk): PluginCapability/PluginPermissions + manifest/registry capability fields"
```

---

## Task B2: Config field + registry API surfacing + consent persistence + projection

**Why one task:** the persisted `consented_capabilities`, the registry-response capabilities, and the manifest projection that reads both are coupled — splitting them leaves an intermediate commit where the projection reads a field nothing writes.

**Files:**
- Modify: `backend/src/magi/config/plugin_models.py` (`PluginSettings`)
- Modify: `backend/src/magi/api/routers/plugins_schemas.py` (`PluginManifestResponse`, `PluginRegistryEntryResponse`)
- Modify: `backend/src/magi/api/routers/plugins_registry_routes.py` (map capabilities; persist on update)
- Modify: `backend/src/magi/api/routers/plugins_common.py` (persist on install; projection sites)
- Modify: `backend/src/magi/api/routers/plugins_install_jobs.py` (persist on update job)
- Test: `backend/tests/plugins/test_capability_consent.py` (create)

- [x] **Step 1: Read the exact integration sites**

```bash
cd /Users/asuka/code/magi
sed -n '10,23p' backend/src/magi/config/plugin_models.py
sed -n '28,39p;70,88p' backend/src/magi/api/routers/plugins_schemas.py
sed -n '133,144p;414,418p;552,556p;601,613p' backend/src/magi/api/routers/plugins_common.py
sed -n '216,240p' backend/src/magi/api/routers/plugins_install_jobs.py
sed -n '150,162p' backend/src/magi/api/routers/plugins_registry_routes.py
```
Confirm the sites referenced below.

- [x] **Step 2: Write failing tests**

Create `backend/tests/plugins/test_capability_consent.py`:
```python
from magi.config.plugin_models import PluginSettings
from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginPackageState,
    PluginPermissions,
)
from magi.api.routers.plugins_common import _serialize_package_lightweight


def test_plugin_settings_consented_default_none():
    assert PluginSettings().consented_capabilities is None
    s = PluginSettings(consented_capabilities=[PluginCapability(capability="network")])
    assert s.consented_capabilities[0].capability == "network"


def _state(plugin_id, caps):
    return PluginPackageState(
        manifest=PluginManifest(
            id=plugin_id,
            name=plugin_id,
            version="1.0.0",
            source="external",
            permissions=PluginPermissions(capabilities=caps),
        ),
        enabled=True,
    )


def test_projection_includes_declared_and_consented():
    declared = [PluginCapability(capability="network", scope=["a.com"])]
    consented = [PluginCapability(capability="network", scope=["a.com"])]
    state = _state("p", declared)
    packages = {"p": PluginSettings(consented_capabilities=consented)}
    resp = _serialize_package_lightweight(state, packages=packages)
    assert [c.capability for c in resp.manifest.capabilities] == ["network"]
    assert resp.manifest.consented_capabilities[0].scope == ["a.com"]


def test_projection_consented_none_when_absent():
    state = _state("p", [PluginCapability(capability="calendar")])
    resp = _serialize_package_lightweight(state, packages={})
    assert resp.manifest.consented_capabilities is None
    assert resp.manifest.capabilities[0].capability == "calendar"
```

- [x] **Step 3: Run, verify failure**

Run: `cd backend && ../.venv/bin/python -m pytest tests/plugins/test_capability_consent.py -v`
Expected: FAIL (`PluginSettings` has no `consented_capabilities`; projection lacks fields).

- [x] **Step 4: Add `consented_capabilities` to PluginSettings**

In `backend/src/magi/config/plugin_models.py`, add the import at the top (after line 7):
```python
from magi_plugin_sdk.contracts import PluginCapability
```
In `class PluginSettings`, after `official` (~:22):
```python
    consented_capabilities: Optional[List[PluginCapability]] = Field(
        default=None,
        description="Capabilities the user consented to at install/update. "
        "None means a legacy install predating consent (treated as empty).",
    )
```

- [x] **Step 5: Add capabilities to the response schemas**

In `backend/src/magi/api/routers/plugins_schemas.py`, add after the imports (line 7):
```python
from ...plugins.contracts import PluginCapability
```
In `class PluginManifestResponse`, after `manifest_path` (~:38):
```python
    capabilities: list[PluginCapability] = Field(default_factory=list)
    consented_capabilities: list[PluginCapability] | None = None
```
In `class PluginRegistryEntryResponse`, after `update_available` (~:87):
```python
    capabilities: list[PluginCapability] = Field(default_factory=list)
```

- [x] **Step 6: Map capabilities in the registry route**

In `backend/src/magi/api/routers/plugins_registry_routes.py`, in the `PluginRegistryEntryResponse(...)` construction (~:68-87), add before the closing `)`:
```python
                capabilities=entry.capabilities,
```

- [x] **Step 7: Wire the two manifest projection sites**

In `backend/src/magi/api/routers/plugins_common.py`, in the `PluginManifestResponse(...)` at `_serialize_manifest` (~:133-144) add before the close:
```python
        capabilities=manifest.capabilities,
        consented_capabilities=(
            packages[manifest.plugin_id].consented_capabilities
            if manifest.plugin_id in packages
            else None
        ),
```
In `_serialize_package_lightweight`'s `PluginManifestResponse(...)` (~:602-613) add the same two lines (it already has `packages` resolved above).

- [x] **Step 8: Persist consented set on registry install**

In `plugins_common.py` `_lightweight_install` (~:417), after `package_config["official"] = bool(entry.official)`:
```python
    package_config["consented_capabilities"] = [c.model_dump() for c in entry.capabilities]
```
In `plugins_common.py` `install_with_closure` manager path (~:554), replace the single-key `save_config({...official...})` with:
```python
            save_config(
                {
                    f"plugins.packages.{entry.plugin_id}.official": bool(entry.official),
                    f"plugins.packages.{entry.plugin_id}.consented_capabilities": [
                        c.model_dump() for c in entry.capabilities
                    ],
                }
            )
```
Also set the manifest's permissions in `_lightweight_install`'s `PluginManifest(...)` (~:432) so its `.capabilities` projects correctly. Add the import near the top of `plugins_common.py` (match existing contract imports): `from ...plugins.contracts import PluginPermissions` and in the constructor add:
```python
            permissions=PluginPermissions(capabilities=list(entry.capabilities)),
```

- [x] **Step 9: Persist consented set on registry update**

In `backend/src/magi/api/routers/plugins_install_jobs.py` `_run_registry_update`, after `new_state = await asyncio.to_thread(manager.install_plugin_from_directory, ...)` (~:239) and before `job.complete(...)`:
```python
            from ...config import save_config

            save_config(
                {
                    f"plugins.packages.{plugin_id}.consented_capabilities": [
                        c.model_dump() for c in entry.capabilities
                    ]
                }
            )
```
And in the sync route `update_plugin` (`plugins_registry_routes.py` ~:154, after `new_state = manager.install_plugin_from_directory(plugin_dir)`):
```python
    from ...config import save_config

    save_config(
        {
            f"plugins.packages.{plugin_id}.consented_capabilities": [
                c.model_dump() for c in entry.capabilities
            ]
        }
    )
```

- [x] **Step 10: Run tests, verify pass**

Run: `cd backend && ../.venv/bin/python -m pytest tests/plugins/test_capability_consent.py tests/plugins/test_capability_contracts.py -v`
Expected: all PASS.

- [x] **Step 11: Regression — plugins suite**

Run: `cd backend && ../.venv/bin/python -m pytest tests/plugins/ -q 2>&1 | tail -15`
Expected: no NEW failures (the 7 pre-existing chrome-history discovery failures noted in #1/#2 may remain).

- [x] **Step 12: Commit**

```bash
cd /Users/asuka/code/magi
git add backend/src/magi/config/plugin_models.py \
        backend/src/magi/api/routers/plugins_schemas.py \
        backend/src/magi/api/routers/plugins_registry_routes.py \
        backend/src/magi/api/routers/plugins_common.py \
        backend/src/magi/api/routers/plugins_install_jobs.py \
        backend/tests/plugins/test_capability_consent.py
git commit -m "feat(plugins): surface capabilities on registry API; persist consented set at install/update"
```

---

## Task B3: Sideload inspect endpoint

**Files:**
- Modify: `backend/src/magi/plugins/installation.py` (`inspect_plugin_archive`)
- Modify: `backend/src/magi/api/routers/plugins_install_routes.py` (route)
- Modify: `backend/src/magi/api/routers/plugins_schemas.py` (response reuse note)
- Test: append to `backend/tests/plugins/test_capability_consent.py`

- [x] **Step 1: Read the archive install internals to reuse**

Run: `sed -n '325,360p' backend/src/magi/plugins/installation.py`
Confirm `install_plugin_from_archive` does `self._extract_archive(archive_path, tmp_path)` → `self._find_manifest_in_tree(tmp_path)` → `self._load_manifest(manifest_file, source="external")`. The inspect method reuses exactly these without copying to the user root or persisting.

- [x] **Step 2: Write failing test**

Append to `backend/tests/plugins/test_capability_consent.py`:
```python
import io
import tarfile
from pathlib import Path


def _make_archive(tmp_path: Path) -> Path:
    toml = (
        b'[plugin]\n'
        b'id = "demo"\nname = "Demo"\nversion = "1.0.0"\n'
        b'entry_module = "plugin"\nentry_class = "Demo"\n'
        b'\n[[plugin.permissions.capabilities]]\n'
        b'capability = "network"\nscope = ["x.com"]\n'
    )
    archive = tmp_path / "demo.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo("demo/plugin.toml")
        info.size = len(toml)
        tf.addfile(info, io.BytesIO(toml))
    return archive


def test_inspect_reads_capabilities_without_installing(tmp_path):
    from magi.plugins.manager import PluginManager

    mgr = PluginManager.__new__(PluginManager)  # avoid full init
    archive = _make_archive(tmp_path)
    manifest = mgr.inspect_plugin_archive(archive)
    assert manifest.plugin_id == "demo"
    assert manifest.capabilities[0].capability == "network"
    assert manifest.capabilities[0].scope == ["x.com"]
```
> If `PluginManager.__new__` lacks the helper methods because they live on `PluginInstallationMixin`, instantiate the real manager fixture used by sibling tests instead (check `tests/plugins/conftest.py`); the assertion on the returned manifest is the point.

- [x] **Step 3: Run, verify failure**

Run: `cd backend && ../.venv/bin/python -m pytest tests/plugins/test_capability_consent.py::test_inspect_reads_capabilities_without_installing -v`
Expected: FAIL (`no attribute 'inspect_plugin_archive'`).

- [x] **Step 4: Implement `inspect_plugin_archive`**

In `backend/src/magi/plugins/installation.py`, in `PluginInstallationMixin`, after `install_plugin_from_archive` (~ end of that method, before the next method):
```python
    def inspect_plugin_archive(self, archive_path: Path) -> PluginManifest:
        """Extract + read plugin.toml from an archive WITHOUT installing or
        persisting anything. Used to surface declared capabilities for the
        pre-install consent step (sideload)."""
        with tempfile.TemporaryDirectory(prefix="magi-plugin-inspect-") as tmp:
            tmp_path = Path(tmp)
            self._extract_archive(archive_path, tmp_path)
            manifest_file = self._find_manifest_in_tree(tmp_path)
            if manifest_file is None:
                raise ValueError("Archive does not contain a plugin.toml")
            return self._load_manifest(manifest_file, source="external")
```
(`tempfile` and `Path` are already imported in this module.)

- [x] **Step 5: Add the inspect route**

In `backend/src/magi/api/routers/plugins_install_routes.py`, add (reuse the archive-extension validation shape from `start_plugin_upload_install_job`):
```python
@plugins_install_router.post("/install/upload/inspect", response_model=PluginManifestResponse)
async def inspect_plugin_upload(file: UploadFile):
    """Return declared capabilities + metadata of an uploaded archive WITHOUT
    installing it — drives the pre-install consent step for sideload."""
    legacy = legacy_plugins_module()
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t("plugins.errors.filename_required", fallback="Filename required"),
        )
    name = file.filename.lower()
    if not (name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".zip")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.archive_extension_invalid",
                fallback="Archive must be .tar.gz, .tgz, or .zip",
            ),
        )
    manager = legacy.resolve_plugin_manager()
    with tempfile.TemporaryDirectory(prefix="magi-upload-inspect-") as tmp:
        archive_path = Path(tmp) / file.filename
        archive_path.write_bytes(await file.read())
        try:
            manifest = manager.inspect_plugin_archive(archive_path)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PluginManifestResponse(
        plugin_id=manifest.plugin_id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        official=False,  # sideload is never official (see #2)
        contribution_types=[c.value for c in manifest.contribution_types],
        source="external",
        plugin_dir="",
        manifest_path="",
        capabilities=manifest.capabilities,
        consented_capabilities=None,
    )
```
Add `PluginManifestResponse` to the imports from `.plugins_schemas` at the top of the file, and add `"inspect_plugin_upload",` to `__all__`.

- [x] **Step 6: Run tests, verify pass**

Run: `cd backend && ../.venv/bin/python -m pytest tests/plugins/test_capability_consent.py -v`
Expected: all PASS (incl. the inspect test).

- [x] **Step 7: Commit**

```bash
cd /Users/asuka/code/magi
git add backend/src/magi/plugins/installation.py \
        backend/src/magi/api/routers/plugins_install_routes.py \
        backend/tests/plugins/test_capability_consent.py
git commit -m "feat(plugins): /install/upload/inspect endpoint for sideload consent"
```

---

## Task B4: Frontend capability lib + API types + type-gen

**Files:**
- Modify: `frontend/src/api/modules/plugins.ts`
- Create: `frontend/src/lib/pluginCapabilities.ts`
- Create: `frontend/src/__tests__/pluginCapabilities.test.ts`
- Regenerate: `frontend/src/types/api/generated.ts`

- [x] **Step 1: Add types + inspectUpload to the API client**

In `frontend/src/api/modules/plugins.ts`, add the capability type (near the top, after the status types ~line 6):
```typescript
export interface PluginCapability {
  capability: string;
  scope: string[];
  optional: boolean;
  reason: string;
  reason_i18n: Record<string, string>;
}
```
Add to `interface PluginManifest` (~:174):
```typescript
  capabilities: PluginCapability[];
  consented_capabilities?: PluginCapability[] | null;
```
Add to `interface PluginRegistryEntry` (~:310):
```typescript
  capabilities: PluginCapability[];
```
Add a method to `pluginsApi` (near the upload methods ~:469):
```typescript
  inspectUpload: async (file: File): Promise<PluginManifest> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<PluginManifest>('/plugins/install/upload/inspect', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });
    return unwrapPayload(response as PluginManifest | ApiResponse<PluginManifest>);
  },
```

- [x] **Step 2: Write failing vitest for the capability lib**

Create `frontend/src/__tests__/pluginCapabilities.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import {
  capabilityMeta,
  groupCapabilities,
  capabilitiesExceedingConsent,
} from '@/lib/pluginCapabilities';
import type { PluginCapability } from '@/api/modules/plugins';

const cap = (capability: string, scope: string[] = []): PluginCapability => ({
  capability, scope, optional: false, reason: '', reason_i18n: {},
});

describe('capabilityMeta', () => {
  it('maps a known capability to a group', () => {
    expect(capabilityMeta('calendar').group).toBe('system');
    expect(capabilityMeta('network').group).toBe('data');
  });
  it('falls back gracefully for unknown', () => {
    const m = capabilityMeta('future_thing');
    expect(m.group).toBe('data');
    expect(m.known).toBe(false);
  });
});

describe('groupCapabilities', () => {
  it('splits into system and data', () => {
    const g = groupCapabilities([cap('calendar'), cap('network')]);
    expect(g.system.map((c) => c.capability)).toEqual(['calendar']);
    expect(g.data.map((c) => c.capability)).toEqual(['network']);
  });
});

describe('capabilitiesExceedingConsent', () => {
  it('returns [] when declared is a scope-subset of consented', () => {
    const declared = [cap('network', ['a.com'])];
    const consented = [cap('network', ['a.com', 'b.com'])];
    expect(capabilitiesExceedingConsent(declared, consented)).toEqual([]);
  });
  it('flags a new category', () => {
    const out = capabilitiesExceedingConsent([cap('subprocess', ['git'])], [cap('network')]);
    expect(out.map((c) => c.capability)).toEqual(['subprocess']);
  });
  it('flags a new scope entry', () => {
    const out = capabilitiesExceedingConsent([cap('network', ['evil.com'])], [cap('network', ['a.com'])]);
    expect(out.map((c) => c.capability)).toEqual(['network']);
  });
  it('flags broadening specific -> any', () => {
    const out = capabilitiesExceedingConsent([cap('network', [])], [cap('network', ['a.com'])]);
    expect(out.length).toBe(1);
  });
  it('any covered by consented-any', () => {
    expect(capabilitiesExceedingConsent([cap('network', [])], [cap('network', [])])).toEqual([]);
  });
  it('treats null consented as empty (all exceed)', () => {
    expect(capabilitiesExceedingConsent([cap('calendar')], null).length).toBe(1);
  });
});
```

- [x] **Step 3: Run, verify failure**

Run: `cd frontend && npx vitest run src/__tests__/pluginCapabilities.test.ts`
Expected: FAIL (module not found).

- [x] **Step 4: Implement the capability lib**

Create `frontend/src/lib/pluginCapabilities.ts`:
```typescript
import type { PluginCapability } from '@/api/modules/plugins';

export type CapabilityGroup = 'system' | 'data';

export interface CapabilityMeta {
  group: CapabilityGroup;
  icon: string;          // lucide icon name used by the dialog
  i18nKey: string;       // settings.marketplace.capability.<key>
  known: boolean;
}

const KNOWN: Record<string, { group: CapabilityGroup; icon: string }> = {
  screen_recording: { group: 'system', icon: 'Monitor' },
  accessibility: { group: 'system', icon: 'Accessibility' },
  calendar: { group: 'system', icon: 'Calendar' },
  photos: { group: 'system', icon: 'Image' },
  contacts: { group: 'system', icon: 'Users' },
  system_media: { group: 'system', icon: 'Music' },
  filesystem_read: { group: 'data', icon: 'FileText' },
  filesystem_write: { group: 'data', icon: 'FilePen' },
  network: { group: 'data', icon: 'Globe' },
  subprocess: { group: 'data', icon: 'Terminal' },
};

export function capabilityMeta(capability: string): CapabilityMeta {
  const entry = KNOWN[capability];
  if (entry) {
    return { ...entry, i18nKey: `settings.marketplace.capability.${capability}`, known: true };
  }
  return { group: 'data', icon: 'ShieldQuestion', i18nKey: 'settings.marketplace.capability.unknown', known: false };
}

export function groupCapabilities(caps: PluginCapability[]): {
  system: PluginCapability[];
  data: PluginCapability[];
} {
  const system: PluginCapability[] = [];
  const data: PluginCapability[] = [];
  for (const c of caps) {
    (capabilityMeta(c.capability).group === 'system' ? system : data).push(c);
  }
  return { system, data };
}

/** §5.4 coverage rule. Returns the declared capabilities NOT covered by the
 *  consented set (a new category, a new scope entry, or broadening to "any"). */
export function capabilitiesExceedingConsent(
  declared: PluginCapability[],
  consented: PluginCapability[] | null | undefined,
): PluginCapability[] {
  const cons = consented ?? [];
  const isCovered = (c: PluginCapability): boolean => {
    const peers = cons.filter((p) => p.capability === c.capability);
    if (peers.length === 0) return false;
    const cScope = c.scope ?? [];
    if (cScope.length === 0) {
      return peers.some((p) => (p.scope ?? []).length === 0);
    }
    return peers.some((p) => {
      const ps = p.scope ?? [];
      if (ps.length === 0) return true;
      return cScope.every((s) => ps.includes(s));
    });
  };
  return declared.filter((c) => !isCovered(c));
}
```

- [x] **Step 5: Run tests, verify pass**

Run: `cd frontend && npx vitest run src/__tests__/pluginCapabilities.test.ts`
Expected: all PASS.

- [x] **Step 6: Regenerate API types from backend OpenAPI**

Run: `cd frontend && npm run gen:api-types`
Then: `git diff --stat -- src/types/api/generated.ts`
Expected: generated.ts now includes `capabilities` / `consented_capabilities` on the plugin manifest + registry schemas. (CI drift-checks this.)

- [x] **Step 7: Commit**

```bash
cd /Users/asuka/code/magi
git add frontend/src/api/modules/plugins.ts \
        frontend/src/lib/pluginCapabilities.ts \
        frontend/src/__tests__/pluginCapabilities.test.ts \
        frontend/src/types/api/generated.ts
git commit -m "feat(frontend): plugin capability types, category map, consent-diff helper"
```

---

## Task B5: Consent dialog component + marketplace wiring + i18n

**Files:**
- Create: `frontend/src/components/plugins/PluginConsentDialog.tsx`
- Create: `frontend/src/__tests__/PluginConsentDialog.test.tsx`
- Modify: `frontend/src/components/settings/PluginMarketplace.tsx`
- Modify: `frontend/src/i18n/locales/en/app.json`, `frontend/src/i18n/locales/zh-CN/app.json`

- [x] **Step 1: Add i18n strings (en + zh-CN)**

In `frontend/src/i18n/locales/en/app.json`, under `settings.marketplace`, add a `consent` and a `capability` block:
```json
"consent": {
  "title": { "install": "Install \"{{name}}\"?", "update": "Update \"{{name}}\"?", "sideload": "Install \"{{name}}\" from file?" },
  "lede": "This plugin declares it will access:",
  "ledeEmpty": "This plugin declares no special system permissions or data access.",
  "updateNewLede": "This update adds the following access:",
  "groupSystem": "System permissions",
  "groupData": "Data & network access",
  "optionalTag": "optional",
  "confirm": { "install": "Install", "update": "Update" },
  "cancel": "Cancel"
},
"capability": {
  "screen_recording": { "label": "Screen recording", "desc": "Capture images of your screen" },
  "accessibility": { "label": "Accessibility", "desc": "Read the active window and UI" },
  "calendar": { "label": "Calendar", "desc": "Read your calendar and reminders" },
  "photos": { "label": "Photos", "desc": "Access your photo library" },
  "contacts": { "label": "Contacts", "desc": "Read your contacts" },
  "system_media": { "label": "System media", "desc": "Read media playback info" },
  "filesystem_read": { "label": "Read files", "desc": "Read files on your computer" },
  "filesystem_write": { "label": "Write files", "desc": "Write files on your computer" },
  "network": { "label": "Network", "desc": "Connect to the internet" },
  "subprocess": { "label": "Run programs", "desc": "Run other programs on your computer" },
  "unknown": { "label": "Other access", "desc": "An access type this version of Magi doesn't recognize" }
}
```
In `frontend/src/i18n/locales/zh-CN/app.json`, the same keys with zh-CN values:
```json
"consent": {
  "title": { "install": "安装「{{name}}」?", "update": "更新「{{name}}」?", "sideload": "从文件安装「{{name}}」?" },
  "lede": "此插件声明将访问:",
  "ledeEmpty": "此插件未声明需要特殊系统权限或数据访问。",
  "updateNewLede": "本次更新新增了以下访问:",
  "groupSystem": "系统权限",
  "groupData": "数据与网络访问",
  "optionalTag": "可选",
  "confirm": { "install": "安装", "update": "更新" },
  "cancel": "取消"
},
"capability": {
  "screen_recording": { "label": "屏幕录制", "desc": "截取你的屏幕画面" },
  "accessibility": { "label": "辅助功能", "desc": "读取活动窗口与界面" },
  "calendar": { "label": "日历", "desc": "读取你的日历与提醒事项" },
  "photos": { "label": "照片", "desc": "访问你的照片库" },
  "contacts": { "label": "通讯录", "desc": "读取你的通讯录" },
  "system_media": { "label": "系统媒体", "desc": "读取媒体播放信息" },
  "filesystem_read": { "label": "读取文件", "desc": "读取你电脑上的文件" },
  "filesystem_write": { "label": "写入文件", "desc": "在你电脑上写入文件" },
  "network": { "label": "联网", "desc": "连接互联网" },
  "subprocess": { "label": "运行程序", "desc": "在你电脑上运行其它程序" },
  "unknown": { "label": "其它访问", "desc": "当前版本 Magi 不识别的访问类型" }
}
```

- [x] **Step 2: Write failing render test**

Create `frontend/src/__tests__/PluginConsentDialog.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PluginConsentDialog } from '@/components/plugins/PluginConsentDialog';
import type { PluginCapability } from '@/api/modules/plugins';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, o?: any) => o?.name ?? k, i18n: { language: 'en' } }),
}));

const cap = (capability: string): PluginCapability => ({
  capability, scope: [], optional: false, reason: '', reason_i18n: {},
});

describe('PluginConsentDialog', () => {
  it('renders declared capabilities and confirms', () => {
    const onConfirm = vi.fn();
    render(
      <PluginConsentDialog open mode="install" pluginName="Demo" version="1.0.0"
        capabilities={[cap('calendar'), cap('network')]} onConfirm={onConfirm} onCancel={vi.fn()} />,
    );
    expect(screen.getByText('settings.marketplace.capability.calendar.label')).toBeTruthy();
    fireEvent.click(screen.getByText('settings.marketplace.consent.confirm.install'));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('shows the empty-declaration message but still requires confirm', () => {
    render(
      <PluginConsentDialog open mode="install" pluginName="Demo" version="1.0.0"
        capabilities={[]} onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText('settings.marketplace.consent.ledeEmpty')).toBeTruthy();
    expect(screen.getByText('settings.marketplace.consent.confirm.install')).toBeTruthy();
  });
});
```

- [x] **Step 3: Run, verify failure**

Run: `cd frontend && npx vitest run src/__tests__/PluginConsentDialog.test.tsx`
Expected: FAIL (component not found).

- [x] **Step 4: Implement the consent dialog**

Create `frontend/src/components/plugins/PluginConsentDialog.tsx`:
```tsx
import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { PluginCapability } from '@/api/modules/plugins';
import { capabilityMeta, groupCapabilities } from '@/lib/pluginCapabilities';

export type ConsentMode = 'install' | 'update' | 'sideload';

interface Props {
  open: boolean;
  mode: ConsentMode;
  pluginName: string;
  version: string;
  official?: boolean;
  capabilities: PluginCapability[];
  newCapabilities?: PluginCapability[];   // update mode highlight
  onConfirm: () => void;
  onCancel: () => void;
}

function localizedReason(c: PluginCapability, lang: string, fallback: string): string {
  return c.reason_i18n?.[lang] ?? c.reason_i18n?.[lang.split('-')[0]] ?? c.reason || fallback;
}

export const PluginConsentDialog: React.FC<Props> = ({
  open, mode, pluginName, version, capabilities, newCapabilities, onConfirm, onCancel,
}) => {
  const { t, i18n } = useTranslation('app');
  const lang = i18n.language;
  const confirmKey = mode === 'update' ? 'update' : 'install';

  const renderRow = (c: PluginCapability, highlight = false) => {
    const meta = capabilityMeta(c.capability);
    const label = t(`${meta.i18nKey}.label`);
    const desc = localizedReason(c, lang, t(`${meta.i18nKey}.desc`));
    return (
      <div key={`${c.capability}:${c.scope.join(',')}`}
        className={`flex gap-2 py-1.5 ${highlight ? 'rounded-md bg-orange-50 px-2' : ''}`}>
        <div className="min-w-0">
          <div className="text-sm font-medium">
            {label}
            {c.scope.length > 0 && (
              <code className="ml-1.5 text-xs text-muted-foreground">{c.scope.join(', ')}</code>
            )}
            {c.optional && (
              <Badge variant="secondary" className="ml-1.5 text-[10px]">
                {t('settings.marketplace.consent.optionalTag')}
              </Badge>
            )}
          </div>
          <div className="text-xs text-muted-foreground">{desc}</div>
        </div>
      </div>
    );
  };

  const renderGroups = (caps: PluginCapability[]) => {
    const { system, data } = groupCapabilities(caps);
    return (
      <>
        {system.length > 0 && (
          <div>
            <div className="mb-0.5 mt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t('settings.marketplace.consent.groupSystem')}
            </div>
            {system.map((c) => renderRow(c))}
          </div>
        )}
        {data.length > 0 && (
          <div>
            <div className="mb-0.5 mt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t('settings.marketplace.consent.groupData')}
            </div>
            {data.map((c) => renderRow(c))}
          </div>
        )}
      </>
    );
  };

  const isUpdate = mode === 'update' && (newCapabilities?.length ?? 0) > 0;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t(`settings.marketplace.consent.title.${mode}`, { name: pluginName })}
          </DialogTitle>
        </DialogHeader>

        {isUpdate && (
          <div className="mb-1">
            <div className="text-sm font-medium text-orange-700">
              {t('settings.marketplace.consent.updateNewLede')}
            </div>
            {newCapabilities!.map((c) => renderRow(c, true))}
          </div>
        )}

        <div className="text-sm">
          {capabilities.length === 0
            ? t('settings.marketplace.consent.ledeEmpty')
            : t('settings.marketplace.consent.lede')}
        </div>
        {capabilities.length > 0 && renderGroups(capabilities)}

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t('settings.marketplace.consent.cancel')}
          </Button>
          <Button size="sm" onClick={onConfirm}>
            {t(`settings.marketplace.consent.confirm.${confirmKey}`)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PluginConsentDialog;
```
> Verify the named exports `Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle` exist in `frontend/src/components/ui/dialog.tsx`; match the actual export names if they differ.

- [x] **Step 5: Run the dialog test, verify pass**

Run: `cd frontend && npx vitest run src/__tests__/PluginConsentDialog.test.tsx`
Expected: PASS.

- [x] **Step 6: Wire the dialog into PluginMarketplace**

In `frontend/src/components/settings/PluginMarketplace.tsx`:

(a) Add imports:
```typescript
import { PluginConsentDialog, type ConsentMode } from '@/components/plugins/PluginConsentDialog';
import { capabilitiesExceedingConsent } from '@/lib/pluginCapabilities';
import type { PluginCapability } from '@/api/modules/plugins';
```

(b) Add consent-request state (after `installSnapshots` ~:54):
```typescript
  const [consent, setConsent] = useState<{
    mode: ConsentMode;
    name: string;
    version: string;
    official?: boolean;
    capabilities: PluginCapability[];
    newCapabilities?: PluginCapability[];
    proceed: () => Promise<void>;
  } | null>(null);
```

(c) Split `handleInstall`: keep the install body in a private runner, gate it with the dialog:
```typescript
  const runInstall = async (pluginId: string) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: 'installing' }));
    try {
      await pluginsApi.installFromRegistryWithProgress(pluginId, (snapshot) => {
        setInstallSnapshots((prev) => ({ ...prev, [pluginId]: snapshot }));
      });
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n[pluginId]; return n; });
    }
  };

  const handleInstall = (entry: PluginRegistryEntry) => {
    setConsent({
      mode: 'install',
      name: localized(entry.name, entry.name_i18n, i18n.language),
      version: entry.version,
      official: entry.official,
      capabilities: entry.capabilities ?? [],
      proceed: () => runInstall(entry.plugin_id),
    });
  };
```
Update the install button (~:379) `onClick={() => void handleInstall(entry.plugin_id)}` → `onClick={() => handleInstall(entry)}`.

(d) Gate `handleUpdate` with the consent-diff:
```typescript
  const runUpdate = async (pluginId: string) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: 'updating' }));
    try {
      await pluginsApi.updatePluginWithProgress(pluginId, (snapshot) => {
        setInstallSnapshots((prev) => ({ ...prev, [pluginId]: snapshot }));
      });
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.updateSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.updateFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n[pluginId]; return n; });
    }
  };

  const handleUpdate = (entry: PluginRegistryEntry) => {
    const installed = installedPlugins.find((p) => p.manifest.plugin_id === entry.plugin_id);
    const declared = entry.capabilities ?? [];
    const newCaps = capabilitiesExceedingConsent(declared, installed?.manifest.consented_capabilities ?? null);
    if (newCaps.length === 0) {
      void runUpdate(entry.plugin_id);
      return;
    }
    setConsent({
      mode: 'update',
      name: localized(entry.name, entry.name_i18n, i18n.language),
      version: entry.version,
      official: entry.official,
      capabilities: declared,
      newCapabilities: newCaps,
      proceed: () => runUpdate(entry.plugin_id),
    });
  };
```
Update the update button (~:340) `onClick={() => void handleUpdate(entry.plugin_id)}` → `onClick={() => handleUpdate(entry)}`.

(e) Gate `handleUpload` with inspect → consent:
```typescript
  const runUpload = async (file: File) => {
    setProcessingIds((prev) => ({ ...prev, __upload: 'uploading' }));
    try {
      await pluginsApi.installFromUploadWithProgress(file, (snapshot) => {
        setInstallSnapshots((prev) => ({ ...prev, __upload: snapshot }));
      });
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n.__upload; return n; });
    }
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setProcessingIds((prev) => ({ ...prev, __upload: 'uploading' }));
    let manifest;
    try {
      manifest = await pluginsApi.inspectUpload(file);
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: err?.message || 'unknown' }));
      setProcessingIds((prev) => { const n = { ...prev }; delete n.__upload; return n; });
      return;
    }
    setProcessingIds((prev) => { const n = { ...prev }; delete n.__upload; return n; });
    setConsent({
      mode: 'sideload',
      name: manifest.name,
      version: manifest.version,
      capabilities: manifest.capabilities ?? [],
      proceed: () => runUpload(file),
    });
  };
```

(f) Render the dialog at the end of the returned JSX (before the final closing `</div>`):
```tsx
      {consent && (
        <PluginConsentDialog
          open
          mode={consent.mode}
          pluginName={consent.name}
          version={consent.version}
          official={consent.official}
          capabilities={consent.capabilities}
          newCapabilities={consent.newCapabilities}
          onCancel={() => setConsent(null)}
          onConfirm={() => { const p = consent.proceed; setConsent(null); void p(); }}
        />
      )}
```

- [x] **Step 7: Type-check + run frontend tests**

```bash
cd /Users/asuka/code/magi/frontend
npm run type-check
npx vitest run src/__tests__/pluginCapabilities.test.ts src/__tests__/PluginConsentDialog.test.tsx
```
Expected: type-check clean; both test files PASS.

- [x] **Step 8: Commit**

```bash
cd /Users/asuka/code/magi
git add frontend/src/components/plugins/PluginConsentDialog.tsx \
        frontend/src/__tests__/PluginConsentDialog.test.tsx \
        frontend/src/components/settings/PluginMarketplace.tsx \
        frontend/src/i18n/locales/en/app.json \
        frontend/src/i18n/locales/zh-CN/app.json
git commit -m "feat(frontend): install/update/sideload consent dialog wired into the marketplace"
```

---

## Task B6: Phase B verification

- [x] **Step 1: Backend — capability tests + plugins suite**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/test_capability_contracts.py tests/plugins/test_capability_consent.py -v
../.venv/bin/python -m pytest tests/plugins/ -q 2>&1 | tail -15
```
Expected: new tests PASS; no NEW failures (the 7 pre-existing chrome-history discovery failures may remain).

- [x] **Step 2: Frontend — full test + type-check + lint**

```bash
cd /Users/asuka/code/magi/frontend
npm run type-check
npx vitest run src/__tests__/pluginCapabilities.test.ts src/__tests__/PluginConsentDialog.test.tsx
npm run lint 2>&1 | tail -15
```
Expected: type-check clean; tests PASS; lint no new errors on the touched files.

- [x] **Step 3: API-types drift check**

```bash
cd /Users/asuka/code/magi/frontend
npm run gen:api-types
git diff --exit-code -- src/types/api/generated.ts && echo "api types in sync"
```
Expected: `api types in sync` (already committed in B4; regeneration is idempotent).

- [x] **Step 4: Gateway sanity (untouched)**

```bash
cd /Users/asuka/code/magi
cargo test -p magi-gateway 2>&1 | tail -5
```
Expected: `test result: ok` for each binary.

- [x] **Step 5: Status + log**

```bash
cd /Users/asuka/code/magi
git status --short
git log --oneline -6 | cat
```
Expected: clean working tree (only unrelated parallel WIP, if any); Phase B commits present.

---

## Acceptance criteria (mirrors spec §7)

**Phase A (magi-plugins):**
- `build-registry.py` validates capabilities against `KNOWN_CAPABILITIES` (unknown → non-zero exit) and copies declarations into each entry.
- All 14 non-library plugins declare accurate capabilities; `browser_history_core` declares none.
- `registry.json` regenerated; each entry's `capabilities` matches its `plugin.toml`; non-capability fields unchanged.
- `agents.md` documents the convention.

**Phase B (magi):**
- `PluginCapability`/`PluginPermissions` parse; `capability` is permissive `str` (unknown value still parses); `PluginManifest.capabilities` reads from `[plugin.permissions].capabilities`; legacy `declares`/`memory_access` tolerated.
- `PluginRegistryEntryResponse.capabilities` surfaced on `/plugins/registry`; manifest projection carries `capabilities` + `consented_capabilities`.
- Registry install (`install_with_closure`, both paths) and registry update (job + sync route) persist `consented_capabilities = entry.capabilities`.
- `/install/upload/inspect` returns declared capabilities without installing/persisting.
- Frontend: capability category map + `capabilitiesExceedingConsent` (scope-level §5.4 rule); `PluginConsentDialog` (grouped layout B, empty-state still confirms, update highlights new); install/update/sideload all gated; EN + zh-CN strings; generated.ts in sync.
- `pytest tests/plugins/` green (no new failures); frontend vitest + type-check green; `cargo test -p magi-gateway` green.

**Out of scope (per spec §2):** runtime sandbox/enforcement, maintainer curation of capabilities, `memory_access` changes, runtime OS permission-status linkage.
