"""Supervised Python plugin worker. Run only through the host launcher.

The protocol input is not an API for arbitrary Python evaluation. Plugin code is
imported only after version agreement and the native confinement probe succeeds.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from contextvars import ContextVar
import importlib.util
import inspect
import os
from pathlib import Path
import socket
import sys
import threading
from typing import Any
import uuid

from .base import Plugin
from .context import PluginContext
from .runtime import PluginHandshake, PLUGIN_PROTOCOL_VERSION, SDK_VERSION
from .transport import (
    MAX_FRAME_BYTES,
    ProtocolError,
    pack,
    read_frame,
    write_frame,
    WorkerRuntimePaths,
)
from .worker_catalog import CHANNEL_PORTS, WorkerCatalog
from .worker_imports import install_library_imports

_request_id: ContextVar[str] = ContextVar("worker_request_id", default="bootstrap")
_host: WorkerHost | None = None


class RemoteHostError(RuntimeError):
    """The scoped host broker denied or failed a request."""


class WorkerHost:
    """The only worker-facing entry to explicitly granted host capabilities."""

    def __init__(self, server: WorkerServer) -> None:
        self.server = server

    async def call(self, capability: str, resource: str, payload: Any = None) -> Any:
        future = self.server.callback(
            "capability",
            {"capability": capability, "resource": resource, "payload": payload},
        )
        return await asyncio.wait_for(
            asyncio.wrap_future(future), self.server.callback_timeout
        )


class WorkerCredentials:
    """Synchronous scoped credential callbacks; no connection selector exists."""

    def __init__(self, server: WorkerServer) -> None:
        self._server = server

    def get(self, key: str) -> str | None:
        return self._call("get", key)

    def set(self, key: str, value: str) -> None:
        self._call("set", key, value)

    def delete(self, key: str) -> None:
        self._call("delete", key)

    def _call(self, method: str, key: str, value: str | None = None) -> Any:
        if not isinstance(key, str) or not key or len(key) > 256:
            raise ValueError("Credential key must be a nonempty bounded string")
        future = self._server.callback(
            "credential", {"method": method, "key": key, "value": value}
        )
        return future.result(timeout=self._server.callback_timeout)


class RemoteChannelPort:
    def __init__(self, server: WorkerServer, port: str) -> None:
        self.server, self.port = server, port

    def __getattr__(self, method: str) -> Any:
        if method not in CHANNEL_PORTS[self.port]:
            raise AttributeError(method)

        async def invoke(*args: Any, **kwargs: Any) -> Any:
            future = self.server.callback(
                "channel",
                {"port": self.port, "method": method, "args": args, "kwargs": kwargs},
                parent="channel",
            )
            return await asyncio.wait_for(
                asyncio.wrap_future(future), self.server.callback_timeout
            )

        return invoke


class WorkerProgress:
    def __init__(self, server: WorkerServer) -> None:
        self.server = server

    async def __call__(self, value: dict[str, Any]) -> None:
        future = self.server.callback("progress", {"value": value})
        await asyncio.wait_for(
            asyncio.wrap_future(future), self.server.callback_timeout
        )


def get_host() -> WorkerHost:
    """Return the worker's scoped host capability client."""
    if _host is None:
        raise RuntimeError(
            "Host capability client is only available inside a plugin worker"
        )
    return _host


class WorkerServer:
    def __init__(self, reader: Any, writer: Any) -> None:
        self.reader, self.writer = reader, writer
        self.write_lock = threading.Lock()
        self.callbacks: dict[str, Future[Any]] = {}
        self.callback_lock = threading.Lock()
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.catalog: WorkerCatalog | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.max_frame_bytes = MAX_FRAME_BYTES
        self.max_inflight = 16
        self.callback_timeout = 30.0
        self.stopping = False
        self.channel_boundaries: dict[str, Any] = {}
        self.streams: dict[str, Any] = {}
        self.stream_busy: set[str] = set()

    def send(self, message: dict[str, Any]) -> None:
        data = pack(message, self.max_frame_bytes)
        with self.write_lock:
            write_frame(self.writer, data)

    def callback(
        self, kind: str, payload: dict[str, Any], *, parent: str | None = None
    ) -> Future[Any]:
        identifier = uuid.uuid4().hex
        future: Future[Any] = Future()
        with self.callback_lock:
            if len(self.callbacks) >= self.max_inflight:
                raise RemoteHostError("Worker callback limit reached")
            self.callbacks[identifier] = future
        future.add_done_callback(lambda _: self._forget_callback(identifier))
        try:
            self.send(
                {
                    "kind": "callback",
                    "id": identifier,
                    "parent": parent or _request_id.get(),
                    "callback": kind,
                    "payload": payload,
                }
            )
        except BaseException:
            self._forget_callback(identifier)
            raise
        return future

    def _forget_callback(self, identifier: str) -> None:
        with self.callback_lock:
            self.callbacks.pop(identifier, None)

    def _reader(self) -> None:
        try:
            while not self.stopping:
                frame = read_frame(self.reader, self.max_frame_bytes)
                if frame.get("kind") == "callback_result":
                    with self.callback_lock:
                        future = self.callbacks.get(frame.get("id"))
                    if future is None or future.done():
                        continue
                    if frame.get("ok") is True:
                        future.set_result(frame.get("result"))
                    else:
                        future.set_exception(
                            RemoteHostError(
                                str(frame.get("error", "Host callback failed"))
                            )
                        )
                else:
                    self.loop.call_soon_threadsafe(self._receive, frame)
        except (EOFError, OSError, ProtocolError):
            if self.loop is not None:
                self.loop.call_soon_threadsafe(self._transport_closed)

    def _transport_closed(self) -> None:
        self.stopping = True
        for task in tuple(self.tasks.values()):
            task.cancel()
        self.done.set()

    def _receive(self, frame: dict[str, Any]) -> None:
        kind, identifier = frame.get("kind"), frame.get("id")
        if kind == "cancel":
            task = self.tasks.get(identifier)
            if task is not None:
                task.cancel()
            return
        if (
            kind != "request"
            or not isinstance(identifier, str)
            or len(identifier) > 128
            or identifier in self.tasks
        ):
            self._transport_closed()
            return
        if self.stopping or len(self.tasks) >= self.max_inflight:
            self.send(
                {
                    "kind": "response",
                    "id": identifier,
                    "ok": False,
                    "error": "Worker request capacity exhausted",
                }
            )
            return
        self.tasks[identifier] = asyncio.create_task(self._execute(identifier, frame))

    async def _execute(self, identifier: str, frame: dict[str, Any]) -> None:
        token = _request_id.set(identifier)
        try:
            method = frame.get("method")
            if method == "initialize":
                result = self._initialize(frame["payload"])
            elif self.catalog is None:
                raise ProtocolError("Worker must initialize before invocation")
            elif method == "invoke":
                payload = frame["payload"]
                args, kwargs = payload.get("args", ()), payload.get("kwargs", {})
                if payload.get("progress"):
                    from .tools import ToolExecutionContext

                    def bind_progress(value: Any) -> Any:
                        return (
                            value.model_copy(update={"progress": WorkerProgress(self)})
                            if isinstance(value, ToolExecutionContext)
                            else value
                        )

                    args = tuple(bind_progress(value) for value in args)
                    kwargs = {
                        key: bind_progress(value) for key, value in kwargs.items()
                    }
                result = self.catalog.method(payload["target"], payload["method"])(
                    *args, **kwargs
                )
                if inspect.isawaitable(result):
                    result = await result
            elif method == "stream_open":
                payload = frame["payload"]
                if len(self.streams) >= self.max_inflight:
                    raise ProtocolError("Worker stream capacity exhausted")
                if (
                    not payload["target"].startswith("provider:")
                    or payload["method"] != "stream"
                ):
                    raise ProtocolError("Worker stream method is not allowed")
                iterator = self.catalog.method(payload["target"], "stream")(
                    payload["request"]
                )
                if inspect.isawaitable(iterator):
                    iterator = await iterator
                if not hasattr(iterator, "__anext__"):
                    raise ProtocolError("Provider stream must be an async iterator")
                stream_id = uuid.uuid4().hex
                self.streams[stream_id] = iterator
                result = {"stream_id": stream_id}
            elif method == "stream_next":
                stream_id = frame["payload"]["stream_id"]
                if stream_id in self.stream_busy:
                    raise ProtocolError(
                        "Concurrent reads of one provider stream are forbidden"
                    )
                iterator = self.streams[stream_id]
                self.stream_busy.add(stream_id)
                try:
                    result = {"done": False, "item": await iterator.__anext__()}
                except StopAsyncIteration:
                    self.streams.pop(stream_id, None)
                    result = {"done": True}
                finally:
                    self.stream_busy.discard(stream_id)
            elif method == "stream_close":
                stream_id = frame["payload"]["stream_id"]
                iterator = self.streams.pop(stream_id, None)
                if iterator is not None and hasattr(iterator, "aclose"):
                    await iterator.aclose()
                result = None
            elif method == "bind_channel":
                channel = self.catalog.targets["channel"][0]
                for port in frame["payload"]["ports"]:
                    if port not in CHANNEL_PORTS:
                        raise ProtocolError("Unknown channel port")
                    getattr(channel, "bind_" + port)(RemoteChannelPort(self, port))
                result = None
            elif method == "channel_boundary":
                payload = frame["payload"]
                if payload["enter"]:
                    if self.channel_boundaries:
                        raise RuntimeError("Channel clear boundary already active")
                    boundary = self.catalog.targets["channel"][
                        0
                    ].inbound_clear_boundary(payload["request"])
                    await boundary.__aenter__()
                    self.channel_boundaries[payload["boundary_id"]] = boundary
                else:
                    boundary = self.channel_boundaries.pop(payload["boundary_id"])
                    await boundary.__aexit__(None, None, None)
                result = None
            elif method == "ingress_catalog":
                entries = self.catalog.plugin.get_plugin_ingress_registrations(
                    runtime_paths=WorkerRuntimePaths(
                        self.catalog.plugin.context.state_dir
                    )
                )
                result = []
                for index, entry in enumerate(entries):
                    target = f"ingress:{index}"
                    self.catalog.targets[target] = (
                        entry.handler,
                        frozenset({"handle_event"}),
                    )
                    result.append(
                        {
                            "target": target,
                            "plugin_target": entry.plugin_target,
                            "event_type": entry.event_type,
                        }
                    )
            else:
                raise ProtocolError("Unknown worker request method")
            self.send(
                {"kind": "response", "id": identifier, "ok": True, "result": result}
            )
        except asyncio.CancelledError:
            self.send(
                {
                    "kind": "response",
                    "id": identifier,
                    "ok": False,
                    "error": "Plugin invocation cancelled",
                    "code": "cancelled",
                }
            )
        except BaseException as exc:
            # Exception text is bounded. Do not transmit tracebacks or locals.
            self.send(
                {
                    "kind": "response",
                    "id": identifier,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:1024]}",
                }
            )
        finally:
            self.tasks.pop(identifier, None)
            _request_id.reset(token)

    def _initialize(self, payload: dict[str, Any]) -> dict[str, Any]:
        global _host
        if self.catalog is not None:
            raise ProtocolError("Worker already initialized")
        handshake = payload["handshake"]
        if (
            not isinstance(handshake, PluginHandshake)
            or handshake.protocol_version != PLUGIN_PROTOCOL_VERSION
            or handshake.sdk_version != SDK_VERSION
        ):
            raise ProtocolError("Plugin protocol agreement failed")
        manifest, connection = payload["manifest"], payload["connection"]
        if (
            handshake.plugin_id != manifest.plugin_id
            or handshake.connection_id != connection.connection_id
            or connection.plugin_id != manifest.plugin_id
        ):
            raise ProtocolError("Plugin handshake identity mismatch")
        if (
            manifest.protocol_version != PLUGIN_PROTOCOL_VERSION
            or str(manifest.min_sdk_version) != SDK_VERSION
        ):
            raise ProtocolError("Plugin requires an incompatible SDK version")
        self.max_inflight = payload["max_inflight"]
        self.callback_timeout = payload["callback_timeout"]
        state_dir, resources_dir = payload["state_dir"], payload["resources_dir"]
        if payload["confinement"] == "macos-seatbelt":
            _verify_confinement(payload["probe_path"])
        context = PluginContext(
            connection, state_dir, resources_dir, WorkerCredentials(self)
        )
        root = Path(manifest.plugin_dir).resolve()
        entry = (root / (manifest.entry_module.replace(".", "/") + ".py")).resolve()
        if not entry.is_relative_to(root) or not entry.is_file():
            raise ProtocolError("Plugin entrypoint is outside its package")
        # Only this worker imports package-local dependencies. SDK modules were
        # loaded before these paths, and site .pth startup code is disabled.
        library_roots = [Path(path).resolve() for path in payload["dependency_paths"]]
        install_library_imports(library_roots)
        for path in reversed(
            [root / ".deps", *(path / ".deps" for path in library_roots)]
        ):
            resolved = Path(path).resolve()
            if resolved.is_dir():
                sys.path.insert(0, str(resolved))
        _host = WorkerHost(self)
        spec = importlib.util.spec_from_file_location(
            "_magi_external_plugin", entry, submodule_search_locations=[str(root)]
        )
        if spec is None or spec.loader is None:
            raise ProtocolError("Plugin module cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls = getattr(module, manifest.entry_class)
        if not isinstance(cls, type) or not issubclass(cls, Plugin):
            raise ProtocolError("Plugin entry class must implement the SDK Plugin")
        plugin = cls()
        plugin.configure(manifest=manifest, connection=connection, context=context)
        self.catalog = WorkerCatalog(plugin)
        return {
            "handshake": handshake,
            "catalog": self.catalog.describe(),
            "pid": os.getpid(),
            "confinement_verified": payload["confinement"] == "macos-seatbelt",
        }

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.done = asyncio.Event()
        threading.Thread(target=self._reader, name="plugin-input", daemon=True).start()
        await self.done.wait()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks.values()), return_exceptions=True)


def _verify_confinement(probe_path: Path) -> None:
    # The host creates this known-readable file outside all allowed roots.
    try:
        with open(probe_path, "rb") as stream:
            stream.read(1)
    except PermissionError:
        pass
    else:
        raise RuntimeError("Filesystem confinement probe failed")
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pass
    else:
        raise RuntimeError("Network confinement probe failed")


def main() -> None:
    # Python and native plugin stdout writes cannot corrupt the protocol stream.
    reader = os.fdopen(os.dup(sys.stdin.fileno()), "rb", buffering=0)
    writer = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        asyncio.run(WorkerServer(reader, writer).run())
    finally:
        reader.close()
        writer.close()


if __name__ == "__main__":
    main()
