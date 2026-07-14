# Plugin Supply-Chain Locking Implementation Plan

**Status:** Complete — lock generation, drift CI, and hash-enforced installation shipped.

> Historical execution record: every task below is complete; the checked steps preserve the rollout and its validation sequence.

**Goal:** Pin every plugin's Python dependency closure to exact versions + sha256 hashes, generated in `magi-plugins` and enforced at install time in `magi` via `pip install --require-hashes`, so a poisoned upstream package or compromised mirror is caught before it lands.

**Architecture:** `magi-plugins` repo grows a `scripts/lock-deps.py` (wraps `uv pip compile --universal --generate-hashes --exclude-newer`) that writes per-plugin `requirements.lock`, plus its first CI workflow that drift-checks those locks. `magi` repo's `installation.py` switches dependency installation to `--require-hashes -r requirements.lock`, refuses to install a plugin that declares deps but ships no lock (with a `MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS` developer escape hatch), and keeps passing no `--index-url` so user mirror config still works.

**Tech Stack:** `uv` (build-time lock generation, `--universal` cross-platform single-pass resolution), `pip --require-hashes` (install-time integrity enforcement), GitHub Actions (drift CI), pytest (magi backend tests).

**Spec reference:** `docs/plugin-supply-chain-locking-design.md` (committed `30730930`).

**Two repos, two phases:**
- **Phase A** (Tasks 1-5) — `/Users/asuka/code/magi-plugins`: generate locks + CI. Ships and tests independently.
- **Phase B** (Tasks 6-9) — `/Users/asuka/code/magi`: enforce at install. Tests with synthetic fixtures, no dependency on Phase A being checked out.

**Refinement over spec (§8):** the spec did not address CI drift flapping when an upstream transitive dep publishes a new version. This plan pins resolution with `uv --exclude-newer <frozen-timestamp>` stored as a constant in `lock-deps.py`, making the drift check deterministic and turning version adoption into a deliberate act (bump the constant, re-run). This is a strict improvement consistent with the spec's supply-chain-security intent.

**Prerequisite / possible blocker:** Tasks 1-4 run `uv pip compile` against PyPI (network required). If the execution environment cannot reach PyPI (or the requested mirror), those tasks must report BLOCKED rather than committing a partial/empty lock.

---

## File Structure

| Path | Repo | Action | Responsibility |
|------|------|--------|----------------|
| `scripts/lock-deps.py` | magi-plugins | Create | Generate/check per-plugin `requirements.lock` from `plugin.toml` deps |
| `plugins/<id>/requirements.lock` (×6) | magi-plugins | Create | Pinned dep closure + hashes (committed) |
| `.github/workflows/ci.yml` | magi-plugins | Create | Drift-check lockfiles + registry.json |
| `README.md` / `agents.md` | magi-plugins | Modify | Document `uv` + regenerate workflow |
| `backend/src/magi/plugins/installation.py` | magi | Modify | `--require-hashes` install + no-lock policy |
| `backend/tests/plugins/test_plugin_dependency_locking.py` | magi | Create | Unit + integration tests for the new install behavior |

The 6 plugins that declare `dependencies` and therefore get a lockfile: `calendar_plugin`, `screen_time`, `system_media`, `screenshot_timeline`, `telegram`, `weixin`.

---

# PHASE A — magi-plugins (generate + CI)

All Phase A tasks run from `/Users/asuka/code/magi-plugins`.

## Task 1: Write `scripts/lock-deps.py`

**Files:**
- Create: `/Users/asuka/code/magi-plugins/scripts/lock-deps.py`

- [x] **Step 1: Confirm uv is available**

Run:
```bash
which uv || pip install uv
uv --version
```
Expected: a version line (e.g. `uv 0.5.x`). If `pip install uv` is needed, that's fine — it's a build-time tool.

- [x] **Step 2: Write the script**

Create `/Users/asuka/code/magi-plugins/scripts/lock-deps.py`:

```python
#!/usr/bin/env python3
"""Generate per-plugin requirements.lock from plugin.toml dependencies.

Uses `uv pip compile --universal --generate-hashes` so one lockfile covers
all target platforms (macOS + Windows) and pins every dependency
(top-level + transitive) to an exact version + sha256 hash.

Resolution is frozen with `--exclude-newer EXCLUDE_NEWER` so re-running is
deterministic: an upstream release does not silently change the lock and
does not flap CI. To adopt newer versions, bump EXCLUDE_NEWER and re-run.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[import-untyped,no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

# Bundled plugin runtime version (python-build-standalone) shipped by the
# main app. Keep in sync with MAGI_PLUGIN_PYTHON_VERSION in the magi repo.
PYTHON_VERSION = "3.13"

# Freeze dependency resolution at this instant. Bump deliberately to adopt
# newer upstream releases; never auto-follow. See module docstring.
EXCLUDE_NEWER = "2026-05-31T00:00:00Z"

LOCK_HEADER = (
    "# This file is auto-generated by scripts/lock-deps.py. Do not edit.\n"
    "# Regenerate with: python scripts/lock-deps.py <plugin_dir_name>\n"
)


def read_dependencies(plugin_dir: Path) -> list[str]:
    toml_path = plugin_dir / "plugin.toml"
    if not toml_path.exists():
        return []
    with open(toml_path, "rb") as fh:
        data = tomllib.load(fh)
    deps = data.get("plugin", {}).get("dependencies", [])
    return [str(dep) for dep in deps]


def compile_lock(dependencies: list[str]) -> str:
    reqs_text = "\n".join(dependencies) + "\n"
    cmd = [
        "uv", "pip", "compile",
        "--universal",
        "--generate-hashes",
        "--python-version", PYTHON_VERSION,
        "--exclude-newer", EXCLUDE_NEWER,
        "--no-header",
        "-",  # read requirements from stdin
    ]
    result = subprocess.run(
        cmd, input=reqs_text, capture_output=True, text=True, check=True
    )
    return LOCK_HEADER + result.stdout


def lock_path_for(plugin_dir: Path) -> Path:
    return plugin_dir / "requirements.lock"


def iter_plugin_dirs(only: str | None) -> list[Path]:
    if only:
        target = PLUGINS_DIR / only
        if not target.is_dir():
            raise SystemExit(f"No plugin directory named: {only}")
        return [target]
    return [d for d in sorted(PLUGINS_DIR.iterdir()) if d.is_dir()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", nargs="?", help="Limit to this plugin dir name")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if any lockfile is stale or missing",
    )
    args = parser.parse_args()

    drift = False
    for plugin_dir in iter_plugin_dirs(args.plugin):
        deps = read_dependencies(plugin_dir)
        lock_file = lock_path_for(plugin_dir)

        if not deps:
            # No declared deps: a stray lockfile must not exist.
            if lock_file.exists():
                if args.check:
                    print(f"STALE (should not exist): {lock_file}")
                    drift = True
                else:
                    lock_file.unlink()
                    print(f"  - removed {lock_file}")
            continue

        new_text = compile_lock(deps)
        if args.check:
            existing = lock_file.read_text() if lock_file.exists() else ""
            if existing != new_text:
                print(f"STALE: {lock_file}")
                drift = True
        else:
            lock_file.write_text(new_text)
            print(f"  + {lock_file}")

    if args.check and drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 3: Make executable**

```bash
chmod +x /Users/asuka/code/magi-plugins/scripts/lock-deps.py
```

- [x] **Step 4: Smoke-run against one plugin with deps**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/lock-deps.py weixin
```
Expected: prints `  + .../plugins/weixin/requirements.lock`; the file exists and contains the header plus pinned lines like `segno==1.6.1 \` followed by `--hash=sha256:...`. (`weixin` chosen first because `segno` + `cryptography` are pure cross-platform — no platform-specific wheels — so it's the simplest to eyeball.)

If `uv pip compile` fails with a network error, STOP and report BLOCKED — locks cannot be generated offline.

- [x] **Step 5: Verify `--check` semantics**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/lock-deps.py weixin --check; echo "exit=$?"   # just generated → in sync → exit=0
echo "# tampered" >> plugins/weixin/requirements.lock
python scripts/lock-deps.py weixin --check; echo "exit=$?"   # tampered → STALE → exit=1
python scripts/lock-deps.py weixin                            # regenerate, restores canonical form
git -C /Users/asuka/code/magi-plugins diff --exit-code -- plugins/weixin/requirements.lock && echo "restored"
```
Expected: first `exit=0`, second prints `STALE` + `exit=1`, final prints `restored`.

- [x] **Step 6: Commit the script only (locks come in Task 2)**

```bash
cd /Users/asuka/code/magi-plugins
git checkout -- plugins/weixin/requirements.lock 2>/dev/null || rm -f plugins/weixin/requirements.lock
git add scripts/lock-deps.py
git commit -m "feat(scripts): add lock-deps.py for per-plugin dependency locking"
```
(The smoke-test lockfile is discarded here; Task 2 regenerates all locks cleanly in one commit.)

---

## Task 2: Generate and commit all lockfiles (migration)

**Files:**
- Create: `plugins/calendar_plugin/requirements.lock`, `plugins/screen_time/requirements.lock`, `plugins/system_media/requirements.lock`, `plugins/screenshot_timeline/requirements.lock`, `plugins/telegram/requirements.lock`, `plugins/weixin/requirements.lock`

- [x] **Step 1: Generate all locks**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/lock-deps.py
```
Expected: six `  + .../requirements.lock` lines (one per plugin with deps). Plugins without deps print nothing.

- [x] **Step 2: Verify each lock is non-empty and hashed**

```bash
cd /Users/asuka/code/magi-plugins
for p in calendar_plugin screen_time system_media screenshot_timeline telegram weixin; do
  echo "=== $p ==="
  grep -c -- "--hash=sha256:" "plugins/$p/requirements.lock"
done
```
Expected: each prints a count ≥ 1 (every plugin's lock has at least one hashed pin). A count of 0 means resolution produced no hashes — investigate before committing.

- [x] **Step 3: Verify platform-marker handling on a Windows-only dep**

```bash
cd /Users/asuka/code/magi-plugins
grep -n "winrt\|sys_platform" plugins/system_media/requirements.lock | head
```
Expected: `winrt-*` lines carry a `; sys_platform == 'win32'` marker (uv `--universal` preserves markers so pip installs them only on Windows). This confirms a macOS install will correctly skip them.

- [x] **Step 4: Confirm `--check` is clean across all plugins**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/lock-deps.py --check; echo "exit=$?"
```
Expected: no `STALE` lines, `exit=0`.

- [x] **Step 5: Commit all six locks**

```bash
cd /Users/asuka/code/magi-plugins
git add plugins/*/requirements.lock
git commit -m "feat(plugins): add hash-pinned requirements.lock for all dependency-declaring plugins"
```

---

## Task 3: Add the CI drift workflow

**Files:**
- Create: `/Users/asuka/code/magi-plugins/.github/workflows/ci.yml`

- [x] **Step 1: Write the workflow**

Create `/Users/asuka/code/magi-plugins/.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  lockfiles-in-sync:
    name: Plugin lockfiles in sync with manifests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - name: Install uv
        run: pip install uv
      - name: Check lockfiles
        run: python scripts/lock-deps.py --check

  registry-in-sync:
    name: registry.json in sync with manifests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - name: Regenerate registry
        run: python scripts/build-registry.py
      - name: Assert registry committed up to date
        run: |
          if ! git diff --exit-code -- registry.json; then
            echo "::error::registry.json is stale. Run scripts/build-registry.py and commit."
            exit 1
          fi
```

Note: `lockfiles-in-sync` uses `lock-deps.py --check` (the script does its own comparison and exits nonzero on drift). `registry-in-sync` uses the regenerate + `git diff` pattern because `build-registry.py` has no `--check` mode.

- [x] **Step 2: Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('/Users/asuka/code/magi-plugins/.github/workflows/ci.yml'))" && echo "valid YAML"
```
Expected: `valid YAML`.

- [x] **Step 3: Verify registry is currently in sync (so the new CI won't fail on existing state)**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/build-registry.py
git diff --exit-code -- registry.json && echo "registry in sync"
```
Expected: `registry in sync`. If it prints a diff, the committed `registry.json` was stale before this work — commit the regenerated registry as part of Step 4 and note it.

- [x] **Step 4: Commit the workflow**

```bash
cd /Users/asuka/code/magi-plugins
git add .github/workflows/ci.yml
# Only if Step 3 showed registry drift, also: git add registry.json
git commit -m "ci: drift-check plugin lockfiles and registry.json"
```

---

## Task 4: Document the workflow

**Files:**
- Modify: `/Users/asuka/code/magi-plugins/agents.md`

- [x] **Step 1: Add lockfile rules to the Do/Don't list**

In `/Users/asuka/code/magi-plugins/agents.md`, find the `**Do**` bullet list under "Quick Rules (Do / Don't)" that currently contains `- Run \`python scripts/build-registry.py\` after adding or modifying a plugin.` Add immediately after it:

```markdown
- After changing a plugin's `dependencies`, run `python scripts/lock-deps.py <plugin_dir>` (needs `uv`: `pip install uv`) and commit the updated `requirements.lock`.
```

And in the `**Don't**` list, after `- Don't manually edit \`registry.json\` — always regenerate it via the script.`, add:

```markdown
- Don't hand-edit `requirements.lock` files — always regenerate via `scripts/lock-deps.py`.
```

- [x] **Step 2: Commit**

```bash
cd /Users/asuka/code/magi-plugins
git add agents.md
git commit -m "docs: document lock-deps.py dependency-locking workflow"
```

---

## Task 5: Phase A verification

- [x] **Step 1: Locks deterministic, registry in sync, YAML valid**

```bash
cd /Users/asuka/code/magi-plugins
python scripts/lock-deps.py --check && echo "locks OK"
python scripts/build-registry.py && git diff --exit-code -- registry.json && echo "registry OK"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "yaml OK"
git status --short
git log --oneline -5
```
Expected: `locks OK`, `registry OK`, `yaml OK`; `git status --short` clean (no uncommitted Phase A files); the recent log shows the four Phase A commits (script, locks, workflow, docs).

---

# PHASE B — magi (enforce at install)

All Phase B tasks run from `/Users/asuka/code/magi`. Tests use **synthetic** lockfiles in temp dirs — they do NOT depend on the `magi-plugins` checkout.

## Task 6: Rewrite dependency installation to lock-based + no-lock policy

**Why one task:** the install-command builder and its only caller
(`_install_dependencies`) are coupled — changing the builder's signature
without updating the caller leaves the integration path broken. They must
land in one commit. TDD is preserved via the step ordering below.

**Files:**
- Modify: `/Users/asuka/code/magi/backend/src/magi/plugins/installation.py`
  (`_build_dependency_install_command` at lines 150-169; `_install_dependencies`
  at line 527; top-level constants near line 29)
- Test: `/Users/asuka/code/magi/backend/tests/plugins/test_plugin_dependency_locking.py` (create)

- [x] **Step 1: Read the current install internals first**

```bash
sed -n '150,169p;527,612p' /Users/asuka/code/magi/backend/src/magi/plugins/installation.py
```
Note the exact `_report_install_progress(...)` percentages (e.g. 56.0 / 82.0)
and the `_run_dependency_install_with_progress(cmd, progress_reporter)` call
shape — the rewrite below mirrors them; reconcile any drift with what you see.

- [x] **Step 2: Write the failing tests**

Create `/Users/asuka/code/magi/backend/tests/plugins/test_plugin_dependency_locking.py`:

```python
from pathlib import Path

import pytest

from magi.plugins.installation import (
    UnlockedDependencyError,
    _build_dependency_install_command,
    _resolve_lock_or_policy,
)


def test_build_command_uses_require_hashes_and_lockfile(tmp_path: Path) -> None:
    deps_dir = tmp_path / ".deps"
    lock = tmp_path / "requirements.lock"
    lock.write_text("segno==1.6.1 --hash=sha256:abc\n")

    cmd = _build_dependency_install_command(lock, deps_dir, quiet=True)

    assert "--require-hashes" in cmd
    assert "-r" in cmd
    assert str(lock) in cmd
    assert "--target" in cmd
    assert str(deps_dir) in cmd
    # user mirror config must keep working: never hard-code an index
    assert "--index-url" not in cmd
    assert "-i" not in cmd


def test_lock_present_returns_lock_path(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("segno==1.6.1 --hash=sha256:abc\n")
    result = _resolve_lock_or_policy(["segno>=1.6.1"], tmp_path, allow_unlocked=False)
    assert result == lock


def test_no_deps_returns_none(tmp_path: Path) -> None:
    assert _resolve_lock_or_policy([], tmp_path, allow_unlocked=False) is None


def test_deps_without_lock_rejected_by_default(tmp_path: Path) -> None:
    with pytest.raises(UnlockedDependencyError):
        _resolve_lock_or_policy(["segno>=1.6.1"], tmp_path, allow_unlocked=False)


def test_deps_without_lock_allowed_in_developer_mode(tmp_path: Path) -> None:
    result = _resolve_lock_or_policy(["segno>=1.6.1"], tmp_path, allow_unlocked=True)
    assert result == ["segno>=1.6.1"]
```

- [x] **Step 3: Run, verify failure**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/test_plugin_dependency_locking.py -v
```
Expected: FAIL — `_resolve_lock_or_policy` / `UnlockedDependencyError` don't exist,
and `_build_dependency_install_command` still takes a deps list (no `--require-hashes`).

- [x] **Step 4: Add constants + env-var reader near line 29**

The file already defines `PLUGIN_DEPENDENCY_PYTHON_ENV` near line 29. Add beside it:

```python
ALLOW_UNLOCKED_DEPS_ENV = "MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS"


def _developer_mode_allows_unlocked() -> bool:
    return os.environ.get(ALLOW_UNLOCKED_DEPS_ENV, "").strip() in {"1", "true", "TRUE"}
```

If `os` is not already imported at the top of the module, add `import os` with
the other stdlib imports.

- [x] **Step 5: Replace the command builder + add the loose fallback builder**

Replace `_build_dependency_install_command` (lines 150-169) with the
lock-based version, and add the renamed loose builder right after it:

```python
def _build_dependency_install_command(
    lock_path: Path,
    deps_dir: Path,
    *,
    quiet: bool,
) -> list[str]:
    cmd = [
        _resolve_dependency_python_executable(),
        "-m",
        "pip",
        "install",
        "--target",
        str(deps_dir),
        "--no-user",
        "--disable-pip-version-check",
        "--require-hashes",
        "-r",
        str(lock_path),
    ]
    if quiet:
        cmd.insert(cmd.index("--require-hashes"), "--quiet")
    return cmd


def _build_loose_dependency_install_command(
    dependencies: list[str],
    deps_dir: Path,
    *,
    quiet: bool,
) -> list[str]:
    """Unverified, range-based install. Developer-mode fallback only."""
    cmd = [
        _resolve_dependency_python_executable(),
        "-m",
        "pip",
        "install",
        "--target",
        str(deps_dir),
        "--no-user",
        "--disable-pip-version-check",
        *dependencies,
    ]
    if quiet:
        cmd.insert(-len(dependencies), "--quiet")
    return cmd
```

- [x] **Step 6: Add the policy helper + exception**

After the two builders, add:

```python
class UnlockedDependencyError(RuntimeError):
    """Raised when a plugin declares dependencies but ships no requirements.lock."""


def _resolve_lock_or_policy(
    dependencies: list[str],
    plugin_dir: Path,
    *,
    allow_unlocked: bool,
) -> Path | list[str] | None:
    """Decide how to install a plugin's dependencies.

    Returns:
      - None       when the plugin declares no dependencies.
      - Path       to requirements.lock when present (hash-enforced install).
      - list[str]  the raw dependency list when no lock exists AND developer
                   mode permits an unverified loose install.

    Raises UnlockedDependencyError when deps are declared, no lock exists, and
    developer mode is off (the default, secure path).
    """
    if not dependencies:
        return None
    lock_path = plugin_dir / "requirements.lock"
    if lock_path.exists():
        return lock_path
    if allow_unlocked:
        return dependencies
    raise UnlockedDependencyError(
        "This plugin declares dependencies but ships no integrity-locked "
        "requirements.lock. Refusing to install unverified dependencies. "
        "Set MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS=1 to override (developer mode)."
    )
```

- [x] **Step 7: Rewrite `_install_dependencies` body (line 527) to use the policy**

```python
@staticmethod
def _install_dependencies(
    dependencies: list[str],
    plugin_dir: Path,
    *,
    progress_reporter: InstallProgressReporter | None = None,
) -> None:
    """Install plugin dependencies into a local .deps/ directory.

    Hash-enforced from requirements.lock by default; falls back to a loose,
    unverified install only in developer mode (see _resolve_lock_or_policy).
    """
    allow_unlocked = _developer_mode_allows_unlocked()
    resolved = _resolve_lock_or_policy(
        dependencies, plugin_dir, allow_unlocked=allow_unlocked
    )
    if resolved is None:
        logger.info(
            "No plugin dependencies need installation",
            extra={"target": str(plugin_dir)},
        )
        _report_install_progress(
            progress_reporter,
            "dependencies",
            "No plugin dependencies need installation",
            82.0,
        )
        return

    deps_dir = plugin_dir / ".deps"
    deps_dir.mkdir(exist_ok=True)

    if isinstance(resolved, Path):
        cmd = _build_dependency_install_command(
            resolved, deps_dir, quiet=progress_reporter is None
        )
        install_label = f"Installing locked plugin dependencies from {resolved.name}"
    else:
        logger.warning(
            "Installing UNVERIFIED plugin dependencies (developer mode; no "
            "requirements.lock). This bypasses supply-chain integrity checks.",
            extra={"deps": resolved, "target": str(deps_dir)},
        )
        installable, skipped = _filter_installable_dependencies(resolved)
        if skipped:
            logger.info(
                "Skipping plugin dependencies for current environment",
                extra={"deps": skipped, "target": str(deps_dir)},
            )
        if not installable:
            _report_install_progress(
                progress_reporter,
                "dependencies",
                "No plugin dependencies need installation",
                82.0,
            )
            return
        cmd = _build_loose_dependency_install_command(
            installable, deps_dir, quiet=progress_reporter is None
        )
        install_label = (
            f"Installing UNVERIFIED plugin dependencies: {', '.join(installable)}"
        )

    logger.info(install_label, extra={"target": str(deps_dir), "python": cmd[0]})
    _report_install_progress(progress_reporter, "dependencies", install_label, 56.0)
    try:
        if progress_reporter is None:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        else:
            result = _run_dependency_install_with_progress(cmd, progress_reporter)
    except subprocess.TimeoutExpired as exc:
        logger.exception(
            "Plugin dependency installation timed out",
            extra={"target": str(deps_dir)},
        )
        raise RuntimeError(
            f"Timed out installing plugin dependencies after {exc.timeout} seconds"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.error(
            "Plugin dependency installation failed",
            extra={
                "target": str(deps_dir),
                "returncode": result.returncode,
                "stderr": stderr,
            },
        )
        raise RuntimeError(f"Plugin dependency installation failed: {stderr}")
    _report_install_progress(
        progress_reporter, "dependencies", "Installed plugin dependencies", 82.0
    )
```

Reconcile the `_report_install_progress` percentages and the
`_run_dependency_install_with_progress` signature against what Step 1 showed.

- [x] **Step 8: Run the unit + policy tests, verify pass**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/test_plugin_dependency_locking.py -v
```
Expected: all 5 tests PASS.

- [x] **Step 9: Commit**

```bash
cd /Users/asuka/code/magi
git add backend/src/magi/plugins/installation.py backend/tests/plugins/test_plugin_dependency_locking.py
git commit -m "feat(plugins): hash-locked dep install; refuse unlocked deps by default"
```

---

## Task 7: Integration test — tampered hash is rejected

**Files:**
- Test: `/Users/asuka/code/magi/backend/tests/plugins/test_plugin_dependency_locking.py` (extend)

- [x] **Step 1: Write an integration test that actually invokes pip with a bad hash**

Append:

```python
import subprocess as _subprocess


def test_require_hashes_rejects_tampered_lock(tmp_path: Path) -> None:
    """A lockfile whose hash does not match the real artifact must fail install.

    This is the core supply-chain property: a poisoned/mismatched artifact is
    refused by pip before it lands in .deps/.
    """
    deps_dir = tmp_path / ".deps"
    lock = tmp_path / "requirements.lock"
    # Real package name + version, deliberately WRONG hash.
    lock.write_text(
        "segno==1.6.1 "
        "--hash=sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
    )
    cmd = _build_dependency_install_command(lock, deps_dir, quiet=True)
    proc = _subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0
    assert "hash" in (proc.stdout + proc.stderr).lower()
    assert not deps_dir.exists() or not any(deps_dir.iterdir())
```

- [x] **Step 2: Run it**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/test_plugin_dependency_locking.py::test_require_hashes_rejects_tampered_lock -v
```
Expected: PASS (pip exits nonzero with a hash-mismatch error; nothing installed). Requires network (pip reaches the index to fetch segno). If the environment is offline, mark this test `@pytest.mark.skipif` on a network probe and report the limitation — do NOT delete it.

- [x] **Step 3: Commit**

```bash
cd /Users/asuka/code/magi
git add backend/tests/plugins/test_plugin_dependency_locking.py
git commit -m "test(plugins): verify --require-hashes rejects a tampered lockfile"
```

---

## Task 8: Phase B verification

- [x] **Step 1: Full plugin test suite + targeted module**

```bash
cd /Users/asuka/code/magi/backend
../.venv/bin/python -m pytest tests/plugins/ -v 2>&1 | tail -30
```
Expected: all tests pass (the new `test_plugin_dependency_locking.py` plus the pre-existing `test_plugin_install_executable_bit.py`, `test_plugin_manager.py`, etc.). If a pre-existing test breaks because it relied on the old loose-install path, fix it to supply a `requirements.lock` fixture (or set `MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS=1` in that test's monkeypatched env) and note the change.

- [x] **Step 2: Gateway sanity (untouched, confirm no regression)**

```bash
cd /Users/asuka/code/magi
cargo test -p magi-gateway 2>&1 | tail -5
```
Expected: `test result: ok` for each binary.

- [x] **Step 3: Status + log**

```bash
cd /Users/asuka/code/magi
git status --short
git log --oneline -4
```
Expected: working tree shows only user's unrelated parallel work (if any); the recent log shows the two Phase B commits (hash-locked dep install + policy; tampered-hash integration test).

---

## Acceptance criteria (mirrors spec §7)

**Phase A (magi-plugins):**
- `scripts/lock-deps.py` generates and `--check`s per-plugin locks; deterministic via `--exclude-newer`.
- All 6 dependency-declaring plugins have committed `requirements.lock` files with sha256 hashes.
- `system_media`'s lock carries `sys_platform == 'win32'` markers on winrt deps (macOS install skips them).
- `.github/workflows/ci.yml` drift-checks lockfiles + registry.
- `agents.md` documents the regenerate workflow.

**Phase B (magi):**
- Dependency install uses `--require-hashes -r requirements.lock`, never `--index-url` (mirror config preserved).
- A plugin with deps + lock installs hash-verified; a tampered hash fails install with nothing landing in `.deps/`.
- A plugin with deps + no lock is refused by default; `MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS=1` falls back to loose install with a warning log.
- `pytest tests/plugins/` and `cargo test -p magi-gateway` are green.

**Out of scope (separate sub-projects, per spec §10):** registry-as-authority for `official`, capability declaration + consent UI, process isolation/sandbox.
