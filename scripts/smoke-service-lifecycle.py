#!/usr/bin/env python3
"""Exercise the real service supervisor with isolated Python loop faults.

The worker fixture uses the production worker lease/owner monitor and a minimal
IPC transport. It never opens user databases, plugins or model providers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


async def worker_loop(root: Path) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    token = os.environ.pop("MAGI_IPC_AUTH_TOKEN")
    tasks: set[asyncio.Task[None]] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        lock = asyncio.Lock()

        async def respond(request: dict[str, Any]) -> None:
            method = request["method"]
            if method == "ipc.authenticate":
                assert request["params"]["token"] == token
                result = {"authenticated": True}
            elif method == "ping":
                if (root / "hang").exists():
                    (root / "hang").unlink()
                    time.sleep(60)  # noqa: ASYNC251 -- Deliberately block the real event loop.
                result = {"status": "pong"}
            else:
                if (root / "slow").exists():
                    (root / "slow").unlink()
                    await asyncio.sleep(4)
                result = {"status": 200, "body": {"success": True, "data": {"ready": True}}, "headers": {}}
            async with lock:
                writer.write((json.dumps({"id": request["id"], "result": result}) + "\n").encode())
                await writer.drain()

        try:
            while line := await reader.readline():
                task = asyncio.create_task(respond(json.loads(line)))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, os.environ["MAGI_IPC_SOCKET"])
    (root / "runtime/worker.ready").write_text(str(os.getpid()))
    await stop.wait()
    server.close()
    await server.wait_closed()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    # Exercise predecessor lease handoff during a non-instantaneous cleanup.
    await asyncio.sleep(1)
    (root / f"drained-{os.getpid()}").write_text("complete")


class Service:
    def __init__(self, executable: Path, config: Path) -> None:
        self.token = uuid.uuid4().hex * 2
        self.process = subprocess.Popen(
            [str(executable), "run", "--config", str(config), "--bootstrap-stdin"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.errors: list[str] = []
        threading.Thread(target=lambda: self.errors.extend(self.process.stderr.readlines()), daemon=True).start()
        self.process.stdin.write(json.dumps({"session_token": self.token}) + "\n")
        self.process.stdin.flush()
        lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=lambda: lines.put(self.process.stdout.readline()), daemon=True).start()
        try:
            self.base = json.loads(lines.get(timeout=15))["baseUrl"]
        except BaseException:
            self.close()
            raise

    def request(self, path: str, *, token: str | None = None, method: str = "GET", body: dict[str, object] | None = None) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={"x-magi-session-token": token or self.token, "Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def close(self) -> None:
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        for pipe in (self.process.stdout, self.process.stderr):
            if pipe:
                pipe.close()


def eventually(check: Callable[[], bool], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("Isolated lifecycle condition did not complete before its deadline")


def smoke(executable: Path) -> None:
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="magi-life-") as directory:
        root = Path(directory) / "data"
        config = Path(directory) / "server.json"
        config.write_text(json.dumps({
            "data_dir": str(root), "port": 0, "builtin_avatar_dir": None,
            "max_restarts": 2, "startup_timeout_secs": 10, "shutdown_timeout_secs": 4,
            "supervision": {"probe_interval_secs": 1, "probe_timeout_secs": 1, "missed_probes": 2, "stable_after_secs": 3, "cooldown_secs": 2},
            "worker": {"executable": sys.executable, "args": [str(Path(__file__).resolve()), "--worker"],
                       "working_directory": str(checkout), "python_path": [str(checkout / "backend/src")], "plugin_python": sys.executable},
        }))
        service = Service(executable, config)
        pid_path = root / "runtime/worker.ready"
        ready = lambda: service.request("/server/info")[1]["data"]["service_ready"]
        try:
            eventually(ready)
            first_pid = pid_path.read_text()
            (root / "slow").touch()
            status, _ = service.request("/lifecycle-fixture-slow")
            assert status == 200 and pid_path.read_text() == first_pid
            print("PASS: slow asynchronous work remains responsive", flush=True)

            (root / "hang").touch()
            eventually(lambda: pid_path.exists() and pid_path.read_text() != first_pid and ready())
            assert service.process.poll() is None
            print("PASS: blocked Python event loop is replaced without restarting the gateway", flush=True)

            _, grant = service.request("/server/pairing-grants", method="POST")
            _, paired = service.request("/auth/pair", token=grant["data"]["pairing_token"], method="POST", body={"name": "isolated-lifecycle-test"})
            credential = paired["data"]["client_credential"]
            _, session = service.request("/auth/session", token=credential, method="POST")
            previous_access = session["data"]["access_token"]
            server_id = service.request("/server/info")[1]["data"]["server_id"]
            previous_pid = pid_path.read_text()
            service.process.kill()
            service.process.wait(timeout=5)
            service.close()
            service = Service(executable, config)
            eventually(ready)
            assert (root / f"drained-{previous_pid}").exists()
            assert pid_path.read_text() != previous_pid
            assert service.request("/server/info")[1]["data"]["server_id"] == server_id
            assert service.request("/server/info", token=previous_access)[0] == 401
            status, renewed = service.request("/auth/session", token=credential, method="POST")
            assert status == 200
            assert service.request("/server/info", token=renewed["data"]["access_token"])[0] == 200
            print("PASS: service crash releases predecessor ownership and preserves paired identity", flush=True)
            final_pid = pid_path.read_text()
            service.close()
            assert service.process.returncode == 0
            assert (root / f"drained-{final_pid}").exists()
            print("PASS: normal stop drains the Python worker before service exit", flush=True)
        finally:
            service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("This fault-injection smoke requires Unix process ownership")
    if args.worker:
        from magi.utils.worker_instance import WorkerInstance
        root = Path(os.environ["MAGI_HOME"])
        with WorkerInstance(root, int(os.environ.pop("MAGI_SERVER_PARENT_PID"))):
            asyncio.run(worker_loop(root))
    elif args.executable:
        smoke(args.executable.resolve())
    else:
        parser.error("--executable is required")
