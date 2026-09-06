"""Supervised external-plugin process and synchronous bootstrap adapter.

This module never imports an external package. The host owns the executable,
identity, context paths and broker; the child owns every plugin Python object.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
import inspect
import json
import os
from pathlib import Path
from queue import Queue, Full
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Sequence
import uuid

from magi_plugin_sdk.base import Plugin
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.contracts import PluginManifest
from magi_plugin_sdk.runtime import (
    InvocationIdentity,
    PluginConnection,
    PluginHandshake,
    SDK_VERSION,
)
from magi_plugin_sdk.transport import (
    MAX_FRAME_BYTES,
    ProtocolError,
    pack,
    read_frame,
    write_frame,
    WorkerRuntimePaths,
)
from magi_plugin_sdk.worker_catalog import CHANNEL_PORTS

from .process_broker import CapabilityBroker, CapabilityDenied
from .process_confinement import plan_confinement


class PluginProcessError(RuntimeError):
    """The worker exited, violated the protocol or failed an invocation."""


class PluginProcessTimeout(PluginProcessError, TimeoutError):
    """The invocation deadline expired; external effects may be uncertain."""


@dataclass(frozen=True)
class ProcessLimits:
    startup_timeout: float = 20.0
    request_timeout: float = 30.0
    cancellation_grace: float = 0.5
    drain_timeout: float = 3.0
    callback_timeout: float = 20.0
    max_inflight: int = 16
    max_frame_bytes: int = MAX_FRAME_BYTES
    max_stderr_bytes: int = 16 * 1024

    def __post_init__(self) -> None:
        if not all(
            0 < value <= 3600
            for value in (
                self.startup_timeout,
                self.request_timeout,
                self.cancellation_grace,
                self.drain_timeout,
                self.callback_timeout,
            )
        ):
            raise ValueError("Process deadlines must be positive and bounded")
        if (
            not 1 <= self.max_inflight <= 128
            or not 1024 <= self.max_frame_bytes <= MAX_FRAME_BYTES
            or not 0 <= self.max_stderr_bytes <= MAX_FRAME_BYTES
        ):
            raise ValueError("Invalid worker resource bounds")


@dataclass
class _Invocation:
    future: Future[Any]
    identity: InvocationIdentity
    loop: asyncio.AbstractEventLoop | None
    deadline: float
    bootstrap: bool = False
    progress: Any = None


def _interpreter_paths(executable: str) -> dict[str, Any]:
    probe = (
        "import json,sys,sysconfig;from pathlib import Path;"
        "exe=Path(sys.executable).absolute();"
        "venv=next((p for p in (exe.parent,exe.parent.parent) if (p/'pyvenv.cfg').is_file()),None);"
        "paths=sysconfig.get_paths(vars={'base':str(venv),'platbase':str(venv)}) if venv else sysconfig.get_paths();"
        "print(json.dumps({'paths':list(dict.fromkeys([paths['purelib'],paths['platlib']])), 'stdlib':sysconfig.get_path('stdlib'), 'prefix':sys.base_prefix, 'executable':sys.executable}))"
    )
    try:
        completed = subprocess.run(
            [executable, "-I", "-S", "-c", probe],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            env=_worker_environment(),
        )
        return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise PluginProcessError("Plugin Python runtime is unavailable") from exc


def _worker_environment() -> dict[str, str]:
    # Never inherit provider keys, session credentials, PYTHONPATH, loader hooks,
    # proxy settings or other host authority from the desktop environment.
    return {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "TZ"}
    }


class ProcessPluginProxy(Plugin):
    """Drop-in Plugin contribution proxy with bounded synchronous bootstrap."""

    def __init__(
        self,
        manifest: PluginManifest,
        connection: PluginConnection,
        context: PluginContext,
        *,
        python_executable: str | Path | None = None,
        dependency_paths: Sequence[str | Path] = (),
        broker: CapabilityBroker | None = None,
        limits: ProcessLimits | None = None,
    ) -> None:
        super().__init__()
        self.configure(manifest=manifest, connection=connection, context=context)
        self.limits = limits or ProcessLimits()
        self.broker = broker or CapabilityBroker(connection)
        if self.broker.connection != connection:
            raise ValueError("Worker broker connection mismatch")
        self._pending: dict[str, _Invocation] = {}
        self._cancelled: dict[str, _Invocation] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._draining = False
        self._failure: str | None = None
        self._stderr = bytearray()
        self._callback_slots = threading.BoundedSemaphore(self.limits.max_inflight)
        self._callbacks = ThreadPoolExecutor(
            max_workers=min(4, self.limits.max_inflight), thread_name_prefix="plugin-broker"
        )
        self._outbox: Queue[bytes | None] = Queue(maxsize=self.limits.max_inflight * 2)
        self._channel_ports: dict[str, Any] = {}
        self._channel_loop: asyncio.AbstractEventLoop | None = None
        self._channel_active = False
        self._channel_contexts: list[Any] = []
        self._channel_sessions: dict[str, Any] = {}
        self._catalog: dict[str, Any] = {}
        self._process: subprocess.Popen[bytes] | None = None
        self._windows_job: Any = None
        self._probe_path: Path | None = None
        self._source_cache: Any = None
        self._tool_cache: Any = None
        self._channel_cache: Any = None
        try:
            self._launch(python_executable, dependency_paths)
        except BaseException:
            self._terminate("Plugin worker startup failed")
            raise

    def _launch(
        self, python_executable: str | Path | None, dependency_paths: Sequence[str | Path]
    ) -> None:
        executable = str(
            python_executable
            or os.environ.get("MAGI_PLUGIN_PYTHON")
            or ("" if getattr(sys, "frozen", False) else sys.executable)
        )
        if not executable:
            raise PluginProcessError("Bundled plugin Python executable was not configured")
        runtime = _interpreter_paths(executable)
        sdk_roots = []
        if not getattr(sys, "frozen", False):
            import magi_plugin_sdk

            sdk_roots.append(str(Path(magi_plugin_sdk.__file__).resolve().parent.parent))
        # -S avoids sitecustomize and executable .pth files. Plugin dependencies
        # are inserted only after trusted SDK import inside the child.
        import_roots = list(dict.fromkeys([*sdk_roots, *runtime["paths"]]))
        launch_code = f"import sys;sys.path[:0]={import_roots!r};from magi_plugin_sdk.worker import main;main()"
        command = [executable, "-I", "-S", "-u", "-c", launch_code]
        state_dir, resources_dir = (
            self.context.state_dir.resolve(),
            self.context.resources_dir.resolve(),
        )
        for path in (state_dir, resources_dir):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        dependencies = [Path(p).resolve() for p in dependency_paths]
        root = Path(self.manifest.plugin_dir).resolve()
        read_roots = [
            Path(runtime["stdlib"]),
            Path(runtime["executable"]).resolve(),
            *map(Path, import_roots),
            root,
            *dependencies,
        ]
        # Native extension shared libraries can be adjacent to the runtime.
        runtime_lib = Path(runtime["prefix"]) / "lib"
        if runtime_lib.is_dir():
            read_roots.append(runtime_lib)
        self._confinement = plan_confinement(
            command,
            mode=self.manifest.execution_mode,
            read_roots=read_roots,
            state_dir=state_dir,
            resources_dir=resources_dir,
        )
        if self._confinement.filesystem_confined:
            fd, probe_name = tempfile.mkstemp(prefix="magi-confinement-")
            os.write(fd, b"confinement probe")
            os.close(fd)
            self._probe_path = Path(probe_name)
        env = _worker_environment()
        source_home = (
            Path.home() if self.manifest.execution_mode == "trusted_process" else state_dir
        )
        env.update(
            {
                "HOME": str(source_home),
                "TMPDIR": str(resources_dir),
                "TEMP": str(resources_dir),
                "TMP": str(resources_dir),
            }
        )
        options: dict[str, Any] = (
            {"start_new_session": True}
            if os.name != "nt"
            else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            }
        )
        self._process = subprocess.Popen(
            self._confinement.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=state_dir,
            env=env,
            bufsize=0,
            **options,
        )
        if os.name == "nt":
            from .process_windows import WindowsWorkerJob

            # The SDK worker cannot import plugin code until initialize arrives.
            self._windows_job = WindowsWorkerJob(int(self._process._handle))
        for name, target in (
            ("writer", self._write_loop),
            ("reader", self._read_loop),
            ("stderr", self._stderr_loop),
        ):
            threading.Thread(
                target=target, name=f"plugin-{self.connection.connection_id}-{name}", daemon=True
            ).start()
        handshake = PluginHandshake(
            protocol_version=2,
            sdk_version=SDK_VERSION,
            plugin_id=self.plugin_id,
            connection_id=self.connection.connection_id,
        )
        try:
            result = self._request_sync(
                "initialize",
                {
                    "handshake": handshake,
                    "manifest": self.manifest,
                    "connection": self.connection,
                    "state_dir": state_dir,
                    "resources_dir": resources_dir,
                    "dependency_paths": dependencies,
                    "max_inflight": self.limits.max_inflight,
                    "callback_timeout": self.limits.callback_timeout,
                    "confinement": self._confinement.mechanism,
                    "probe_path": self._probe_path,
                },
                timeout=self.limits.startup_timeout,
                bootstrap=True,
            )
            if result["handshake"] != handshake or (
                self._confinement.filesystem_confined and not result["confinement_verified"]
            ):
                raise ProtocolError("Worker handshake or confinement validation failed")
            self._catalog = result["catalog"]
        finally:
            if self._probe_path:
                self._probe_path.unlink(missing_ok=True)
                self._probe_path = None

    @property
    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pid": self._process.pid if self._process else None,
                "execution_mode": self.manifest.execution_mode,
                "mechanism": self._confinement.mechanism,
                "filesystem_confined": self._confinement.filesystem_confined,
                "network_confined": self._confinement.network_confined,
                "description": self._confinement.description,
                "healthy": not self._closed
                and self._process is not None
                and self._process.poll() is None,
                "draining": self._draining,
                "pending": len(self._pending),
                "last_error": self._failure,
                "exit_code": self._process.poll() if self._process else None,
            }

    def _identity(self) -> InvocationIdentity:
        return InvocationIdentity(
            invocation_id=uuid.uuid4().hex,
            plugin_id=self.plugin_id,
            connection_id=self.connection.connection_id,
            principal_id="plugin-system",
            trigger="system",
        )

    def _begin(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout: float,
        identity: InvocationIdentity | None,
        loop: asyncio.AbstractEventLoop | None,
        bootstrap: bool = False,
        allow_drain: bool = False,
        progress: Any = None,
    ) -> tuple[str, Future[Any]]:
        identity = identity or self._identity()
        if (
            identity.connection_id != self.connection.connection_id
            or identity.plugin_id != self.plugin_id
        ):
            raise CapabilityDenied("Invocation identity does not belong to worker")
        identifier, future = uuid.uuid4().hex, Future()
        data = pack(
            {"kind": "request", "id": identifier, "method": method, "payload": payload},
            self.limits.max_frame_bytes,
        )
        with self._lock:
            if self._closed or (self._draining and not allow_drain):
                raise PluginProcessError("Plugin worker is not accepting work")
            if len(self._pending) + len(self._cancelled) >= self.limits.max_inflight:
                raise PluginProcessError("Plugin worker request capacity exhausted")
            self._pending[identifier] = _Invocation(
                future, identity, loop, time.monotonic() + timeout, bootstrap, progress
            )
            try:
                self._outbox.put_nowait(data)
            except Full:
                self._pending.pop(identifier, None)
                raise PluginProcessError("Plugin worker transport capacity exhausted") from None
        return identifier, future

    def _request_sync(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
        bootstrap: bool = False,
    ) -> Any:
        duration = timeout or self.limits.request_timeout
        identifier, future = self._begin(
            method, payload, timeout=duration, identity=None, loop=None, bootstrap=bootstrap
        )
        try:
            return future.result(timeout=duration)
        except FutureTimeout:
            self._cancel(identifier)
            raise PluginProcessTimeout(
                "Plugin worker request timed out; effects may be uncertain"
            ) from None
        finally:
            with self._lock:
                self._pending.pop(identifier, None)

    async def request(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        identity: InvocationIdentity | None = None,
        timeout: float | None = None,
        allow_drain: bool = False,
        progress: Any = None,
    ) -> Any:
        duration = timeout or self.limits.request_timeout
        identifier, future = self._begin(
            method,
            payload,
            timeout=duration,
            identity=identity,
            loop=asyncio.get_running_loop(),
            allow_drain=allow_drain,
            progress=progress,
        )
        wrapped = asyncio.wrap_future(future)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), duration)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            wrapped.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
            self._cancel(identifier)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise PluginProcessTimeout(
                "Plugin worker request timed out; effects may be uncertain"
            ) from None
        finally:
            with self._lock:
                self._pending.pop(identifier, None)

    async def invoke(
        self,
        target: str,
        method: str,
        *args: Any,
        identity: InvocationIdentity | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        from magi_plugin_sdk.tools import ToolExecutionContext

        progress = next(
            (
                value.progress
                for value in (*args, *kwargs.values())
                if isinstance(value, ToolExecutionContext) and callable(value.progress)
            ),
            None,
        )
        return await self.request(
            "invoke",
            {
                "target": target,
                "method": method,
                "args": self._safe_args(args),
                "kwargs": self._safe_args(kwargs),
                "progress": progress is not None,
            },
            identity=identity,
            timeout=timeout,
            progress=progress,
        )

    def invoke_sync(self, target: str, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._request_sync(
            "invoke",
            {
                "target": target,
                "method": method,
                "args": self._safe_args(args),
                "kwargs": self._safe_args(kwargs),
            },
        )

    async def iter_stream(
        self,
        target: str,
        request: Any,
        *,
        identity: InvocationIdentity | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Pull one bounded chunk at a time; never accumulate a remote stream."""
        identity = identity or self._identity()
        duration = timeout or self.limits.request_timeout
        deadline = time.monotonic() + duration
        opened = await self.request(
            "stream_open",
            {"target": target, "method": "stream", "request": request},
            identity=identity,
            timeout=duration,
        )
        stream_id = opened["stream_id"]
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PluginProcessTimeout("Provider stream deadline expired")
                chunk = await self.request(
                    "stream_next", {"stream_id": stream_id}, identity=identity, timeout=remaining
                )
                if chunk["done"]:
                    return
                yield chunk["item"]
        finally:
            if not self._closed and not self._draining:
                try:
                    await asyncio.shield(
                        self.request(
                            "stream_close",
                            {"stream_id": stream_id},
                            identity=identity,
                            timeout=self.limits.cancellation_grace,
                        )
                    )
                except (PluginProcessError, asyncio.CancelledError):
                    self._terminate("Provider stream did not close")

    def _safe_args(self, value: Any) -> Any:
        from magi_plugin_sdk.sources import SourceSyncContext
        from magi_plugin_sdk.tools import ToolExecutionContext
        from magi_plugin_sdk.user_content import UserContentClearContext

        if isinstance(value, (SourceSyncContext, UserContentClearContext)):
            return replace(value, runtime_paths=WorkerRuntimePaths(self.context.state_dir))
        if isinstance(value, ToolExecutionContext):
            return value.model_copy(
                update={
                    "capabilities": None,
                    "cancellation": None,
                    "trace_context": None,
                    "progress": None,
                    "env_vars": {},
                }
            )
        if isinstance(value, (list, tuple)):
            return type(value)(self._safe_args(item) for item in value)
        if isinstance(value, dict):
            return {key: self._safe_args(item) for key, item in value.items()}
        return value

    def _cancel(self, identifier: str) -> None:
        with self._lock:
            call = self._pending.pop(identifier, None)
            if call is not None:
                self._cancelled[identifier] = call
        if call is None:
            return
        self._send({"kind": "cancel", "id": identifier})

        # Revoke admission immediately. A child ignoring cancellation is killed
        # after grace; its unknown side effects are never reported as success.
        def enforce() -> None:
            if not call.future.done():
                self._terminate("Plugin worker ignored cancellation")
            with self._lock:
                self._cancelled.pop(identifier, None)

        timer = threading.Timer(self.limits.cancellation_grace, enforce)
        timer.daemon = True
        timer.start()

    def _send(self, message: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            self._outbox.put_nowait(pack(message, self.limits.max_frame_bytes))
        except (Full, ProtocolError):
            self._terminate("Plugin worker transport capacity exceeded")

    def _write_loop(self) -> None:
        try:
            while not self._closed:
                frame = self._outbox.get()
                if frame is None:
                    return
                write_frame(self._process.stdin, frame)
        except (EOFError, OSError, ValueError):
            self._terminate("Plugin worker input closed")

    def _read_loop(self) -> None:
        try:
            while not self._closed:
                frame = read_frame(self._process.stdout, self.limits.max_frame_bytes)
                if frame.get("kind") == "response":
                    with self._lock:
                        call = self._pending.get(frame.get("id")) or self._cancelled.get(
                            frame.get("id")
                        )
                    if call and not call.future.done():
                        if frame.get("ok") is True:
                            call.future.set_result(frame.get("result"))
                        else:
                            call.future.set_exception(
                                PluginProcessError(
                                    str(frame.get("error", "Plugin invocation failed"))[:2048]
                                )
                            )
                elif frame.get("kind") == "callback":
                    if not self._callback_slots.acquire(blocking=False):
                        raise ProtocolError("Plugin callback capacity exceeded")
                    self._callbacks.submit(self._dispatch_callback, frame)
                else:
                    raise ProtocolError("Unknown worker frame kind")
        except (EOFError, OSError, ProtocolError, RuntimeError, TypeError, KeyError):
            self._terminate("Plugin worker exited or violated the protocol")

    def _stderr_loop(self) -> None:
        try:
            while True:
                chunk = self._process.stderr.read(4096)
                if not chunk:
                    return
                with self._lock:
                    remaining = self.limits.max_stderr_bytes - len(self._stderr)
                    if remaining > 0:
                        self._stderr.extend(chunk[:remaining])
        except (OSError, ValueError):
            return

    def _dispatch_callback(self, frame: dict[str, Any]) -> None:
        try:
            result = self._callback(frame)
            self._send({"kind": "callback_result", "id": frame["id"], "ok": True, "result": result})
        except Exception as exc:
            # Host exception details can contain credentials or internal paths.
            self._send(
                {
                    "kind": "callback_result",
                    "id": frame.get("id"),
                    "ok": False,
                    "error": f"Host callback rejected: {type(exc).__name__}",
                }
            )
        finally:
            self._callback_slots.release()

    def _callback(self, frame: dict[str, Any]) -> Any:
        with self._lock:
            call = self._pending.get(frame.get("parent"))
            if self._closed or self._draining:
                raise CapabilityDenied("Worker connection is draining")
        kind, payload = frame.get("callback"), frame.get("payload", {})
        if kind == "channel":
            return self._channel_callback(payload)
        if call is None or call.deadline <= time.monotonic() or call.future.done():
            raise CapabilityDenied("Worker callback has no active invocation")
        if kind == "credential":
            method, key, value = payload.get("method"), payload.get("key"), payload.get("value")
            if (
                set(payload) != {"method", "key", "value"}
                or method not in {"get", "set", "delete"}
                or not isinstance(key, str)
                or not key
                or len(key) > 256
            ):
                raise CapabilityDenied("Invalid scoped credential operation")
            if method == "set":
                if not isinstance(value, str) or len(value) > 65536:
                    raise CapabilityDenied("Invalid scoped credential value")
                return self.context.credentials.set(key, value)
            return getattr(self.context.credentials, method)(key)
        if kind == "progress":
            if (
                call.loop is None
                or not callable(call.progress)
                or set(payload) != {"value"}
                or not isinstance(payload["value"], dict)
            ):
                raise CapabilityDenied("Progress publisher was not bound to this invocation")

            async def publish() -> Any:
                value = call.progress(payload["value"])
                return await value if inspect.isawaitable(value) else value

            future = asyncio.run_coroutine_threadsafe(publish(), call.loop)
            try:
                return future.result(
                    timeout=min(
                        self.limits.callback_timeout, max(0.001, call.deadline - time.monotonic())
                    )
                )
            except FutureTimeout:
                future.cancel()
                raise CapabilityDenied("Progress callback deadline expired") from None
        if kind != "capability" or call.bootstrap or call.loop is None:
            raise CapabilityDenied("Host capability requires an active asynchronous invocation")
        operation = self.broker.invoke(
            call.identity, payload["capability"], payload["resource"], payload.get("payload")
        )
        future = asyncio.run_coroutine_threadsafe(operation, call.loop)
        try:
            return future.result(
                timeout=min(
                    self.limits.callback_timeout, max(0.001, call.deadline - time.monotonic())
                )
            )
        except FutureTimeout:
            future.cancel()
            raise CapabilityDenied("Host callback deadline expired") from None

    def bind_channel_port(self, name: str, port: Any) -> None:
        if name not in CHANNEL_PORTS:
            raise CapabilityDenied("Unknown channel port")
        self._channel_ports[name] = port

    async def start_channel(self) -> None:
        self._channel_loop = asyncio.get_running_loop()
        self._channel_active = True
        try:
            await self.request("bind_channel", {"ports": list(self._channel_ports)})
            await self.invoke("channel", "start")
        except BaseException:
            self._channel_active = False
            raise

    def _channel_callback(self, payload: dict[str, Any]) -> Any:
        if not self._channel_active or self._channel_loop is None:
            raise CapabilityDenied("Channel callback lease is inactive")
        port_name, method = payload.get("port"), payload.get("method")
        if port_name not in self._channel_ports or method not in CHANNEL_PORTS[port_name]:
            raise CapabilityDenied("Channel method is not bound")
        kwargs, args = dict(payload.get("kwargs", {})), tuple(payload.get("args", ()))
        channel_type = self._catalog["get_channel"]["channel_type"]
        host_channel_type = self.get_channel().channel_type
        if "channel_type" in kwargs and kwargs["channel_type"] != channel_type:
            raise CapabilityDenied("Channel callback type mismatch")
        if "channel_type" in kwargs:
            kwargs["channel_type"] = host_channel_type
        if (
            args
            and method
            in {"lookup", "delete_mapping", "get_notification_cursor", "update_notification_cursor"}
            and args[0] != channel_type
        ):
            raise CapabilityDenied("Channel callback type mismatch")
        if args and method in {
            "lookup",
            "delete_mapping",
            "get_notification_cursor",
            "update_notification_cursor",
        }:
            args = (host_channel_type, *args[1:])
        if "inbound_context" in kwargs and kwargs["inbound_context"] not in self._channel_contexts:
            raise CapabilityDenied("Channel callback requires host-issued inbound context")
        if method == "dispatch_user_message":
            if kwargs.get("source") != channel_type:
                raise CapabilityDenied("Channel message source mismatch")
            kwargs["source"] = host_channel_type
        if method in {"dispatch_user_message", "handle_command", "store_attachment"}:
            session_id = kwargs.get("session_id")
            mapping = self._channel_sessions.get(session_id)
            if mapping is None:
                raise CapabilityDenied(
                    "Channel callback requires a session owned by this connection"
                )
            if "user_id" in kwargs and kwargs["user_id"] != mapping.magi_user_id:
                raise CapabilityDenied("Channel principal does not match its session")

        async def invoke() -> Any:
            result = getattr(self._channel_ports[port_name], method)(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        future = asyncio.run_coroutine_threadsafe(invoke(), self._channel_loop)
        try:
            result = future.result(timeout=self.limits.callback_timeout)
        except FutureTimeout:
            future.cancel()
            raise CapabilityDenied("Channel callback deadline expired") from None
        if method == "capture_inbound_context":
            if result.channel_type != host_channel_type:
                raise CapabilityDenied("Inbound context belongs to another connection")
            self._channel_contexts.append(result)
            del self._channel_contexts[:-1024]
        if (
            port_name == "session_mapper"
            and method in {"lookup", "lookup_by_session", "resolve_or_create"}
            and result is not None
        ):
            if result.channel_type != host_channel_type:
                raise CapabilityDenied("Session mapping belongs to another connection")
            if len(self._channel_sessions) >= 1024:
                self._channel_sessions.pop(next(iter(self._channel_sessions)))
            self._channel_sessions[result.magi_session_id] = result
            return replace(result, channel_type=channel_type)
        return result

    def _terminate(self, reason: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._channel_active = False
            self._failure = reason
            pending = [*self._pending.values(), *self._cancelled.values()]
            self._pending.clear()
            self._cancelled.clear()
        self.broker.close()
        try:
            self._outbox.put_nowait(None)
        except Full:
            pass
        process = self._process
        if self._windows_job is not None:
            self._windows_job.close()
        if process is not None:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                elif process.poll() is None:
                    process.kill()
            except (ProcessLookupError, PermissionError):
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        for call in pending:
            if not call.future.done():
                call.future.set_exception(PluginProcessError(reason or "Plugin worker stopped"))
        self._callbacks.shutdown(wait=False, cancel_futures=True)

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._draining = True
        self._channel_active = False
        deadline = time.monotonic() + self.limits.drain_timeout
        while self._pending and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        try:
            await self.request(
                "invoke",
                {"target": "plugin", "method": "shutdown", "args": (), "kwargs": {}},
                timeout=max(0.01, deadline - time.monotonic()),
                allow_drain=True,
            )
        except (PluginProcessError, asyncio.CancelledError):
            pass
        finally:
            self._terminate()

    def get_tools(self) -> list[type[Any]]:
        from .process_proxies import tool_proxy_type

        if self._tool_cache is None:
            self._tool_cache = [tool_proxy_type(self, item) for item in self._catalog["get_tools"]]
        return self._tool_cache

    def get_operations(self) -> list[Any]:
        return self._catalog["get_operations"]

    def get_providers(self) -> list[Any]:
        from .process_proxies import WebSearchProviderProxy, ProtocolProviderProxy

        return [
            (
                item["kind"],
                item["id"],
                (WebSearchProviderProxy if item["kind"] == "web_search" else ProtocolProviderProxy)(
                    self, item
                ),
            )
            for item in self._catalog["get_providers"]
        ]

    async def invoke_operation(
        self, operation_id: str, arguments: dict[str, Any], identity: InvocationIdentity
    ) -> Any:
        return await self.invoke(
            "plugin", "invoke_operation", operation_id, arguments, identity, identity=identity
        )

    def get_sources(self) -> list[Any]:
        from .process_proxies import SourceProxy

        if self._source_cache is None:
            self._source_cache = [
                (item["id"], SourceProxy(self, item), item["spec"])
                for item in self._catalog["get_sources"]
            ]
        return self._source_cache

    def get_channel(self) -> Any:
        from .process_proxies import ChannelProxy

        if self._catalog["get_channel"] is None:
            return None
        if self._channel_cache is None:
            self._channel_cache = ChannelProxy(self, self._catalog["get_channel"])
        return self._channel_cache

    def get_history_importers(self) -> list[Any]:
        from .process_proxies import AsyncObjectProxy

        return [
            (item["id"], AsyncObjectProxy(self, item["target"], {"parse"}), item["spec"])
            for item in self._catalog["get_history_importers"]
        ]

    def get_channel_fields(self) -> list[Any]:
        return self._catalog["get_channel_fields"]

    def get_settings_resources(self) -> list[Any]:
        return self._catalog["get_settings_resources"]

    def get_settings_actions(self) -> list[Any]:
        return self._catalog["get_settings_actions"]

    def get_summary_profiles(self) -> list[Any]:
        return self._catalog["get_summary_profiles"]

    def get_extraction_profiles(self) -> list[Any]:
        return self._catalog["get_extraction_profiles"]

    def get_skills(self) -> list[Any]:
        return self._catalog["get_skills"]

    def get_hooks(self) -> list[Any]:
        from .process_proxies import AsyncObjectProxy

        return [
            (
                item["event_type"],
                AsyncObjectProxy(self, item["target"], {"__call__"}).__call__,
                item["matcher"],
            )
            for item in self._catalog["get_hooks"]
        ]

    def read_settings_resource(self, resource_name: str) -> Any:
        return self.invoke_sync("plugin", "read_settings_resource", resource_name)

    async def read_settings_resource_async(
        self, resource_name: str, *, identity: InvocationIdentity | None = None
    ) -> Any:
        return await self.invoke(
            "plugin", "read_settings_resource", resource_name, identity=identity
        )

    async def start_settings_action(self, action_id: str, **kwargs: Any) -> Any:
        return await self.invoke("plugin", "start_settings_action", action_id, **kwargs)

    async def poll_settings_action(self, action_id: str, **kwargs: Any) -> Any:
        return await self.invoke("plugin", "poll_settings_action", action_id, **kwargs)

    async def cancel_settings_action(self, action_id: str, **kwargs: Any) -> Any:
        return await self.invoke("plugin", "cancel_settings_action", action_id, **kwargs)

    async def invoke_settings_action(
        self,
        phase: str,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None = None,
        identity: InvocationIdentity,
    ) -> Any:
        if phase not in {"start", "poll", "cancel"}:
            raise ValueError("Invalid settings action phase")
        kwargs: dict[str, Any] = {"session_id": session_id}
        if phase != "cancel":
            kwargs["field_values"] = field_values
        return await self.invoke(
            "plugin", f"{phase}_settings_action", action_id, identity=identity, **kwargs
        )

    def build_temporal_summary_features(self, **kwargs: Any) -> Any:
        return self.invoke_sync("plugin", "build_temporal_summary_features", **kwargs)

    async def clear_user_content(self, context: Any) -> None:
        await self.invoke("plugin", "clear_user_content", context)

    def get_plugin_ingress_registrations(self, *, runtime_paths: Any) -> list[Any]:
        from magi_plugin_sdk.ingress import PluginIngressHandlerRegistration
        from .process_proxies import IngressProxy

        entries = self._request_sync("ingress_catalog", {})
        return [
            PluginIngressHandlerRegistration(
                entry["plugin_target"], entry["event_type"], IngressProxy(self, entry["target"])
            )
            for entry in entries
        ]
