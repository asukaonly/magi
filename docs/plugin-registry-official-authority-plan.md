# Plugin Registry `official` Authority Implementation Plan

**Status:** Complete — the maintainer allowlist and app-side authority rules shipped.

> Historical execution record: every task below is complete; the checked steps preserve the rollout and its validation sequence.

**Goal:** Make the registry the sole authority for a plugin's `official` flag — a maintainer-controlled allowlist in `magi-plugins` decides it, and the `magi` app never trusts a non-builtin plugin's self-declared `official` from its local manifest.

**Architecture:** `magi-plugins` gains an `official-plugins.json` allowlist; `build-registry.py` derives each entry's `official` from allowlist membership (ignoring `plugin.toml` self-declaration). `magi` adds an `official` field to the persisted per-plugin config, populates it from the registry entry at install (builtin keeps its bundled manifest value; sideload is always False), and routes the two installed-plugin projections through a helper that reads the authoritative value for non-builtin plugins.

**Tech Stack:** Python (build-registry.py, pydantic config models, plugin manager), JSON allowlist, GitHub CODEOWNERS, pytest.

**Spec reference:** `docs/plugin-registry-official-authority-design.md` (committed `701cd479`).

**Two repos, two phases:**
- **Phase A** (Tasks 1-3) — `/Users/asuka/code/magi-plugins`: allowlist + generator authority + CODEOWNERS. Migration is behavior-neutral (registry.json unchanged).
- **Phase B** (Tasks 4-5) — `/Users/asuka/code/magi`: config field + install-time persist + projection helper. Tests are local (no network).

---

## File Structure

| Path | Repo | Action | Responsibility |
|------|------|--------|----------------|
| `official-plugins.json` | magi-plugins | Create | Maintainer-only allowlist of official plugin_ids |
| `scripts/build-registry.py` | magi-plugins | Modify | Derive `official` from allowlist, ignore self-declaration |
| `.github/CODEOWNERS` | magi-plugins | Create/modify | Gate the allowlist behind maintainer review |
| `agents.md` | magi-plugins | Modify | Document the allowlist authority |
| `backend/src/magi/config/plugin_models.py` | magi | Modify | Add `official` to `PluginSettings` |
| `backend/src/magi/api/routers/plugins_common.py` | magi | Modify | `_authoritative_official` helper + wire 2 sites |
| `backend/src/magi/plugins/manager.py` | magi | Modify | Persist `official` at scan (default) |
| (install-from-registry path) | magi | Modify | Persist registry `entry.official` at install |
| `backend/tests/plugins/test_official_authority.py` | magi | Create | Unit tests for the helper + persistence |

---

# PHASE A — magi-plugins (allowlist authority)

All Phase A tasks run from `/Users/asuka/code/magi-plugins`.

## Task 1: Allowlist file + build-registry.py authority

**Files:**
- Create: `official-plugins.json`
- Modify: `scripts/build-registry.py`

- [x] **Step 1: Capture the current official set (migration baseline)**

```bash
cd /Users/asuka/code/magi-plugins
python3 -c "
import json
data = json.load(open('registry.json'))
ids = sorted(p['plugin_id'] for p in data['plugins'] if p.get('official'))
print(json.dumps({'official_plugin_ids': ids}, indent=2, ensure_ascii=False))
" > official-plugins.json
cat official-plugins.json
```
Expected: a JSON object with `official_plugin_ids` listing every plugin_id currently marked `official: true`. This seeds the allowlist so regeneration produces an unchanged registry.json (behavior-neutral migration).

- [x] **Step 2: Read the current build-registry.py official line**

```bash
grep -n "official" /Users/asuka/code/magi-plugins/scripts/build-registry.py
```
Expected: `entry["official"] = meta.get("official", False)` (around line 42). Note the surrounding `build_entry(plugin_dir)` function signature and the `meta = data.get("plugin", {})` line above it.

- [x] **Step 3: Add allowlist loading + change the official derivation**

In `scripts/build-registry.py`, near the top (after the `REGISTRY_PATH` constant), add a loader (the module already imports `json`):

```python
OFFICIAL_ALLOWLIST_PATH = REPO_ROOT / "official-plugins.json"


def load_official_ids() -> set[str]:
    """Maintainer-controlled set of plugin_ids allowed to be `official`.

    Authority for the `official` flag lives here, NOT in each plugin's
    plugin.toml — a third-party PR touching only plugins/<their-plugin>/
    cannot grant itself official status.
    """
    if not OFFICIAL_ALLOWLIST_PATH.exists():
        return set()
    with open(OFFICIAL_ALLOWLIST_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data.get("official_plugin_ids", []))
```

Then thread `official_ids` into `build_entry`. Change `build_entry(plugin_dir)` to `build_entry(plugin_dir, official_ids)`, and replace the official line:

```python
    plugin_id = meta.get("id", plugin_dir.name)
    # ... existing entry["plugin_id"] = plugin_id assignment uses the same value ...
    self_declared = bool(meta.get("official", False))
    entry["official"] = plugin_id in official_ids
    if self_declared and not entry["official"]:
        print(
            f"  ! {plugin_id}: plugin.toml self-declares official=true but is "
            f"not in official-plugins.json — ignored (allowlist is authoritative)"
        )
```

In `main()`, load the ids once and pass them: `official_ids = load_official_ids()` then `entry = build_entry(child, official_ids)`.

> Note: `entry["plugin_id"]` is already computed as `meta.get("id", plugin_dir.name)` in the existing code — reuse that exact expression for the allowlist membership test so the id matching is consistent (e.g. `calendar_plugin/` dir → `calendar` id).

- [x] **Step 4: Regenerate registry.json and verify it is UNCHANGED**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/build-registry.py
# The registry uses a two-step pipeline (see #1 supply-chain CI note):
python scripts/gen_registry.py
git diff --exit-code -- registry.json && echo "MIGRATION NEUTRAL: registry.json unchanged"
```
Expected: `MIGRATION NEUTRAL: registry.json unchanged`. If registry.json changed, the allowlist seed (Step 1) does not match the current official set — investigate before committing (a diff here means behavior would change for some plugin's badge).

- [x] **Step 5: Verify the authority actually flips a self-declared plugin**

```bash
cd /Users/asuka/code/magi-plugins
# Pick any plugin NOT in the allowlist and temporarily self-declare official:
python3 - <<'PY'
import json, pathlib, re
# find a plugin dir not in allowlist
allow = set(json.load(open("official-plugins.json"))["official_plugin_ids"])
import tomllib
for d in sorted(pathlib.Path("plugins").iterdir()):
    t = d / "plugin.toml"
    if not t.exists():
        continue
    meta = tomllib.load(open(t, "rb")).get("plugin", {})
    pid = meta.get("id", d.name)
    if pid not in allow:
        print("NON-OFFICIAL test target:", pid, "dir:", d.name)
        break
PY
```
Take the printed dir, temporarily append `official = true` under its `[plugin]` table, run `python scripts/build-registry.py`, and confirm it prints the `! ... ignored` warning AND that the regenerated registry entry for it has `official: false`. Then revert the plugin.toml edit (`git checkout -- plugins/<dir>/plugin.toml`) and re-run build-registry + gen_registry so registry.json is clean again.

- [x] **Step 6: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git checkout -- registry.json 2>/dev/null  # ensure no stray test diff
python scripts/build-registry.py && python scripts/gen_registry.py
git add official-plugins.json scripts/build-registry.py
# registry.json should be unchanged; add it only if it legitimately changed
git status --short
git commit -m "feat(registry): make official-plugins.json the authority for the official flag"
```

---

## Task 2: CODEOWNERS + docs

**Files:**
- Create/modify: `.github/CODEOWNERS`
- Modify: `agents.md`

- [x] **Step 1: Check for an existing CODEOWNERS**

```bash
ls /Users/asuka/code/magi-plugins/.github/CODEOWNERS 2>/dev/null && cat /Users/asuka/code/magi-plugins/.github/CODEOWNERS || echo "(none)"
```

- [x] **Step 2: Add the allowlist ownership rule**

Create or append to `/Users/asuka/code/magi-plugins/.github/CODEOWNERS`:

```
# The official-plugins allowlist is the authority for the `official` trust
# badge. Changes require maintainer review (enable "Require review from
# Code Owners" in branch protection for this to be enforced).
/official-plugins.json   @asukaonly
```

(If a CODEOWNERS already exists, append only the comment + the `/official-plugins.json` line; don't disturb existing rules.)

- [x] **Step 3: Document in agents.md**

In `/Users/asuka/code/magi-plugins/agents.md`, under the "Quick Rules (Do / Don't)" `**Don't**` list, add:

```markdown
- Don't set `official = true` in a plugin's `plugin.toml` expecting a badge — the `official` flag is derived solely from `official-plugins.json` (maintainer-controlled). Self-declared values are ignored.
```

And under `**Do**`:

```markdown
- To mark a plugin official, add its `plugin_id` to `official-plugins.json` (maintainer-gated via CODEOWNERS), then regenerate the registry.
```

- [x] **Step 4: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add .github/CODEOWNERS agents.md
git commit -m "docs(registry): gate official-plugins.json via CODEOWNERS; document authority"
```

---

## Task 3: Phase A verification

- [x] **Step 1: Registry neutral, allowlist authoritative, CI green**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/build-registry.py && python scripts/gen_registry.py
git diff --exit-code -- registry.json && echo "registry neutral"
python3 -c "import json; print('allowlist size:', len(json.load(open('official-plugins.json'))['official_plugin_ids']))"
git status --short
git log --oneline -3 | cat
```
Expected: `registry neutral`, the allowlist size printed, clean working tree, and the two Phase A commits in the log.

---

# PHASE B — magi (consume authoritatively)

All Phase B tasks run from `/Users/asuka/code/magi`. Use `../.venv/bin/python -m pytest` from `backend/`.

## Task 4: Config field + persist + projection helper

**Why one task:** the config field, its persistence at install/scan, and the projection helper that reads it are coupled — a helper reading a field that nothing populates would under-badge every official plugin. They land together so no intermediate commit regresses badges.

**Files:**
- Modify: `backend/src/magi/config/plugin_models.py` (`PluginSettings`, line ~10-17)
- Modify: `backend/src/magi/plugins/manager.py` (`_persist_new_packages`, the block at ~680-695)
- Modify: `backend/src/magi/api/routers/plugins_common.py` (helper + projection sites at ~115 and ~565 + the registry-install persist at ~390-393)
- Test: `backend/tests/plugins/test_official_authority.py` (create)

The registry-install persist point is already pinned: `plugins_common.py:390-393` builds a `package_config` dict and calls `save_config({f"plugins.packages.{entry.plugin_id}": package_config})` with the `PluginRegistryEntry` (`entry`) in hand. That's where `entry.official` gets persisted — same file as the helper and projection sites, so this whole task is one file plus config + manager + test.

- [x] **Step 1: Read the exact integration sites first**

```bash
cd /Users/asuka/code/magi
sed -n '8,20p' backend/src/magi/config/plugin_models.py
sed -n '676,696p' backend/src/magi/plugins/manager.py
sed -n '110,120p;385,397p;556,568p' backend/src/magi/api/routers/plugins_common.py
```
Confirm: (a) `PluginSettings` fields and that `Optional`/`Field` are imported; (b) the `_persist_new_packages` else/library branches; (c) the three plugins_common sites — the two projection responses (`official=manifest.official` ~115, `official=m.official` ~565) and the registry-install `package_config` / `save_config` block (~390-393).

- [x] **Step 2: Write failing tests**

Create `backend/tests/plugins/test_official_authority.py`:

```python
from magi.config.plugin_models import PluginSettings
from magi.api.routers.plugins_common import _authoritative_official


class _FakeManifest:
    def __init__(self, plugin_id, source, official):
        self.plugin_id = plugin_id
        self.source = source
        self.official = official


def _cfg_with(plugin_id, official):
    # Minimal stand-in for config.plugins.packages[plugin_id]
    return {plugin_id: PluginSettings(official=official)}


def test_builtin_trusts_its_manifest_official(monkeypatch):
    m = _FakeManifest("core-tools", "builtin", True)
    # builtin path ignores config; reads manifest
    assert _authoritative_official(m, packages={}) is True


def test_non_builtin_reads_persisted_official_true(monkeypatch):
    m = _FakeManifest("calendar", "external", False)  # manifest says false
    pkgs = _cfg_with("calendar", True)                 # registry persisted true
    assert _authoritative_official(m, packages=pkgs) is True


def test_non_builtin_ignores_forged_manifest_official(monkeypatch):
    m = _FakeManifest("evil", "external", True)        # forged self-declare
    pkgs = _cfg_with("evil", False)                    # registry says false
    assert _authoritative_official(m, packages=pkgs) is False


def test_non_builtin_missing_config_defaults_false(monkeypatch):
    m = _FakeManifest("legacy", "external", True)       # forged
    assert _authoritative_official(m, packages={}) is False  # no persisted entry


def test_plugin_settings_has_official_field():
    s = PluginSettings(official=True)
    assert s.official is True
    assert PluginSettings().official is None  # default: unknown
```

> The helper signature here takes `packages` explicitly for testability. The two projection call sites will pass `get_config().plugins.packages`.

- [x] **Step 3: Run, verify failure**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/test_official_authority.py -v
```
Expected: FAIL — `PluginSettings` has no `official`, `_authoritative_official` doesn't exist.

- [x] **Step 4: Add `official` to `PluginSettings`**

In `backend/src/magi/config/plugin_models.py`, in `class PluginSettings`, after `manifest_path`:

```python
    official: Optional[bool] = Field(
        default=None,
        description="Registry-authoritative official flag for non-builtin "
        "plugins; None means unknown (treated as non-official).",
    )
```

(Confirm `Optional` and `Field` are already imported in that file; they are used by the existing fields.)

- [x] **Step 5: Add the projection helper**

In `backend/src/magi/api/routers/plugins_common.py`, add near the top (after imports):

```python
def _authoritative_official(manifest, *, packages) -> bool:
    """Resolve a plugin's official status from the authoritative source.

    builtin plugins are bundled in the app binary, so their manifest is
    trusted. For every other source the local manifest is attacker-authored
    and MUST NOT be trusted — official comes from the registry value
    persisted into config at install time (None/missing → not official).
    """
    if getattr(manifest, "source", None) == "builtin":
        return bool(getattr(manifest, "official", False))
    entry = packages.get(getattr(manifest, "plugin_id", None))
    return bool(getattr(entry, "official", None)) if entry is not None else False
```

- [x] **Step 6: Wire the two projection sites**

At `plugins_common.py:~115`, change `official=manifest.official,` to:
```python
        official=_authoritative_official(manifest, packages=get_config().plugins.packages),
```
At `plugins_common.py:~565`, change `official=m.official,` to:
```python
            official=_authoritative_official(m, packages=get_config().plugins.packages),
```
(Confirm `get_config` is imported in this module; if not, add `from magi.config import get_config` — match the existing import style in the file.)

- [x] **Step 7: Persist official at scan (conservative default)**

In `manager.py` `_persist_new_packages`, the `updates[f"plugins.packages.{plugin_id}.*"]` assignments sit AFTER the `if/else` that computes `enabled`/`trusted`, so they run for both the library and non-library branches. Add one more shared line in that block (next to the existing `enabled`/`trusted`/`source`/`manifest_path` assignments):

```python
            updates[f"plugins.packages.{plugin_id}.official"] = (
                bool(manifest.official) if manifest.source == "builtin" else False
            )
```
This gives builtin its bundled `manifest.official`, and everything else (library + external) a conservative `False` — the registry-install path (Step 8) overwrites the external case with the authoritative value when applicable.

- [x] **Step 8: Persist registry official at install**

At `plugins_common.py:390-393`, the registry install builds `package_config` then saves it. Add the registry's `official` to that dict before the `save_config` call:

```python
    package_config: dict[str, Any] = {"enabled": True}
    if is_library:
        package_config["trusted"] = True
    package_config["official"] = bool(entry.official)   # registry is authoritative
    save_config({f"plugins.packages.{entry.plugin_id}": package_config})
```
Invariant: after a registry install, `config.plugins.packages[plugin_id].official == entry.official`. (Libraries get `entry.official` too, but they're never shown as official badges and the projection treats library/non-builtin uniformly — fine.)

- [x] **Step 9: Run the tests, verify pass**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/test_official_authority.py -v
```
Expected: all 5 tests PASS.

- [x] **Step 10: Commit**

```bash
cd /Users/asuka/code/magi
git add backend/src/magi/config/plugin_models.py \
        backend/src/magi/api/routers/plugins_common.py \
        backend/src/magi/plugins/manager.py \
        backend/tests/plugins/test_official_authority.py
git commit -m "feat(plugins): registry is authoritative for official; ignore non-builtin manifest self-declaration"
```

---

## Task 5: Phase B verification

- [x] **Step 1: Targeted + full plugin suite**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/test_official_authority.py -v
../.venv/bin/python -m pytest tests/plugins/ -q 2>&1 | tail -15
```
Expected: the 5 new tests pass. For the full dir: the 7 pre-existing `test_chrome_history_plugin.py` discovery failures (documented in the supply-chain work, unrelated to this change) may remain; NO new failures introduced by this task. If any other test breaks because it asserted `official` from a non-builtin manifest, update it to the authoritative path and note it.

- [x] **Step 2: Gateway sanity (untouched)**

```bash
cd /Users/asuka/code/magi
cargo test -p magi-gateway 2>&1 | tail -5
```
Expected: `test result: ok` for each binary.

- [x] **Step 3: Status + log**

```bash
cd /Users/asuka/code/magi
git status --short
git log --oneline -3 | cat
```
Expected: clean working tree (only unrelated parallel work, if any); the Phase B commit present.

---

## Acceptance criteria (mirrors spec §7)

**Phase A (magi-plugins):**
- `official-plugins.json` exists, seeded from the current official set.
- `build-registry.py` derives `official` from the allowlist; a self-declared `official=true` outside the allowlist is ignored (+ warning) and yields `official:false`.
- Regenerated `registry.json` is byte-unchanged vs pre-migration (behavior-neutral).
- `.github/CODEOWNERS` gates `official-plugins.json`; `agents.md` documents the rule.

**Phase B (magi):**
- `PluginSettings.official` exists (default None).
- A non-builtin installed plugin with a forged `manifest.official=true` projects `official=false` unless the registry persisted true.
- builtin keeps trusting its bundled manifest; sideload is always False; legacy installs (no persisted official) default to False.
- `pytest tests/plugins/test_official_authority.py` green; no new failures in `tests/plugins/`; `cargo test -p magi-gateway` green.

**Out of scope (per spec §2):** plugin-content hash pinning, registry signing, `author`-field treatment, sandbox.
