# Obsidian Vault Sensor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Obsidian-vault Sensor plugin that folds notes into Magi's L1 (full
current-state text) and L2 (entities/relations/assertions with provenance), with folder-based
cognition gating.

**Architecture:** A read-only Sensor plugin in the `magi-plugins` repo, following the
`git_activity` pattern (interval + cursor pull-sync). One `ObsidianVaultSensor` class is
instantiated **twice** — a *knowledge* sensor (`cognition_eligible=True`) over normal folders
and a *search-only* sensor (`cognition_eligible=False`) over reference/clipping folders —
because `SensorMemoryPolicy` is set per-sensor-instance, not per-note. Both share one
`reader.py` (markdown parsing + vault walk). Each changed note becomes one canonical L1 event
(superseded on re-ingest via a stable `source_item_id`); wikilinks/tags feed L2 via
`extract_metadata` and an `ExtractionProfileSpec`.

**Tech Stack:** Python 3.10+, `magi_plugin_sdk` (SensorBase / Plugin / SensorSpec /
ExtensionFieldSpec / ExtractionProfileSpec), pytest + asyncio. No new third-party deps
(minimal hand-rolled frontmatter parser — no PyYAML).

**Working directory for ALL code:** `/Users/asuka/code/magi-plugins/plugins/obsidian-vault/`
**Run tests from:** `/Users/asuka/code/magi-plugins/` with `python3 -m pytest plugins/obsidian-vault/tests/ -v`

**Reference implementation to imitate:** `/Users/asuka/code/magi-plugins/plugins/git_activity/`
(plugin.toml, plugin.py, sensor.py, i18n/en.json) and the test-loader pattern in
`/Users/asuka/code/magi-plugins/plugins/screen_time/tests/test_sensor_occurred_at.py`.

**Spec:** `docs/specs/2026-06-07-obsidian-vault-sensor-design.md` (in the `magi` repo).

---

## Key SDK contracts (verbatim, for reference)

```python
# magi_plugin_sdk.sensors
@dataclass(slots=True)
class SensorSyncContext:
    source_type: str
    manual: bool
    last_cursor: Optional[str]
    last_success_at: Optional[float]
    limit: int
    runtime_paths: PluginRuntimePaths
    plugin_settings: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class SensorSyncResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: Optional[str] = None
    watermark_ts: Optional[float] = None
    stats: dict[str, Any] = field(default_factory=dict)

@dataclass
class SensorOutputMetadata:
    entities: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    fact_hints: list[dict[str, Any]] = field(default_factory=list)
    relation_candidates: list[dict[str, Any]] = field(default_factory=list)

# SensorMemoryPolicy fields: memory_domain, ingest_target, cognition_eligible, tom_depth,
#   retention_class, importance_bias, author_type, content_type

# SensorBase: subclass sets class attrs (sensor_id, source_type, polling_mode,
#   default_interval, supports_pull_sync, update_key_fields, relation_edge_whitelist,
#   memory_policy). MUST implement build_output(item). For pull-sync implement
#   collect_items(context). MAY override extract_metadata(item), source_item_identity(item),
#   source_item_version_fingerprint(item).
# Helpers provided: self._build_output(...), self._build_activity(...),
#   self._build_activity_facet(...), self._build_narration(...), self.t(key, fallback=..., **kw)

# Plugin: configure(manifest, settings); get_sensors() -> list[(sensor_id, sensor, SensorSpec)];
#   get_extraction_profiles() -> list[ExtractionProfileSpec]; self.settings (dict); self.t(...)
```

`self._build_output(*, source_item_id, activity, narration, occurred_at=None,
raw_payload_ref=None, content_blocks=None, tags=None, provenance=None, domain_payload=None)`
returns a `SensorOutput` (it sets `source_type` from `self.source_type`).

---

## File structure

| File | Responsibility |
|---|---|
| `plugin.toml` | Manifest: id, entry, contribution=sensor, default settings, capabilities, suggestion_descriptor, privacy-forward description |
| `__init__.py` | Empty package marker |
| `reader.py` | Pure markdown/vault parsing: `walk_markdown`, `parse_note`, frontmatter/wikilink/tag extraction |
| `sensor.py` | `ObsidianVaultSensor(SensorBase)`: `collect_items`, `build_output`, `extract_metadata`, `source_item_identity`, cursor + folder-tier logic |
| `plugin.py` | `ObsidianVaultPlugin(Plugin)`: `get_sensors` (two instances), `_fields`, `get_extraction_profiles` |
| `i18n/en.json`, `i18n/zh-CN.json` | Plugin-scoped strings (`obsidian-vault.fields.*`, `activity.*`, `content_blocks.*`) |
| `tests/test_reader.py` | Reader parsing + walk tests |
| `tests/test_sensor.py` | `build_output`, `extract_metadata`, `collect_items`, memory-policy variant tests |

---

## Task 1: Scaffold plugin package + manifest

**Files:**
- Create: `plugins/obsidian-vault/__init__.py`
- Create: `plugins/obsidian-vault/plugin.toml`
- Create: `plugins/obsidian-vault/tests/__init__.py`
- Test: `plugins/obsidian-vault/tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manifest.py
from __future__ import annotations
import tomllib
from pathlib import Path


def test_manifest_is_valid_sensor_plugin() -> None:
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "plugin.toml").read_text(encoding="utf-8"))
    plugin = data["plugin"]
    assert plugin["id"] == "obsidian-vault"
    assert plugin["entry_module"] == "plugin"
    assert plugin["entry_class"] == "ObsidianVaultPlugin"
    assert "sensor" in plugin["contribution_types"]
    # Opt-in by default (privacy-forward), like screenshot_timeline.
    assert plugin["default_settings"]["sensors"]["obsidian_vault"]["enabled"] is False
    # Local-only must be declared so the host can render a privacy badge.
    assert plugin["suggestion_descriptor"]["data_locality"] == "local_only"
    # filesystem_read capability must be declared.
    caps = [c["capability"] for c in plugin["permissions"]["capabilities"]]
    assert "filesystem_read" in caps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_manifest.py -v`
Expected: FAIL (FileNotFoundError on `plugin.toml`).

- [ ] **Step 3: Create the package files**

```python
# __init__.py
# (empty — package marker)
```

```python
# tests/__init__.py
# (empty — package marker)
```

```toml
# plugin.toml
[plugin]
id = "obsidian-vault"
name = "Obsidian Vault"
name_i18n = { "zh-CN" = "Obsidian 笔记库" }
version = "0.1.0"
description = "Optional. Reads on-screen-free, on-device markdown notes from an Obsidian vault (wikilinks, tags, frontmatter) so Magi can connect what you write to the rest of your activity. Off by default; notes never leave your device, and you can exclude any folder."
description_i18n = { "zh-CN" = "可选。在本地读取 Obsidian 笔记库的 markdown（含 wikilink、标签、frontmatter），让 Magi 把你写的内容和其他活动连起来。默认关闭；笔记不出本机，任意文件夹都可排除。" }
author = "Magi Team"
entry_module = "plugin"
entry_class = "ObsidianVaultPlugin"
official = true
contribution_types = ["sensor"]
platforms = ["macos", "windows"]

[plugin.default_settings.sensors.obsidian_vault]
enabled = false
vault_path = ""
exclude_folders = [".obsidian", ".trash", "Templates"]
cognition_exclude_folders = ["Clippings", "References"]
sync_interval_minutes = 10
initial_sync_configured = false

[plugin.suggestion_descriptor]
category = "notes"
platform_support = ["darwin", "win32"]
setup_time_estimate_seconds = 20
data_locality = "local_only"

[plugin.suggestion_descriptor.triggers]
intents = []
entities = []

[plugin.suggestion_descriptor.triggers.keywords]
zh = ["笔记", "obsidian", "vault", "记了什么", "写过", "知识库"]
en = ["notes", "obsidian", "vault", "wrote", "knowledge base", "markdown"]

[plugin.suggestion_descriptor.rationale]
zh = "magi 能看到你在笔记里写了什么"
en = "Lets magi see what you write in your notes"

[[plugin.permissions.capabilities]]
capability = "filesystem_read"
reason_i18n = { en = "Read markdown notes from your Obsidian vault", "zh-CN" = "读取你 Obsidian 库中的 markdown 笔记" }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/__init__.py plugins/obsidian-vault/plugin.toml plugins/obsidian-vault/tests/
git commit -m "feat(obsidian-vault): scaffold plugin package + manifest"
```

---

## Task 2: reader.py — parse a single note

**Files:**
- Create: `plugins/obsidian-vault/reader.py`
- Test: `plugins/obsidian-vault/tests/test_reader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reader.py
from __future__ import annotations
from pathlib import Path
import importlib.util


def _load_reader():
    path = Path(__file__).resolve().parents[1] / "reader.py"
    spec = importlib.util.spec_from_file_location("obsidian_reader_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_note_extracts_title_body_tags_links(tmp_path: Path) -> None:
    reader = _load_reader()
    vault = tmp_path
    note = vault / "Projects" / "Magi.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        "title: Magi Project\n"
        "aliases: [Magi, MagiApp]\n"
        "tags: [project, ai]\n"
        "---\n"
        "# Magi Project\n"
        "Working with [[Alex]] on [[Project X|the launch]]. Also #beta work.\n",
        encoding="utf-8",
    )
    parsed = reader.parse_note(note, vault)
    assert parsed["title"] == "Magi Project"
    assert parsed["rel_path"] == "Projects/Magi.md"
    assert "Working with" in parsed["body"]
    assert set(parsed["wikilinks"]) == {"Alex", "Project X"}
    assert set(parsed["aliases"]) == {"Magi", "MagiApp"}
    assert set(parsed["tags"]) == {"project", "ai", "beta"}
    assert parsed["mtime"] == note.stat().st_mtime


def test_parse_note_title_falls_back_to_h1_then_filename(tmp_path: Path) -> None:
    reader = _load_reader()
    note = tmp_path / "Note Without Frontmatter.md"
    note.write_text("# Heading Title\nbody\n", encoding="utf-8")
    assert reader.parse_note(note, tmp_path)["title"] == "Heading Title"

    note2 = tmp_path / "Bare.md"
    note2.write_text("just text, no heading\n", encoding="utf-8")
    assert reader.parse_note(note2, tmp_path)["title"] == "Bare"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_reader.py -v`
Expected: FAIL (`reader.py` not found / `parse_note` undefined).

- [ ] **Step 3: Write reader.py**

```python
# reader.py
"""Pure parsing helpers for an Obsidian vault. No SDK imports — keep testable in isolation."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+?)\]\]")
# Inline #tag: must follow start-of-line or whitespace; allow nested a/b and -, _.
_INLINE_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_][A-Za-z0-9_/\-]*)")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def walk_markdown(vault_root: Path) -> Iterator[Path]:
    """Yield every .md file under the vault, skipping nothing (callers filter folders)."""
    yield from (p for p in vault_root.rglob("*.md") if p.is_file())


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body). Minimal YAML — scalars + inline/block lists only."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fm: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if current_list_key and line.lstrip().startswith("- "):
            fm.setdefault(current_list_key, [])
            fm[current_list_key].append(line.lstrip()[2:].strip().strip("\"'"))
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            current_list_key = key  # block list follows on next lines
            fm[key] = []
        elif value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("\"'") for v in value[1:-1].split(",")]
            fm[key] = [v for v in items if v]
        else:
            fm[key] = value.strip("\"'")
    return fm, body


def _normalize_link_target(raw: str) -> str:
    """`[[Target|alias]]` -> `Target`; strip `#section` and `^block` refs and whitespace."""
    target = raw.split("|", 1)[0]
    target = target.split("#", 1)[0].split("^", 1)[0]
    return target.strip()


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def parse_note(path: Path, vault_root: Path) -> dict[str, Any]:
    """Parse one markdown note into a normalized dict."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = _split_frontmatter(text)

    title = str(fm.get("title") or "").strip()
    if not title:
        m = _H1_RE.search(body)
        title = m.group(1).strip() if m else path.stem

    wikilinks = sorted({_normalize_link_target(m) for m in _WIKILINK_RE.findall(text) if _normalize_link_target(m)})

    tags = set(_as_str_list(fm.get("tags")))
    for raw_tag in _INLINE_TAG_RE.findall(body):
        tags.add(raw_tag.strip())

    rel_path = path.relative_to(vault_root).as_posix()
    uid = str(fm.get("uid") or fm.get("id") or "").strip()

    return {
        "rel_path": rel_path,
        "uid": uid,
        "title": title,
        "body": body.strip(),
        "tags": sorted(tags),
        "wikilinks": wikilinks,
        "aliases": _as_str_list(fm.get("aliases")),
        "frontmatter": fm,
        "mtime": path.stat().st_mtime,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_reader.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/reader.py plugins/obsidian-vault/tests/test_reader.py
git commit -m "feat(obsidian-vault): markdown note parser (frontmatter, wikilinks, tags)"
```

---

## Task 3: reader.py — folder tier classification

**Files:**
- Modify: `plugins/obsidian-vault/reader.py` (add `classify_folder`)
- Test: `plugins/obsidian-vault/tests/test_reader.py` (append)

- [ ] **Step 1: Write the failing test (append to tests/test_reader.py)**

```python
def test_classify_folder_tiers() -> None:
    reader = _load_reader()
    exclude = [".obsidian", "Templates"]
    search_only = ["Clippings", "References"]
    # exclude wins over everything
    assert reader.classify_folder(".obsidian/workspace.md", exclude, search_only) == "exclude"
    assert reader.classify_folder("Templates/Daily.md", exclude, search_only) == "exclude"
    # search-only folders
    assert reader.classify_folder("Clippings/some-article.md", exclude, search_only) == "search"
    assert reader.classify_folder("References/paper.md", exclude, search_only) == "search"
    # everything else is knowledge
    assert reader.classify_folder("Projects/Magi.md", exclude, search_only) == "knowledge"
    assert reader.classify_folder("Daily/2026-06-07.md", exclude, search_only) == "knowledge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_reader.py::test_classify_folder_tiers -v`
Expected: FAIL (`classify_folder` undefined).

- [ ] **Step 3: Add `classify_folder` to reader.py**

```python
def _path_in_folders(rel_path: str, folders: list[str]) -> bool:
    """True if rel_path is inside any of the given top-or-nested folder names."""
    parts = rel_path.split("/")[:-1]  # directory segments only
    folder_set = {f.strip("/").strip() for f in folders if f.strip()}
    return any(seg in folder_set for seg in parts)


def classify_folder(rel_path: str, exclude_folders: list[str], search_only_folders: list[str]) -> str:
    """Return 'exclude' | 'search' | 'knowledge' for a vault-relative note path."""
    if _path_in_folders(rel_path, exclude_folders):
        return "exclude"
    if _path_in_folders(rel_path, search_only_folders):
        return "search"
    return "knowledge"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_reader.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/reader.py plugins/obsidian-vault/tests/test_reader.py
git commit -m "feat(obsidian-vault): folder tier classification (exclude/search/knowledge)"
```

---

## Task 4: sensor.py — `build_output` (note → L1 SensorOutput)

**Files:**
- Create: `plugins/obsidian-vault/sensor.py`
- Test: `plugins/obsidian-vault/tests/test_sensor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sensor.py
from __future__ import annotations
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_sensor_module() -> ModuleType:
    plugin_dir = Path(__file__).resolve().parents[1]
    pkg_name = "obsidian_vault_under_test"
    spec = importlib.util.spec_from_file_location(
        pkg_name, plugin_dir / "__init__.py", submodule_search_locations=[str(plugin_dir)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = package
    spec.loader.exec_module(package)
    sensor_spec = importlib.util.spec_from_file_location(f"{pkg_name}.sensor", plugin_dir / "sensor.py")
    module = importlib.util.module_from_spec(sensor_spec)
    sys.modules[sensor_spec.name] = module
    sensor_spec.loader.exec_module(module)
    return module


def _sample_item() -> dict:
    return {
        "rel_path": "Projects/Magi.md",
        "uid": "",
        "title": "Magi Project",
        "body": "Working with [[Alex]] on the launch. #beta",
        "tags": ["project", "beta"],
        "wikilinks": ["Alex", "Project X"],
        "aliases": ["Magi"],
        "frontmatter": {"title": "Magi Project"},
        "mtime": 1781000000.0,
    }


def test_build_output_maps_note_to_l1_fields() -> None:
    mod = _load_sensor_module()
    sensor = mod.ObsidianVaultSensor(cognition_eligible=True, sensor_suffix="knowledge")
    out = asyncio.run(sensor.build_output(_sample_item()))

    assert out.source_type == "obsidian_vault"
    # Stable id = vault-relative path when no frontmatter uid.
    assert out.source_item_id == "Projects/Magi.md"
    assert out.occurred_at == 1781000000.0
    assert out.narration.title == "Magi Project"
    assert "Working with" in out.narration.body  # full text, not a summary
    assert out.activity.source.code == "obsidian"
    assert out.activity.object is not None and out.activity.object.code == "note"
    assert set(out.tags) == {"project", "beta"}
    assert out.activity.qualifiers["wikilink_count"] == 2


def test_build_output_prefers_frontmatter_uid_for_supersession() -> None:
    mod = _load_sensor_module()
    sensor = mod.ObsidianVaultSensor(cognition_eligible=True, sensor_suffix="knowledge")
    item = _sample_item()
    item["uid"] = "note-uid-123"
    out = asyncio.run(sensor.build_output(item))
    assert out.source_item_id == "note-uid-123"


def test_memory_policy_differs_by_tier() -> None:
    mod = _load_sensor_module()
    knowledge = mod.ObsidianVaultSensor(cognition_eligible=True, sensor_suffix="knowledge")
    search = mod.ObsidianVaultSensor(cognition_eligible=False, sensor_suffix="search")
    assert knowledge.memory_policy.cognition_eligible is True
    assert search.memory_policy.cognition_eligible is False
    # Both are authored + permanent.
    assert knowledge.memory_policy.memory_domain == "user_authored"
    assert knowledge.memory_policy.retention_class == "permanent"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_sensor.py -v`
Expected: FAIL (`sensor.py` not found).

- [ ] **Step 3: Write sensor.py (build_output + class scaffold)**

```python
# sensor.py
"""Obsidian vault timeline sensor."""
from __future__ import annotations

import time
from typing import Any, Optional

from magi_plugin_sdk.sensors import (
    ContentBlock,
    SensorBase,
    SensorMemoryPolicy,
    SensorOutput,
    SensorOutputMetadata,
    SensorSyncContext,
    SensorSyncResult,
)

from .reader import classify_folder, parse_note, walk_markdown
from pathlib import Path


class ObsidianVaultSensor(SensorBase):
    """Pull-sync sensor that ingests Obsidian markdown notes.

    Instantiated twice by the plugin: a ``knowledge`` instance
    (``cognition_eligible=True``) and a ``search`` instance
    (``cognition_eligible=False``). ``SensorMemoryPolicy`` is per-instance, which is
    how the spec's folder-based cognition gating (Option X) is realized.
    """

    source_type = "obsidian_vault"
    polling_mode = "interval"
    default_interval = 10  # minutes
    update_key_fields = ("source_item_id",)
    relation_edge_whitelist = ("REFERENCES", "TAGGED_AS")
    supports_pull_sync = True

    def __init__(
        self,
        *,
        cognition_eligible: bool,
        sensor_suffix: str,
        vault_path: Optional[str] = None,
        exclude_folders: Optional[list[str]] = None,
        cognition_exclude_folders: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self.sensor_id = f"timeline.obsidian_vault.{sensor_suffix}"
        self.display_name = "Obsidian Vault"
        self._tier = sensor_suffix
        self._vault_path = vault_path
        self._exclude_folders = exclude_folders or []
        self._cognition_exclude_folders = cognition_exclude_folders or []
        self.memory_policy = SensorMemoryPolicy(
            memory_domain="user_authored",
            ingest_target="l1_only",
            cognition_eligible=bool(cognition_eligible),
            retention_class="permanent",
            importance_bias=0.6,
            author_type="user",
            content_type="text",
        )

    def source_item_identity(self, item: dict) -> str:
        """Stable id for supersession: frontmatter uid if present, else vault-relative path."""
        uid = str(item.get("uid") or "").strip()
        return uid or str(item.get("rel_path") or "").strip()

    async def build_output(self, item: dict) -> SensorOutput:
        body = str(item.get("body") or "")
        title = str(item.get("title") or "").strip() or None
        tags = [str(t) for t in (item.get("tags") or []) if str(t).strip()]
        wikilinks = [str(w) for w in (item.get("wikilinks") or []) if str(w).strip()]
        mtime = float(item.get("mtime") or time.time())

        content_blocks: list[ContentBlock] = [ContentBlock(kind="text", value=body)]
        content_blocks += [ContentBlock(kind="wikilink", value=w) for w in wikilinks]
        content_blocks += [ContentBlock(kind="tag", value=t) for t in tags]

        return self._build_output(
            source_item_id=self.source_item_identity(item),
            activity=self._build_activity(
                source=self._build_activity_facet(
                    code="obsidian",
                    i18n_key="activity.source.obsidian",
                    fallback="Obsidian",
                    embedding_fallback="Obsidian note",
                ),
                action=self._build_activity_facet(
                    code="edited",
                    i18n_key="activity.action.edited",
                    fallback="edited",
                ),
                object=self._build_activity_facet(
                    code="note",
                    i18n_key="activity.object.note",
                    fallback="note",
                ),
                qualifiers={
                    "word_count": len(body.split()),
                    "wikilink_count": len(wikilinks),
                    "tag_count": len(tags),
                },
            ),
            narration=self._build_narration(title=title, body=body),
            occurred_at=mtime,
            content_blocks=content_blocks,
            tags=tags,
            provenance={
                "sensor_id": self.sensor_id,
                "rel_path": item.get("rel_path"),
                "aliases": item.get("aliases") or [],
            },
            domain_payload={"wikilinks": wikilinks, "tier": self._tier},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_sensor.py -v`
Expected: PASS (3 tests).
NOTE: tests import `magi_plugin_sdk` — ensure the SDK is importable (`pip install -e /Users/asuka/code/magi/sdk` if not already on PYTHONPATH). If import fails, run:
`cd /Users/asuka/code/magi-plugins && PYTHONPATH=/Users/asuka/code/magi/sdk/src python3 -m pytest plugins/obsidian-vault/tests/test_sensor.py -v`

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/sensor.py plugins/obsidian-vault/tests/test_sensor.py
git commit -m "feat(obsidian-vault): sensor build_output + per-tier memory policy"
```

---

## Task 5: sensor.py — `extract_metadata` (wikilinks/tags → structured L2 hints)

**Files:**
- Modify: `plugins/obsidian-vault/sensor.py` (add `extract_metadata`)
- Test: `plugins/obsidian-vault/tests/test_sensor.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_extract_metadata_emits_entities_and_relations() -> None:
    mod = _load_sensor_module()
    sensor = mod.ObsidianVaultSensor(cognition_eligible=True, sensor_suffix="knowledge")
    meta = asyncio.run(sensor.extract_metadata(_sample_item()))

    # The note itself + each wikilink target become entity hints.
    surfaces = {e["surface"] for e in meta.entities}
    assert "Magi Project" in surfaces      # the note
    assert "Alex" in surfaces and "Project X" in surfaces
    assert set(meta.tags) == {"project", "beta"}

    # Each wikilink is a REFERENCES relation candidate from this note.
    preds = {(rc["predicate"], rc["object_ref"]) for rc in meta.relation_candidates}
    assert ("REFERENCES", "Alex") in preds
    assert ("REFERENCES", "Project X") in preds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_sensor.py::test_extract_metadata_emits_entities_and_relations -v`
Expected: FAIL (default `extract_metadata` returns empty `SensorOutputMetadata`).

- [ ] **Step 3: Add `extract_metadata` to ObsidianVaultSensor**

```python
    async def extract_metadata(self, item: dict[str, Any]) -> SensorOutputMetadata:
        """Pre-extract high-confidence structured signals from the note.

        wikilinks -> note entities + REFERENCES relation candidates;
        tags      -> tag list + TAGGED_AS relation candidates.
        These are unambiguous, so they are emitted even though free-prose extraction
        only runs for the knowledge (cognition_eligible) instance.
        """
        title = str(item.get("title") or "").strip()
        note_surface = title or str(item.get("rel_path") or "")
        wikilinks = [str(w) for w in (item.get("wikilinks") or []) if str(w).strip()]
        tags = [str(t) for t in (item.get("tags") or []) if str(t).strip()]

        entities: list[dict[str, Any]] = [
            {
                "surface": note_surface,
                "normalized_name": note_surface,
                "entity_type": "note",
                "alias_signals": list(item.get("aliases") or []),
            }
        ]
        for link in wikilinks:
            entities.append({"surface": link, "normalized_name": link, "entity_type": "note"})

        relation_candidates: list[dict[str, Any]] = []
        for link in wikilinks:
            relation_candidates.append({
                "subject_ref": note_surface,
                "subject_type": "note",
                "predicate": "REFERENCES",
                "object_ref": link,
                "object_type": "note",
                "confidence": 0.95,
            })
        for tag in tags:
            relation_candidates.append({
                "subject_ref": note_surface,
                "subject_type": "note",
                "predicate": "TAGGED_AS",
                "object_ref": tag,
                "object_type": "topic",
                "confidence": 0.95,
            })

        return SensorOutputMetadata(
            entities=entities,
            tags=tags,
            fact_hints=[],
            relation_candidates=relation_candidates,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_sensor.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/sensor.py plugins/obsidian-vault/tests/test_sensor.py
git commit -m "feat(obsidian-vault): structured metadata from wikilinks + tags"
```

---

## Task 6: sensor.py — `collect_items` (scan + tier filter + mtime cursor)

**Files:**
- Modify: `plugins/obsidian-vault/sensor.py` (add `collect_items`, cursor helpers)
- Test: `plugins/obsidian-vault/tests/test_sensor.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def _ctx(mod, vault: Path, last_cursor=None, settings=None):
    return mod_sync_context(mod, vault, last_cursor, settings)


def mod_sync_context(mod, vault: Path, last_cursor, settings):
    # Build a SensorSyncContext with the real SDK dataclass.
    from magi_plugin_sdk.sensors import SensorSyncContext

    class _Paths:
        def plugin_cache_dir(self, plugin_id: str) -> Path:
            return vault
    return SensorSyncContext(
        source_type="obsidian_vault",
        manual=False,
        last_cursor=last_cursor,
        last_success_at=None,
        limit=1000,
        runtime_paths=_Paths(),
        plugin_settings=settings or {},
    )


def test_collect_items_knowledge_tier_skips_search_and_excluded(tmp_path: Path) -> None:
    mod = _load_sensor_module()
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Clippings").mkdir()
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / "Projects" / "A.md").write_text("# A\nbody [[X]]\n", encoding="utf-8")
    (tmp_path / "Clippings" / "C.md").write_text("# C\nclip\n", encoding="utf-8")
    (tmp_path / ".obsidian" / "W.md").write_text("# W\nconfig\n", encoding="utf-8")

    sensor = mod.ObsidianVaultSensor(
        cognition_eligible=True, sensor_suffix="knowledge",
        vault_path=str(tmp_path),
        exclude_folders=[".obsidian"], cognition_exclude_folders=["Clippings"],
    )
    result = asyncio.run(sensor.collect_items(mod_sync_context(mod, tmp_path, None, {})))
    rels = {it["rel_path"] for it in result.items}
    assert rels == {"Projects/A.md"}              # only knowledge-tier note
    assert result.next_cursor is not None


def test_collect_items_incremental_via_cursor(tmp_path: Path) -> None:
    mod = _load_sensor_module()
    (tmp_path / "Projects").mkdir()
    old = tmp_path / "Projects" / "Old.md"
    old.write_text("# Old\nold\n", encoding="utf-8")
    import os
    os.utime(old, (1000.0, 1000.0))  # mtime far in the past

    sensor = mod.ObsidianVaultSensor(
        cognition_eligible=True, sensor_suffix="knowledge",
        vault_path=str(tmp_path), exclude_folders=[], cognition_exclude_folders=[],
    )
    # Cursor newer than the old file -> nothing ingested.
    result = asyncio.run(sensor.collect_items(mod_sync_context(mod, tmp_path, "2000.0", {})))
    assert result.items == []

    # A fresh file (current mtime) is picked up.
    new = tmp_path / "Projects" / "New.md"
    new.write_text("# New\nnew\n", encoding="utf-8")
    result2 = asyncio.run(sensor.collect_items(mod_sync_context(mod, tmp_path, "2000.0", {})))
    assert {it["rel_path"] for it in result2.items} == {"Projects/New.md"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_sensor.py -k collect_items -v`
Expected: FAIL (`collect_items` not implemented — base raises NotImplementedError).

- [ ] **Step 3: Add `collect_items` + cursor helpers to ObsidianVaultSensor**

```python
    def _resolve_settings(self, context: SensorSyncContext) -> dict[str, Any]:
        """Merge constructor defaults with live plugin settings for this sensor."""
        sensors = context.plugin_settings.get("sensors", {})
        live = sensors.get("obsidian_vault", {}) if isinstance(sensors, dict) else {}
        return {
            "vault_path": live.get("vault_path", self._vault_path) or "",
            "exclude_folders": live.get("exclude_folders", self._exclude_folders) or [],
            "cognition_exclude_folders": live.get(
                "cognition_exclude_folders", self._cognition_exclude_folders
            ) or [],
        }

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        settings = self._resolve_settings(context)
        vault_path = str(settings["vault_path"]).strip()
        if not vault_path:
            return SensorSyncResult(items=[], next_cursor=context.last_cursor,
                                    watermark_ts=time.time(),
                                    stats={"count": 0, "error": "no vault_path"})

        vault_root = Path(vault_path).expanduser()
        if not vault_root.is_dir():
            return SensorSyncResult(items=[], next_cursor=context.last_cursor,
                                    watermark_ts=time.time(),
                                    stats={"count": 0, "error": "vault_path not a directory"})

        try:
            since = float(context.last_cursor) if context.last_cursor else 0.0
        except (TypeError, ValueError):
            since = 0.0

        exclude = list(settings["exclude_folders"])
        search_only = list(settings["cognition_exclude_folders"])

        items: list[dict[str, Any]] = []
        max_mtime = since
        scanned = 0
        for path in walk_markdown(vault_root):
            rel = path.relative_to(vault_root).as_posix()
            tier = classify_folder(rel, exclude, search_only)
            if tier == "exclude":
                continue
            if tier != self._tier:
                continue  # this instance only handles its own tier
            mtime = path.stat().st_mtime
            if mtime <= since:
                continue
            scanned += 1
            note = parse_note(path, vault_root)
            note["source_item_id"] = self.source_item_identity(note)
            items.append(note)
            if mtime > max_mtime:
                max_mtime = mtime
            if len(items) >= int(context.limit or 1000):
                break

        items.sort(key=lambda it: float(it.get("mtime") or 0.0), reverse=True)
        return SensorSyncResult(
            items=items,
            next_cursor=str(max_mtime) if max_mtime > 0 else context.last_cursor,
            watermark_ts=max_mtime or time.time(),
            stats={"count": len(items), "tier": self._tier},
        )
```

NOTE: in `__init__`, `self._tier` is set to `sensor_suffix`, so `tier != self._tier` correctly
restricts the knowledge instance to `"knowledge"` notes and the search instance to `"search"`
notes.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_sensor.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/sensor.py plugins/obsidian-vault/tests/test_sensor.py
git commit -m "feat(obsidian-vault): collect_items with tier filter + mtime cursor"
```

---

## Task 7: plugin.py — `ObsidianVaultPlugin` (two sensors + settings + extraction profile)

**Files:**
- Create: `plugins/obsidian-vault/plugin.py`
- Test: `plugins/obsidian-vault/tests/test_plugin.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plugin.py
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path


def _load_plugin_class():
    plugin_dir = Path(__file__).resolve().parents[1]
    pkg = "obsidian_vault_plugin_under_test"
    spec = importlib.util.spec_from_file_location(
        pkg, plugin_dir / "__init__.py", submodule_search_locations=[str(plugin_dir)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[pkg] = package
    spec.loader.exec_module(package)
    pspec = importlib.util.spec_from_file_location(f"{pkg}.plugin", plugin_dir / "plugin.py")
    module = importlib.util.module_from_spec(pspec)
    sys.modules[pspec.name] = module
    pspec.loader.exec_module(module)
    return module.ObsidianVaultPlugin


def _make_plugin(enabled: bool):
    cls = _load_plugin_class()
    plugin = cls()
    plugin.settings = {"sensors": {"obsidian_vault": {
        "enabled": enabled, "vault_path": "/tmp/vault",
        "exclude_folders": [".obsidian"], "cognition_exclude_folders": ["Clippings"],
    }}}
    return plugin


def test_get_sensors_returns_two_tiers_when_enabled() -> None:
    plugin = _make_plugin(enabled=True)
    sensors = plugin.get_sensors()
    ids = {sid for sid, _inst, _spec in sensors}
    assert ids == {"timeline.obsidian_vault.knowledge", "timeline.obsidian_vault.search"}
    cog = {sid: inst.memory_policy.cognition_eligible for sid, inst, _ in sensors}
    assert cog["timeline.obsidian_vault.knowledge"] is True
    assert cog["timeline.obsidian_vault.search"] is False


def test_get_sensors_empty_when_disabled() -> None:
    plugin = _make_plugin(enabled=False)
    assert plugin.get_sensors() == []


def test_extraction_profile_allows_reference_predicates() -> None:
    plugin = _make_plugin(enabled=True)
    profiles = plugin.get_extraction_profiles()
    assert len(profiles) == 1
    prof = profiles[0]
    assert "obsidian_vault" in prof.source_types
    assert "REFERENCES" in prof.allowed_predicates
    assert "TAGGED_AS" in prof.allowed_predicates
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_plugin.py -v`
Expected: FAIL (`plugin.py` not found).

- [ ] **Step 3: Write plugin.py**

```python
# plugin.py
"""Obsidian Vault sensor plugin."""
from __future__ import annotations

from typing import Any

from magi_plugin_sdk import (
    ExtensionFieldSpec,
    ExtractionProfileSpec,
    Plugin,
    SensorSpec,
)

from .sensor import ObsidianVaultSensor

_PREFIX = "sensors.obsidian_vault"

DEFAULT_SETTINGS = {
    "enabled": False,
    "vault_path": "",
    "exclude_folders": [".obsidian", ".trash", "Templates"],
    "cognition_exclude_folders": ["Clippings", "References"],
    "sync_interval_minutes": 10,
    "initial_sync_configured": False,
}


def _fields() -> list[ExtensionFieldSpec]:
    return [
        ExtensionFieldSpec(
            key=f"{_PREFIX}.enabled", type="switch", label="Enabled",
            description="Whether the Obsidian vault sensor is active.",
            default=False, section="general", surface="timeline", order=10,
        ),
        ExtensionFieldSpec(
            key=f"{_PREFIX}.vault_path", type="path", label="Vault Folder",
            description="Path to your Obsidian vault.",
            default="", required=True, section="general", surface="timeline", order=20,
        ),
        ExtensionFieldSpec(
            key=f"{_PREFIX}.exclude_folders", type="tags", label="Excluded Folders",
            description="Folders never read at all (privacy). Defaults skip Obsidian internals.",
            default=[".obsidian", ".trash", "Templates"],
            section="privacy", surface="timeline", order=30,
        ),
        ExtensionFieldSpec(
            key=f"{_PREFIX}.cognition_exclude_folders", type="tags",
            label="Search-only Folders",
            description="Folders read for search but kept out of the knowledge graph "
                        "(e.g. clippings, references).",
            default=["Clippings", "References"],
            section="privacy", surface="timeline", order=40,
        ),
        ExtensionFieldSpec(
            key=f"{_PREFIX}.sync_interval_minutes", type="number",
            label="Sync Interval (minutes)",
            description="How often to rescan the vault for changes.",
            default=10, min=1, max=1440, section="general", surface="timeline", order=50,
        ),
    ]


class ObsidianVaultPlugin(Plugin):
    """Registers two Obsidian vault sensors (knowledge + search-only)."""

    def get_extraction_profiles(self) -> list[ExtractionProfileSpec]:
        return [
            ExtractionProfileSpec(
                profile_id="source.obsidian_vault",
                source_types=["obsidian_vault"],
                allowed_entity_types=["note", "person", "topic", "concept"],
                allowed_predicates=["REFERENCES", "TAGGED_AS", "MENTIONS"],
                structured_allowed_entity_types=["note", "topic"],
                structured_allowed_predicates=["REFERENCES", "TAGGED_AS"],
                allow_graph=True,
                allow_assertion=True,
                extraction_instructions=(
                    "These events are user-authored Obsidian notes.\n"
                    "- Treat [[wikilinks]] as REFERENCES edges between notes/entities.\n"
                    "- Treat #tags as TAGGED_AS topics.\n"
                    "- Extract entities the user clearly writes about (people, projects,\n"
                    "  concepts). Do NOT assert quoted or third-party claims as the user's\n"
                    "  own beliefs."
                ),
            )
        ]

    def get_sensors(self) -> list[tuple[str, Any, SensorSpec]]:
        sensors_cfg = self.settings.get("sensors", {})
        cfg = dict(sensors_cfg.get("obsidian_vault", {})) if isinstance(sensors_cfg, dict) else {}
        if not bool(cfg.get("enabled", DEFAULT_SETTINGS["enabled"])):
            return []

        vault_path = str(cfg.get("vault_path", "")).strip()
        exclude = cfg.get("exclude_folders", DEFAULT_SETTINGS["exclude_folders"])
        search_only = cfg.get("cognition_exclude_folders", DEFAULT_SETTINGS["cognition_exclude_folders"])
        interval = cfg.get("sync_interval_minutes", DEFAULT_SETTINGS["sync_interval_minutes"])

        def _spec(sensor_id: str) -> SensorSpec:
            return SensorSpec(
                sensor_id=sensor_id,
                display_name="Obsidian Vault",
                description="Obsidian vault note ingestion for the timeline.",
                domain="timeline",
                surface="timeline",
                sync_mode="interval",
                polling_mode="interval",
                fields=_fields(),
                metadata={
                    "source_type": "obsidian_vault",
                    "default_settings": dict(DEFAULT_SETTINGS),
                    "sync_interval_minutes": interval,
                },
            )

        result: list[tuple[str, Any, SensorSpec]] = []
        for suffix, cognition in (("knowledge", True), ("search", False)):
            sensor = ObsidianVaultSensor(
                cognition_eligible=cognition,
                sensor_suffix=suffix,
                vault_path=vault_path,
                exclude_folders=list(exclude),
                cognition_exclude_folders=list(search_only),
            )
            result.append((sensor.sensor_id, sensor, _spec(sensor.sensor_id)))
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_plugin.py -v`
Expected: PASS (3 tests).
NOTE: If `ExtractionProfileSpec` rejects unknown kwargs, run the same import in a Python REPL to
confirm the exact field names against `git_activity/plugin.py` (which uses the identical set) and
match them.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/plugin.py plugins/obsidian-vault/tests/test_plugin.py
git commit -m "feat(obsidian-vault): plugin registers knowledge + search sensors + extraction profile"
```

---

## Task 8: i18n — plugin-scoped en + zh-CN strings

**Files:**
- Create: `plugins/obsidian-vault/i18n/en.json`
- Create: `plugins/obsidian-vault/i18n/zh-CN.json`
- Test: `plugins/obsidian-vault/tests/test_i18n.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_i18n.py
from __future__ import annotations
import json
from pathlib import Path


def _leaf_keys(obj, prefix=""):
    out = set()
    for k, v in obj.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _leaf_keys(v, p)
        else:
            out.add(p)
    return out


def test_en_and_zh_have_matching_keys_and_required_namespaces() -> None:
    root = Path(__file__).resolve().parents[1] / "i18n"
    en = json.loads((root / "en.json").read_text(encoding="utf-8"))
    zh = json.loads((root / "zh-CN.json").read_text(encoding="utf-8"))
    assert _leaf_keys(en) == _leaf_keys(zh)
    # Plugin-scoped schema (per the frontend contract): fields live under the plugin id.
    assert "obsidian-vault" in en
    assert "fields" in en["obsidian-vault"]
    # Activity facet i18n keys used by the sensor must resolve.
    assert en["activity"]["source"]["obsidian"]
    assert en["activity"]["object"]["note"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_i18n.py -v`
Expected: FAIL (i18n files not found).

- [ ] **Step 3: Write i18n/en.json and i18n/zh-CN.json**

```json
// i18n/en.json
{
  "obsidian-vault": {
    "name": "Obsidian Vault",
    "description": "Reads markdown notes from your Obsidian vault into Magi's memory.",
    "fields": {
      "vault_path": { "label": "Vault Folder", "description": "Path to your Obsidian vault." },
      "exclude_folders": { "label": "Excluded Folders", "description": "Folders never read at all." },
      "cognition_exclude_folders": { "label": "Search-only Folders", "description": "Read for search but kept out of the knowledge graph." },
      "sync_interval_minutes": { "label": "Sync Interval (minutes)", "description": "How often to rescan the vault." }
    },
    "sections": { "general": "General", "privacy": "Privacy" }
  },
  "activity": {
    "source": { "obsidian": "Obsidian" },
    "action": { "edited": "edited", "created": "created" },
    "object": { "note": "note" }
  },
  "content_blocks": { "note": "Note: {title}" }
}
```

```json
// i18n/zh-CN.json
{
  "obsidian-vault": {
    "name": "Obsidian 笔记库",
    "description": "将 Obsidian 库中的 markdown 笔记读入 Magi 的记忆。",
    "fields": {
      "vault_path": { "label": "库目录", "description": "你的 Obsidian 库路径。" },
      "exclude_folders": { "label": "排除的文件夹", "description": "完全不读取的文件夹。" },
      "cognition_exclude_folders": { "label": "仅搜索文件夹", "description": "可搜索但不进入知识图谱。" },
      "sync_interval_minutes": { "label": "同步间隔（分钟）", "description": "多久重新扫描一次库。" }
    },
    "sections": { "general": "通用", "privacy": "隐私" }
  },
  "activity": {
    "source": { "obsidian": "Obsidian" },
    "action": { "edited": "编辑", "created": "新建" },
    "object": { "note": "笔记" }
  },
  "content_blocks": { "note": "笔记：{title}" }
}
```

(Strip the `//` comment lines — they are not valid JSON; they only label the blocks here.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/tests/test_i18n.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/obsidian-vault/i18n/
git commit -m "feat(obsidian-vault): plugin-scoped i18n (en + zh-CN)"
```

---

## Task 9: Full-suite green + manifest/extraction-profile field-name validation

**Files:** (no new files; verification + any fixes)

- [ ] **Step 1: Run the whole plugin suite**

Run: `cd /Users/asuka/code/magi-plugins && python3 -m pytest plugins/obsidian-vault/ -v`
Expected: ALL PASS (manifest, reader×3, sensor×6, plugin×3, i18n×1).
If `magi_plugin_sdk` import fails, prefix with `PYTHONPATH=/Users/asuka/code/magi/sdk/src`.

- [ ] **Step 2: Validate plugin loads through the real host loader (smoke)**

Run (from the `magi` backend, which knows how to discover plugins):
`cd /Users/asuka/code/magi/backend && PYTHONPATH=src python3 -c "from magi.plugins.manager import *  # noqa"`
Then locate the discovery entry point used in `backend/src/magi/plugins/manager.py` and confirm
`obsidian-vault` is discovered when placed under a configured search path
(`~/.magi/plugins` or the repo `plugins/` dir). Document the exact command you used.
Expected: the plugin manifest parses and `ObsidianVaultPlugin` imports without error.
If discovery requires the plugin under `~/.magi/plugins/`, copy it there:
`cp -R /Users/asuka/code/magi-plugins/plugins/obsidian-vault ~/.magi/plugins/`
(Per project memory: source → installed copies do NOT auto-sync.)

- [ ] **Step 3: Confirm SDK field names actually exist**

For each SDK type used (`ExtractionProfileSpec`, `ExtensionFieldSpec`, `SensorSpec`,
`SensorMemoryPolicy`), open the SDK source and confirm every kwarg in this plan matches a real
field. `SensorMemoryPolicy` fields to verify: `memory_domain, ingest_target, cognition_eligible,
retention_class, importance_bias, author_type, content_type`. Fix any mismatch inline and re-run.
Run: `cd /Users/asuka/code/magi && rg -n "class SensorMemoryPolicy" -A 20 sdk/src/magi_plugin_sdk/sensors.py`

- [ ] **Step 4: Commit any fixes**

```bash
cd /Users/asuka/code/magi-plugins
git add -A plugins/obsidian-vault
git commit -m "test(obsidian-vault): full suite green + SDK field validation"
```

---

## Self-review notes (author)

- **Spec coverage:** §4 flow → Tasks 4/6; §5 L1 mapping → Task 4; §6 supersession (`source_item_id`)
  → Task 4 (`source_item_identity`) + Task 6 (`update_key_fields`); §7 Option X gating →
  Tasks 6–7 (two sensors, tier filter); §8 structured L2 + provenance → Task 5 +
  ExtractionProfileSpec (Task 7); §9 sync interval+cursor → Task 6; §10 settings/permissions/i18n
  → Tasks 1/7/8; §11 privacy framing → Task 1 manifest description + `data_locality`.
- **Deferred (per spec non-goals):** deletion/rename reconciliation, real-time watcher, Tool
  contribution, Option Y `structured_only` mode — intentionally NOT in this plan.
- **Risk to verify during execution:** exact SDK field names (Task 9 Step 3) and the host's
  per-sensor cursor storage (two same-`source_type` sensors must get independent cursors keyed by
  `sensor_id`). Confirm against `backend/src/magi/plugins/manager.py` during Task 9 Step 2.
```
