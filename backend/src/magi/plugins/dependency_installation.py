"""Plugin dependency installation helpers."""

from __future__ import annotations

from codecs import getincrementaldecoder
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

logger = logging.getLogger(__name__)
InstallProgressReporter = Callable[[str, str, float | None], None]
PLUGIN_DEPENDENCY_PYTHON_ENV = "MAGI_PLUGIN_PYTHON"
BACKEND_PYTHON_ENV = "MAGI_BACKEND_PYTHON"
ALLOW_UNLOCKED_DEPS_ENV = "MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS"
MAX_PLUGIN_DEPENDENCY_LOCK_BYTES = 1024 * 1024
MAX_PLUGIN_DEPENDENCY_LOCK_ENTRIES = 1024
MAX_PLUGIN_DEPENDENCY_INSTALL_BYTES = 256 * 1024 * 1024
MAX_PLUGIN_DEPENDENCY_INSTALL_ENTRIES = 50_000
MAX_PLUGIN_DEPENDENCY_OUTPUT_BYTES = 64 * 1024
MAX_PLUGIN_DEPENDENCY_OUTPUT_LINE_CHARS = 2048
DEPENDENCY_RESOURCE_CHECK_INTERVAL_SECONDS = 0.1
_LOCK_HASH_PATTERN = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}")
_OUTPUT_TRUNCATION_PREFIX = "[truncated] "


class UnlockedDependencyError(RuntimeError):
    """Raised when a plugin declares dependencies but ships no requirements.lock."""


class UnsafeDependencyLockError(RuntimeError):
    """Raised when a dependency lock could execute a source build or pip directive."""


class DependencyInstallResourceLimitError(RuntimeError):
    """Raised when dependency installation exceeds its local resource budget."""


@dataclass(slots=True)
class _DependencyInstallPlan:
    cmd: list[str]
    label: str
    deps_dir: Path
    staging_dir: Path


@dataclass(frozen=True, slots=True)
class _DependencyResourceUsage:
    bytes_used: int
    entries: int


class _BoundedOutputTail:
    """Retain only a bounded tail of subprocess output."""

    def __init__(self) -> None:
        self._lines: deque[str] = deque()
        self._bytes_used = 0

    def append(self, line: str) -> None:
        encoded_size = len(line.encode("utf-8")) + 1
        while (
            self._lines
            and self._bytes_used + encoded_size > MAX_PLUGIN_DEPENDENCY_OUTPUT_BYTES
        ):
            removed = self._lines.popleft()
            self._bytes_used -= len(removed.encode("utf-8")) + 1

        if encoded_size > MAX_PLUGIN_DEPENDENCY_OUTPUT_BYTES:
            line = _truncate_text_to_utf8_tail(
                line,
                max_bytes=max(1, MAX_PLUGIN_DEPENDENCY_OUTPUT_BYTES - 1),
            )
            encoded_size = len(line.encode("utf-8")) + 1

        self._lines.append(line)
        self._bytes_used += encoded_size

    def render(self) -> str:
        return "\n".join(self._lines)


class _BoundedLineParser:
    """Split streamed text into independently bounded output lines."""

    def __init__(self) -> None:
        self._fragment = ""
        self._truncated = False

    def feed(self, text: str) -> list[str]:
        parts = text.split("\n")
        completed: list[str] = []
        for part in parts[:-1]:
            self._append_fragment(part)
            completed.append(self._finish_line())
        self._append_fragment(parts[-1])
        return completed

    def flush(self) -> list[str]:
        if not self._fragment and not self._truncated:
            return []
        return [self._finish_line()]

    def _append_fragment(self, text: str) -> None:
        combined = f"{self._fragment}{text}"
        if len(combined) > MAX_PLUGIN_DEPENDENCY_OUTPUT_LINE_CHARS:
            self._fragment = combined[-MAX_PLUGIN_DEPENDENCY_OUTPUT_LINE_CHARS:]
            self._truncated = True
            return
        self._fragment = combined

    def _finish_line(self) -> str:
        line = self._fragment.rstrip("\r")
        if self._truncated:
            remaining = max(
                0,
                MAX_PLUGIN_DEPENDENCY_OUTPUT_LINE_CHARS
                - len(_OUTPUT_TRUNCATION_PREFIX),
            )
            tail = line[-remaining:] if remaining else ""
            line = f"{_OUTPUT_TRUNCATION_PREFIX}{tail}"
        self._fragment = ""
        self._truncated = False
        return line


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


def _filter_installable_dependencies(
    dependencies: list[str],
) -> tuple[list[str], list[str]]:
    installable: list[str] = []
    skipped: list[str] = []
    environment = default_environment()

    for dependency in dependencies:
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement:
            installable.append(dependency)
            continue

        if requirement.marker is not None and not requirement.marker.evaluate(
            environment
        ):
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
        candidate_path = Path(candidate).expanduser()
        if not candidate_path.is_absolute():
            discovered = shutil.which(str(candidate_path))
            if discovered:
                candidate_path = Path(discovered)
        normalized = os.path.abspath(candidate_path)
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
        return (
            False,
            f"Python {output[0]} does not match runtime Python {expected_version}",
        )
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
    details = (
        "; ".join(rejected) if rejected else "no candidate Python executable found"
    )
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
    declared_dependencies: list[str] | None = None,
) -> list[str]:
    locked_names = _validate_dependency_lock(lock_path)
    if declared_dependencies is not None:
        _validate_dependency_lock_coverage(declared_dependencies, locked_names)
    resolved_deps_dir = deps_dir.resolve(strict=False)
    resolved_lock_path = lock_path.resolve(strict=False)
    cmd = [
        _resolve_dependency_python_executable(),
        "-m",
        "pip",
        "install",
        "--target",
        str(resolved_deps_dir),
        "--no-user",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--only-binary=:all:",
        "--require-hashes",
        "-r",
        str(resolved_lock_path),
    ]
    if quiet:
        cmd.insert(cmd.index("--require-hashes"), "--quiet")
    return cmd


def _validate_dependency_lock(lock_path: Path) -> set[str]:
    """Accept only exact, hash-pinned package requirements from an ordinary index."""

    try:
        size = lock_path.stat().st_size
    except OSError as exc:
        raise UnsafeDependencyLockError(
            f"Cannot read plugin dependency lock: {lock_path}"
        ) from exc
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
        raise UnsafeDependencyLockError(
            "Plugin dependency lock contains no requirements"
        )
    if len(statements) > MAX_PLUGIN_DEPENDENCY_LOCK_ENTRIES:
        raise UnsafeDependencyLockError(
            "Plugin dependency lock contains too many requirements "
            f"(maximum {MAX_PLUGIN_DEPENDENCY_LOCK_ENTRIES})"
        )
    locked_names: set[str] = set()
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
        if (
            len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            raise UnsafeDependencyLockError(
                f"Plugin dependency must pin one exact version: {requirement.name}"
            )
        locked_names.add(canonicalize_name(requirement.name))
    return locked_names


def _validate_dependency_lock_coverage(
    declared_dependencies: list[str],
    locked_names: set[str],
) -> None:
    declared_names: set[str] = set()
    for dependency in declared_dependencies:
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement as exc:
            raise UnsafeDependencyLockError(
                f"Invalid declared plugin dependency: {dependency}"
            ) from exc
        declared_names.add(canonicalize_name(requirement.name))

    missing = sorted(declared_names - locked_names)
    if missing:
        raise UnsafeDependencyLockError(
            "Plugin dependency lock does not cover declared dependencies: "
            f"{', '.join(missing)}"
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
        raise UnsafeDependencyLockError(
            "Plugin dependency lock has an unfinished continuation"
        )
    return statements


def _build_loose_dependency_install_command(
    dependencies: list[str],
    deps_dir: Path,
    *,
    quiet: bool,
) -> list[str]:
    """Unverified, range-based install. Developer-mode fallback only."""
    resolved_deps_dir = deps_dir.resolve(strict=False)
    cmd = [
        _resolve_dependency_python_executable(),
        "-m",
        "pip",
        "install",
        "--target",
        str(resolved_deps_dir),
        "--no-user",
        "--disable-pip-version-check",
        "--no-cache-dir",
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
    resolved = _resolve_lock_or_policy(
        dependencies, plugin_dir, allow_unlocked=allow_unlocked
    )
    if resolved is None:
        _report_no_plugin_dependencies(plugin_dir, progress_reporter)
        return

    deps_dir = (plugin_dir / ".deps").resolve(strict=False)
    deps_dir.mkdir(exist_ok=True)

    plan = _dependency_install_plan(
        resolved,
        declared_dependencies=dependencies,
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
    declared_dependencies: list[str],
    deps_dir: Path,
    progress_reporter: InstallProgressReporter | None,
) -> _DependencyInstallPlan | None:
    if isinstance(resolved, Path):
        return _locked_dependency_install_plan(
            resolved,
            declared_dependencies=declared_dependencies,
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
    declared_dependencies: list[str],
    deps_dir: Path,
    progress_reporter: InstallProgressReporter | None,
) -> _DependencyInstallPlan:
    return _DependencyInstallPlan(
        cmd=_build_dependency_install_command(
            lock_path,
            deps_dir,
            quiet=progress_reporter is None,
            declared_dependencies=declared_dependencies,
        ),
        label=f"Installing locked plugin dependencies from {lock_path.name}",
        deps_dir=deps_dir,
        staging_dir=deps_dir.parent.resolve(strict=False),
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
        staging_dir=deps_dir.parent.resolve(strict=False),
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
    install_tmp_dir = Path(
        tempfile.mkdtemp(
            prefix=".magi-dependency-install-",
            dir=plan.staging_dir,
        )
    )
    install_env = os.environ.copy()
    for variable_name in (
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONWARNINGS",
    ):
        install_env.pop(variable_name, None)
    install_env.update(
        {
            "PIP_NO_CACHE_DIR": "1",
            "PYTHONNOUSERSITE": "1",
            "TEMP": str(install_tmp_dir),
            "TMP": str(install_tmp_dir),
            "TMPDIR": str(install_tmp_dir),
        }
    )
    try:
        result = _run_dependency_install_process(
            plan.cmd,
            progress_reporter=progress_reporter,
            monitored_roots=(plan.deps_dir, install_tmp_dir),
            env=install_env,
            cwd=install_tmp_dir,
        )
    except subprocess.TimeoutExpired as exc:
        logger.exception(
            "Plugin dependency installation timed out",
            extra={"target": str(plan.deps_dir)},
        )
        raise RuntimeError(
            f"Timed out installing plugin dependencies after {exc.timeout} seconds"
        ) from exc
    except DependencyInstallResourceLimitError:
        logger.exception(
            "Plugin dependency installation exceeded its resource budget",
            extra={"target": str(plan.deps_dir)},
        )
        raise
    finally:
        shutil.rmtree(install_tmp_dir, ignore_errors=True)

    if install_tmp_dir.exists():
        raise RuntimeError("Failed to clean plugin dependency installation workspace")
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip() or "no diagnostic output"
        logger.error(
            "Plugin dependency installation failed",
            extra={
                "target": str(plan.deps_dir),
                "returncode": result.returncode,
                "stderr": stderr,
            },
        )
        raise RuntimeError(f"Plugin dependency installation failed: {stderr}")
    _enforce_dependency_resource_limits((plan.deps_dir,))
    _report_install_progress(
        progress_reporter, "dependencies", "Installed plugin dependencies", 82.0
    )


def _run_dependency_install_with_progress(
    cmd: list[str],
    progress_reporter: InstallProgressReporter,
) -> subprocess.CompletedProcess[str]:
    return _run_dependency_install_process(
        cmd,
        progress_reporter=progress_reporter,
    )


def _run_dependency_install_process(
    cmd: list[str],
    *,
    progress_reporter: InstallProgressReporter | None,
    monitored_roots: tuple[Path, ...] = (),
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    output_tail = _BoundedOutputTail()
    output_queue: Queue[bytes | None] = Queue(maxsize=128)
    stop_reader = threading.Event()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        start_new_session=os.name != "nt",
    )

    def read_output() -> None:
        try:
            if process.stdout is not None:
                while not stop_reader.is_set():
                    chunk = process.stdout.read(8192)
                    if not chunk:
                        break
                    while not stop_reader.is_set():
                        try:
                            output_queue.put(chunk, timeout=0.1)
                            break
                        except Full:
                            continue
        finally:
            while not stop_reader.is_set():
                try:
                    output_queue.put(None, timeout=0.1)
                    break
                except Full:
                    continue

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + 300
    next_resource_check = time.monotonic()
    decoder = getincrementaldecoder("utf-8")(errors="replace")
    line_parser = _BoundedLineParser()
    reader_done = False

    def record_lines(lines: list[str]) -> None:
        for line in lines:
            text = line.strip()
            if not text:
                continue
            output_tail.append(text)
            _report_install_progress(progress_reporter, "dependencies", text)

    try:
        while True:
            now = time.monotonic()
            if now > deadline:
                _terminate_dependency_process(process)
                raise subprocess.TimeoutExpired(cmd, 300)
            if monitored_roots and now >= next_resource_check:
                _enforce_dependency_resource_limits(monitored_roots)
                next_resource_check = now + DEPENDENCY_RESOURCE_CHECK_INTERVAL_SECONDS

            try:
                chunk = output_queue.get(timeout=0.05)
            except Empty:
                chunk = b""

            if chunk is None:
                reader_done = True
                record_lines(line_parser.feed(decoder.decode(b"", final=True)))
                record_lines(line_parser.flush())
            elif chunk:
                record_lines(line_parser.feed(decoder.decode(chunk)))

            if process.poll() is not None and reader_done and output_queue.empty():
                if monitored_roots:
                    _enforce_dependency_resource_limits(monitored_roots)
                break
    except Exception:
        _terminate_dependency_process(process)
        raise
    finally:
        stop_reader.set()
        reader.join(timeout=1.0)

    process.wait(timeout=5)
    stdout = output_tail.render()
    return subprocess.CompletedProcess(
        cmd,
        process.returncode,
        stdout=stdout,
        stderr=stdout,
    )


def _terminate_dependency_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        if process.poll() is not None:
            return
        process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.error("Plugin dependency process did not exit after termination")


def _enforce_dependency_resource_limits(roots: tuple[Path, ...]) -> None:
    usage = _measure_dependency_resource_usage(roots)
    if usage.bytes_used > MAX_PLUGIN_DEPENDENCY_INSTALL_BYTES:
        raise DependencyInstallResourceLimitError(
            "Plugin dependency installation exceeded the "
            f"{MAX_PLUGIN_DEPENDENCY_INSTALL_BYTES}-byte limit"
        )
    if usage.entries > MAX_PLUGIN_DEPENDENCY_INSTALL_ENTRIES:
        raise DependencyInstallResourceLimitError(
            "Plugin dependency installation exceeded the "
            f"{MAX_PLUGIN_DEPENDENCY_INSTALL_ENTRIES}-entry limit"
        )


def _measure_dependency_resource_usage(
    roots: tuple[Path, ...],
) -> _DependencyResourceUsage:
    bytes_used = 0
    entries = 0
    pending = [root for root in roots if root.exists()]

    while pending:
        current = pending.pop()
        try:
            children = os.scandir(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DependencyInstallResourceLimitError(
                f"Cannot inspect plugin dependency installation output: {current}"
            ) from exc

        with children:
            for child in children:
                try:
                    metadata = child.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise DependencyInstallResourceLimitError(
                        "Cannot inspect plugin dependency installation output: "
                        f"{child.path}"
                    ) from exc
                entries += 1
                if entries > MAX_PLUGIN_DEPENDENCY_INSTALL_ENTRIES:
                    return _DependencyResourceUsage(
                        bytes_used=bytes_used,
                        entries=entries,
                    )
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(Path(child.path))
                else:
                    bytes_used += metadata.st_size
                    if bytes_used > MAX_PLUGIN_DEPENDENCY_INSTALL_BYTES:
                        return _DependencyResourceUsage(
                            bytes_used=bytes_used,
                            entries=entries,
                        )

    return _DependencyResourceUsage(bytes_used=bytes_used, entries=entries)


def _truncate_text_to_utf8_tail(text: str, *, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[-max_bytes:].decode("utf-8", errors="ignore")
