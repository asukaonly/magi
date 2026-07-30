"""Plugin dependency installation helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import sys
import threading
import time

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement

logger = logging.getLogger(__name__)
InstallProgressReporter = Callable[[str, str, float | None], None]
PLUGIN_DEPENDENCY_PYTHON_ENV = "MAGI_PLUGIN_PYTHON"
BACKEND_PYTHON_ENV = "MAGI_BACKEND_PYTHON"
ALLOW_UNLOCKED_DEPS_ENV = "MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS"
MAX_PLUGIN_DEPENDENCY_LOCK_BYTES = 1024 * 1024
_LOCK_HASH_PATTERN = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}")


class UnlockedDependencyError(RuntimeError):
    """Raised when a plugin declares dependencies but ships no requirements.lock."""


class UnsafeDependencyLockError(RuntimeError):
    """Raised when a dependency lock could execute a source build or pip directive."""


@dataclass(slots=True)
class _DependencyInstallPlan:
    cmd: list[str]
    label: str
    deps_dir: Path


def _developer_mode_allows_unlocked() -> bool:
    return os.environ.get(ALLOW_UNLOCKED_DEPS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _report_install_progress(
    reporter: InstallProgressReporter | None,
    stage: str,
    message: str,
    progress_pct: float | None = None,
) -> None:
    if reporter is not None:
        reporter(stage, message, progress_pct)


def _filter_installable_dependencies(dependencies: list[str]) -> tuple[list[str], list[str]]:
    installable: list[str] = []
    skipped: list[str] = []
    environment = default_environment()

    for dependency in dependencies:
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement:
            installable.append(dependency)
            continue

        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            skipped.append(dependency)
            continue

        installable.append(dependency)

    return installable, skipped


def _is_frozen_runtime() -> bool:
    return bool(getattr(sys, "frozen", False))


def _looks_like_sidecar_executable(executable: str) -> bool:
    name = Path(executable).name.lower()
    return name in {"magi-backend", "magi-backend.exe"}


def _dependency_python_candidates() -> list[str]:
    candidates: list[str] = []
    for env_name in (PLUGIN_DEPENDENCY_PYTHON_ENV, BACKEND_PYTHON_ENV):
        configured = os.environ.get(env_name)
        if configured:
            candidates.append(configured)

    if not _is_frozen_runtime() and sys.executable:
        candidates.append(sys.executable)

    for executable_name in ("python3", "python"):
        discovered = shutil.which(executable_name)
        if discovered:
            candidates.append(discovered)

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(Path(candidate).expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(normalized)
    return unique_candidates


def _probe_python_for_pip(executable: str) -> tuple[bool, str]:
    if _looks_like_sidecar_executable(executable):
        return False, "candidate is the Magi sidecar executable"

    probe = (
        "import importlib.util, sys; "
        "has_pip = importlib.util.find_spec('pip') is not None; "
        "print(f'{sys.version_info.major}.{sys.version_info.minor} {int(has_pip)}')"
    )
    try:
        result = subprocess.run(
            [executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)

    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip() or "probe failed"

    output = result.stdout.strip().split()
    if len(output) != 2:
        return False, "probe returned an unexpected response"

    expected_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if output[0] != expected_version:
        return False, f"Python {output[0]} does not match runtime Python {expected_version}"
    if output[1] != "1":
        return False, "pip is not importable"
    return True, ""


def _resolve_dependency_python_executable() -> str:
    rejected: list[str] = []
    for candidate in _dependency_python_candidates():
        ok, reason = _probe_python_for_pip(candidate)
        if ok:
            return candidate
        rejected.append(f"{candidate}: {reason}")

    expected_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    details = "; ".join(rejected) if rejected else "no candidate Python executable found"
    raise RuntimeError(
        "Cannot install plugin dependencies because no Python interpreter with pip is available. "
        f"Set {PLUGIN_DEPENDENCY_PYTHON_ENV} to a Python {expected_version} executable with pip. "
        f"Checked: {details}"
    )


def _build_dependency_install_command(
    lock_path: Path,
    deps_dir: Path,
    *,
    quiet: bool,
) -> list[str]:
    _validate_dependency_lock(lock_path)
    cmd = [
        _resolve_dependency_python_executable(),
        "-m",
        "pip",
        "install",
        "--target",
        str(deps_dir),
        "--no-user",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--require-hashes",
        "-r",
        str(lock_path),
    ]
    if quiet:
        cmd.insert(cmd.index("--require-hashes"), "--quiet")
    return cmd


def _validate_dependency_lock(lock_path: Path) -> None:
    """Accept only exact, hash-pinned package requirements from an ordinary index."""

    try:
        size = lock_path.stat().st_size
    except OSError as exc:
        raise UnsafeDependencyLockError(f"Cannot read plugin dependency lock: {lock_path}") from exc
    if size <= 0 or size > MAX_PLUGIN_DEPENDENCY_LOCK_BYTES:
        raise UnsafeDependencyLockError(
            f"Plugin dependency lock must be between 1 and "
            f"{MAX_PLUGIN_DEPENDENCY_LOCK_BYTES} bytes"
        )

    try:
        text = lock_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UnsafeDependencyLockError(
            "Plugin dependency lock must be readable UTF-8 text"
        ) from exc

    statements = _dependency_lock_statements(text)
    if not statements:
        raise UnsafeDependencyLockError("Plugin dependency lock contains no requirements")
    for statement in statements:
        hash_start = statement.find(" --hash=")
        if hash_start < 0:
            raise UnsafeDependencyLockError(
                "Every locked plugin dependency must include a SHA-256 hash"
            )
        requirement_text = statement[:hash_start].strip()
        hash_tokens = statement[hash_start:].split()
        if not hash_tokens or any(
            _LOCK_HASH_PATTERN.fullmatch(token) is None for token in hash_tokens
        ):
            raise UnsafeDependencyLockError(
                "Plugin dependency locks may contain only SHA-256 hash options"
            )
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement as exc:
            raise UnsafeDependencyLockError(
                f"Invalid locked plugin dependency: {requirement_text}"
            ) from exc
        if requirement.url is not None:
            raise UnsafeDependencyLockError(
                "Plugin dependency locks cannot use direct URLs or local paths"
            )
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==" or "*" in specifiers[0].version:
            raise UnsafeDependencyLockError(
                f"Plugin dependency must pin one exact version: {requirement.name}"
            )


def _dependency_lock_statements(text: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        continued = stripped.endswith("\\")
        part = stripped[:-1].rstrip() if continued else stripped
        pending = f"{pending} {part}".strip()
        if not continued:
            statements.append(pending)
            pending = ""
    if pending:
        raise UnsafeDependencyLockError("Plugin dependency lock has an unfinished continuation")
    return statements


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
    if quiet and dependencies:
        cmd.insert(-len(dependencies), "--quiet")
    return cmd


def _resolve_lock_or_policy(
    dependencies: list[str],
    plugin_dir: Path,
    *,
    allow_unlocked: bool,
) -> Path | list[str] | None:
    """Decide how to install a plugin's dependencies."""
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


def install_plugin_dependencies(
    dependencies: list[str],
    plugin_dir: Path,
    *,
    progress_reporter: InstallProgressReporter | None = None,
) -> None:
    """Install plugin dependencies into a local .deps/ directory."""
    allow_unlocked = _developer_mode_allows_unlocked()
    resolved = _resolve_lock_or_policy(dependencies, plugin_dir, allow_unlocked=allow_unlocked)
    if resolved is None:
        _report_no_plugin_dependencies(plugin_dir, progress_reporter)
        return

    deps_dir = plugin_dir / ".deps"
    deps_dir.mkdir(exist_ok=True)

    plan = _dependency_install_plan(
        resolved,
        deps_dir=deps_dir,
        progress_reporter=progress_reporter,
    )
    if plan is None:
        return

    _run_dependency_install_plan(plan, progress_reporter)


def _report_no_plugin_dependencies(
    plugin_dir: Path,
    progress_reporter: InstallProgressReporter | None,
) -> None:
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


def _dependency_install_plan(
    resolved: Path | list[str],
    *,
    deps_dir: Path,
    progress_reporter: InstallProgressReporter | None,
) -> _DependencyInstallPlan | None:
    if isinstance(resolved, Path):
        return _locked_dependency_install_plan(
            resolved,
            deps_dir=deps_dir,
            progress_reporter=progress_reporter,
        )
    return _loose_dependency_install_plan(
        resolved,
        deps_dir=deps_dir,
        progress_reporter=progress_reporter,
    )


def _locked_dependency_install_plan(
    lock_path: Path,
    *,
    deps_dir: Path,
    progress_reporter: InstallProgressReporter | None,
) -> _DependencyInstallPlan:
    return _DependencyInstallPlan(
        cmd=_build_dependency_install_command(
            lock_path,
            deps_dir,
            quiet=progress_reporter is None,
        ),
        label=f"Installing locked plugin dependencies from {lock_path.name}",
        deps_dir=deps_dir,
    )


def _loose_dependency_install_plan(
    dependencies: list[str],
    *,
    deps_dir: Path,
    progress_reporter: InstallProgressReporter | None,
) -> _DependencyInstallPlan | None:
    logger.warning(
        "Installing UNVERIFIED plugin dependencies (developer mode; no "
        "requirements.lock). This bypasses supply-chain integrity checks.",
        extra={"deps": dependencies, "target": str(deps_dir)},
    )
    installable, skipped = _filter_installable_dependencies(dependencies)
    if skipped:
        _report_skipped_dependencies(skipped, deps_dir, progress_reporter)
    if not installable:
        _report_install_progress(
            progress_reporter,
            "dependencies",
            "No plugin dependencies need installation",
            82.0,
        )
        return None
    return _DependencyInstallPlan(
        cmd=_build_loose_dependency_install_command(
            installable,
            deps_dir,
            quiet=progress_reporter is None,
        ),
        label=f"Installing UNVERIFIED plugin dependencies: {', '.join(installable)}",
        deps_dir=deps_dir,
    )


def _report_skipped_dependencies(
    skipped: list[str],
    deps_dir: Path,
    progress_reporter: InstallProgressReporter | None,
) -> None:
    logger.info(
        "Skipping plugin dependencies for current environment",
        extra={"deps": skipped, "target": str(deps_dir)},
    )
    _report_install_progress(
        progress_reporter,
        "dependencies",
        f"Skipping plugin dependencies for current environment: {', '.join(skipped)}",
    )


def _run_dependency_install_plan(
    plan: _DependencyInstallPlan,
    progress_reporter: InstallProgressReporter | None,
) -> None:
    logger.info(plan.label, extra={"target": str(plan.deps_dir), "python": plan.cmd[0]})
    _report_install_progress(progress_reporter, "dependencies", plan.label, 56.0)
    try:
        if progress_reporter is None:
            result = subprocess.run(plan.cmd, capture_output=True, text=True, timeout=300)
        else:
            result = _run_dependency_install_with_progress(plan.cmd, progress_reporter)
    except subprocess.TimeoutExpired as exc:
        logger.exception(
            "Plugin dependency installation timed out",
            extra={"target": str(plan.deps_dir)},
        )
        raise RuntimeError(
            f"Timed out installing plugin dependencies after {exc.timeout} seconds"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.error(
            "Plugin dependency installation failed",
            extra={
                "target": str(plan.deps_dir),
                "returncode": result.returncode,
                "stderr": stderr,
            },
        )
        raise RuntimeError(f"Plugin dependency installation failed: {stderr}")
    _report_install_progress(
        progress_reporter, "dependencies", "Installed plugin dependencies", 82.0
    )


def _run_dependency_install_with_progress(
    cmd: list[str],
    progress_reporter: InstallProgressReporter,
) -> subprocess.CompletedProcess[str]:
    output_lines: list[str] = []
    output_queue: Queue[str] = Queue()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def read_output() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            output_queue.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + 300

    while process.poll() is None:
        try:
            line = output_queue.get(timeout=0.1)
        except Empty:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise subprocess.TimeoutExpired(cmd, 300)
            continue
        text = line.strip()
        if text:
            output_lines.append(text)
            _report_install_progress(progress_reporter, "dependencies", text)

    reader.join(timeout=1.0)
    while True:
        try:
            line = output_queue.get_nowait()
        except Empty:
            break
        text = line.strip()
        if text:
            output_lines.append(text)
            _report_install_progress(progress_reporter, "dependencies", text)

    stdout = "\n".join(output_lines)
    return subprocess.CompletedProcess(cmd, process.returncode or 0, stdout=stdout, stderr=stdout)
