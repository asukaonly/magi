"""OS-backed secret storage abstraction for Magi configuration and plugin credentials.

Secrets are persisted in the platform credential store (macOS Keychain Services,
Windows Credential Manager, or Linux Secret Service when available) and referenced
from YAML/JSON files via opaque ``secret_ref:<namespace>:<key>`` placeholders.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import RLock
from typing import Any, Protocol

from magi_plugin_sdk.runtime_paths import get_magi_home

logger = logging.getLogger(__name__)

SECRET_REF_PREFIX = "secret_ref:"
_B64_VALUE_PREFIX = "magi_b64:"
_ENV_KEY_SANITIZE_RE = re.compile(r"[^A-Za-z0-9]+")


class SecretStoreError(RuntimeError):
    """Raised when reading or writing the underlying OS secret store fails."""


@dataclass(frozen=True, slots=True)
class SecretStorageStatus:
    """Honest status report of the active secret storage backend."""

    backend: str
    secure: bool
    detail: str


class SecretStore(Protocol):
    """Protocol implemented by OS and in-memory secret backends."""

    def get(self, ref: str) -> str | None: ...

    def set(self, ref: str, value: str) -> None: ...

    def delete(self, ref: str) -> None: ...

    def status(self) -> SecretStorageStatus: ...


def is_secret_ref(value: Any) -> bool:
    """Return True when ``value`` is a canonical ``secret_ref:...`` placeholder."""
    return (
        isinstance(value, str)
        and value.startswith(SECRET_REF_PREFIX)
        and len(value) > len(SECRET_REF_PREFIX)
    )


def make_secret_ref(namespace: str, *parts: str) -> str:
    """Build a canonical opaque secret reference key."""
    cleaned_ns = str(namespace or "").strip().strip(":")
    cleaned_parts = [str(part).strip().strip(":") for part in parts if str(part or "").strip()]
    if not cleaned_ns or not cleaned_parts:
        raise ValueError("Secret reference requires a non-empty namespace and key parts")
    return f"{SECRET_REF_PREFIX}{cleaned_ns}:{':'.join(cleaned_parts)}"


def _encode_secret_for_transport(secret: str) -> str:
    encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
    return f"{_B64_VALUE_PREFIX}{encoded}"


def _decode_secret_from_transport(raw: str) -> str:
    if raw.startswith(_B64_VALUE_PREFIX):
        payload = raw[len(_B64_VALUE_PREFIX) :]
        try:
            return base64.b64decode(payload.encode("ascii")).decode("utf-8")
        except Exception:
            return raw
    return raw


class InMemorySecretStore:
    """Thread-safe in-memory SecretStore used by tests and isolated harnesses."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[str, str] = {}

    def get(self, ref: str) -> str | None:
        with self._lock:
            return self._items.get(ref)

    def set(self, ref: str, value: str) -> None:
        if not is_secret_ref(ref):
            raise ValueError(f"Invalid secret ref: {ref!r}")
        with self._lock:
            self._items[ref] = str(value)

    def delete(self, ref: str) -> None:
        with self._lock:
            self._items.pop(ref, None)

    def status(self) -> SecretStorageStatus:
        return SecretStorageStatus(
            backend="memory",
            secure=True,
            detail="In-memory secret store (test/isolated mode)",
        )


def _service_name_for_home(magi_home: Path | None = None) -> str:
    home = (magi_home or get_magi_home()).resolve()
    default_home = (Path.home() / ".magi").resolve()
    if home == default_home:
        return "com.magi.secrets"
    digest = hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:12]
    return f"com.magi.secrets.{digest}"


def _env_var_name_for_ref(ref: str) -> str:
    body = ref[len(SECRET_REF_PREFIX) :] if ref.startswith(SECRET_REF_PREFIX) else ref
    normalized = _ENV_KEY_SANITIZE_RE.sub("_", body).strip("_").upper()
    return f"MAGI_SECRET_{normalized}"


class _ProtectedFileFallbackStore:
    """Explicit 0o600 protected fallback for headless environments without OS keyring."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()

    def _read_all(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except Exception as exc:
            raise SecretStoreError(f"Failed to read fallback secret store: {exc}") from exc

    def _write_all(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        try:
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                raise
            os.replace(tmp_path, self._path)
            if os.name != "nt":
                os.chmod(self._path, 0o600)
        finally:
            tmp_path.unlink(missing_ok=True)

    def get(self, ref: str) -> str | None:
        env_val = os.environ.get(_env_var_name_for_ref(ref))
        if env_val is not None:
            return env_val
        with self._lock:
            return self._read_all().get(ref)

    def set(self, ref: str, value: str) -> None:
        with self._lock:
            data = self._read_all()
            data[ref] = value
            self._write_all(data)

    def delete(self, ref: str) -> None:
        with self._lock:
            data = self._read_all()
            if ref in data:
                del data[ref]
                self._write_all(data)


class OSSecretStore:
    """Platform-native OS credential store with explicit Linux headless fallback."""

    def __init__(self, *, magi_home: Path | None = None) -> None:
        self._magi_home = magi_home
        self._lock = RLock()

    def _service_name(self) -> str:
        return _service_name_for_home(self._magi_home)

    def _fallback_store(self) -> _ProtectedFileFallbackStore:
        home = self._magi_home or get_magi_home()
        return _ProtectedFileFallbackStore(home / "runtime" / "secrets.fallback.json")

    def status(self) -> SecretStorageStatus:
        if sys.platform == "darwin" and Path("/usr/bin/security").exists():
            return SecretStorageStatus(
                backend="macos_keychain",
                secure=True,
                detail="macOS Keychain Services",
            )
        if sys.platform == "win32":
            return SecretStorageStatus(
                backend="windows_credential_manager",
                secure=True,
                detail="Windows Credential Manager",
            )
        if self._linux_secret_tool_available():
            return SecretStorageStatus(
                backend="linux_secret_service",
                secure=True,
                detail="Linux Secret Service (secret-tool)",
            )
        return SecretStorageStatus(
            backend="protected_file_fallback",
            secure=False,
            detail=(
                "OS secret service unavailable; using environment variables or "
                "0600-restricted runtime fallback file"
            ),
        )

    @staticmethod
    def _linux_secret_tool_available() -> bool:
        return bool(
            sys.platform.startswith("linux")
            and os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            and shutil.which("secret-tool")
        )

    def get(self, ref: str) -> str | None:
        env_val = os.environ.get(_env_var_name_for_ref(ref))
        if env_val is not None:
            return env_val
        with self._lock:
            if sys.platform == "darwin" and Path("/usr/bin/security").exists():
                return self._macos_get(ref)
            if sys.platform == "win32":
                return self._windows_get(ref)
            if self._linux_secret_tool_available():
                return self._linux_get(ref)
            return self._fallback_store().get(ref)

    def set(self, ref: str, value: str) -> None:
        if not is_secret_ref(ref):
            raise ValueError(f"Invalid secret ref: {ref!r}")
        with self._lock:
            if sys.platform == "darwin" and Path("/usr/bin/security").exists():
                self._macos_set(ref, value)
                return
            if sys.platform == "win32":
                self._windows_set(ref, value)
                return
            if self._linux_secret_tool_available():
                self._linux_set(ref, value)
                return
            self._fallback_store().set(ref, value)

    def delete(self, ref: str) -> None:
        with self._lock:
            if sys.platform == "darwin" and Path("/usr/bin/security").exists():
                self._macos_delete(ref)
                return
            if sys.platform == "win32":
                self._windows_delete(ref)
                return
            if self._linux_secret_tool_available():
                self._linux_delete(ref)
                return
            self._fallback_store().delete(ref)

    # ------------------------------------------------------------------
    # macOS Keychain via /usr/bin/security (stdin mode avoids argv leaks)
    # ------------------------------------------------------------------
    def _macos_get(self, ref: str) -> str | None:
        proc = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                self._service_name(),
                "-a",
                ref,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 44:  # errSecItemNotFound
            return None
        if proc.returncode != 0:
            raise SecretStoreError(
                f"macOS Keychain lookup failed (exit={proc.returncode}): {proc.stderr.strip()}"
            )
        raw = proc.stdout.rstrip("\r\n")
        return _decode_secret_from_transport(raw)

    def _macos_set(self, ref: str, value: str) -> None:
        encoded = _encode_secret_for_transport(value)
        # Interactive stdin avoids exposing the secret in process argv.
        script_line = (
            f'add-generic-password -U -s "{self._service_name()}" '
            f'-a "{ref}" -w "{encoded}"\n'
        )
        proc = subprocess.run(
            ["/usr/bin/security", "-i"],
            input=script_line,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SecretStoreError(
                f"macOS Keychain write failed (exit={proc.returncode}): {proc.stderr.strip()}"
            )

    def _macos_delete(self, ref: str) -> None:
        proc = subprocess.run(
            [
                "/usr/bin/security",
                "delete-generic-password",
                "-s",
                self._service_name(),
                "-a",
                ref,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode not in (0, 44):
            raise SecretStoreError(
                f"macOS Keychain delete failed (exit={proc.returncode}): {proc.stderr.strip()}"
            )

    # ------------------------------------------------------------------
    # Linux Secret Service via secret-tool
    # ------------------------------------------------------------------
    def _linux_get(self, ref: str) -> str | None:
        proc = subprocess.run(
            ["secret-tool", "lookup", "service", self._service_name(), "account", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        return _decode_secret_from_transport(proc.stdout.rstrip("\r\n"))

    def _linux_set(self, ref: str, value: str) -> None:
        encoded = _encode_secret_for_transport(value)
        proc = subprocess.run(
            [
                "secret-tool",
                "store",
                "--label",
                f"Magi ({ref})",
                "service",
                self._service_name(),
                "account",
                ref,
            ],
            input=encoded,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SecretStoreError(
                f"Linux secret-tool write failed (exit={proc.returncode}): {proc.stderr.strip()}"
            )

    def _linux_delete(self, ref: str) -> None:
        subprocess.run(
            ["secret-tool", "clear", "service", self._service_name(), "account", ref],
            capture_output=True,
            text=True,
            check=False,
        )

    # ------------------------------------------------------------------
    # Windows Credential Manager via ctypes advapi32.dll
    # ------------------------------------------------------------------
    def _windows_target_name(self, ref: str) -> str:
        return f"{self._service_name()}/{ref}"

    def _windows_get(self, ref: str) -> str | None:
        import ctypes
        from ctypes import wintypes

        class _CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        cred_ptr = ctypes.POINTER(_CREDENTIALW)()
        target = self._windows_target_name(ref)
        ok = advapi32.CredReadW(target, 1, 0, ctypes.byref(cred_ptr))
        if not ok:
            err = ctypes.get_last_error()
            if err == 1168:  # ERROR_NOT_FOUND
                return None
            raise SecretStoreError(f"Windows CredReadW failed (error={err})")
        try:
            size = int(cred_ptr.contents.CredentialBlobSize)
            raw_bytes = bytes(cred_ptr.contents.CredentialBlob[:size])
            return _decode_secret_from_transport(raw_bytes.decode("utf-8"))
        finally:
            advapi32.CredFree(cred_ptr)

    def _windows_set(self, ref: str, value: str) -> None:
        import ctypes
        from ctypes import wintypes

        class _CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        encoded_bytes = _encode_secret_for_transport(value).encode("utf-8")
        blob = (ctypes.c_ubyte * len(encoded_bytes))(*encoded_bytes)
        cred = _CREDENTIALW(
            Flags=0,
            Type=1,  # CRED_TYPE_GENERIC
            TargetName=self._windows_target_name(ref),
            Comment=None,
            CredentialBlobSize=len(encoded_bytes),
            CredentialBlob=blob,
            Persist=2,  # CRED_PERSIST_LOCAL_MACHINE
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName=ref,
        )
        ok = advapi32.CredWriteW(ctypes.byref(cred), 0)
        if not ok:
            err = ctypes.get_last_error()
            raise SecretStoreError(f"Windows CredWriteW failed (error={err})")

    def _windows_delete(self, ref: str) -> None:
        import ctypes

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        ok = advapi32.CredDeleteW(self._windows_target_name(ref), 1, 0)
        if not ok:
            err = ctypes.get_last_error()
            if err != 1168:  # ERROR_NOT_FOUND
                raise SecretStoreError(f"Windows CredDeleteW failed (error={err})")


_STORE_LOCK = RLock()
_ACTIVE_SECRET_STORE: SecretStore | None = None


def get_secret_store() -> SecretStore:
    """Return the active process-wide SecretStore (honoring MAGI_SECRET_STORE=memory)."""
    global _ACTIVE_SECRET_STORE
    with _STORE_LOCK:
        if _ACTIVE_SECRET_STORE is not None:
            return _ACTIVE_SECRET_STORE
        if os.environ.get("MAGI_SECRET_STORE", "").strip().lower() == "memory":
            _ACTIVE_SECRET_STORE = InMemorySecretStore()
        else:
            _ACTIVE_SECRET_STORE = OSSecretStore()
        return _ACTIVE_SECRET_STORE


def set_secret_store(store: SecretStore | None) -> None:
    """Override or reset the process-wide SecretStore (used by tests and bootstrap)."""
    global _ACTIVE_SECRET_STORE
    with _STORE_LOCK:
        _ACTIVE_SECRET_STORE = store


@contextmanager
def override_secret_store(store: SecretStore) -> Iterator[SecretStore]:
    """Temporarily replace the active SecretStore within a context block."""
    with _STORE_LOCK:
        previous = _ACTIVE_SECRET_STORE
        set_secret_store(store)
    try:
        yield store
    finally:
        set_secret_store(previous)


__all__ = [
    "InMemorySecretStore",
    "OSSecretStore",
    "SECRET_REF_PREFIX",
    "SecretStorageStatus",
    "SecretStore",
    "SecretStoreError",
    "get_secret_store",
    "is_secret_ref",
    "make_secret_ref",
    "override_secret_store",
    "set_secret_store",
]
