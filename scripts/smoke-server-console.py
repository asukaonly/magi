#!/usr/bin/env python3
"""Exercise console setup against real Python APIs and a local mock model.

Uses isolated data roots, standard-library PTYs and no external model credentials.
Never installs a LaunchAgent or changes the user's existing service.
"""
from __future__ import annotations

import argparse
import fcntl
import http.server
import json
import os
import pty
import re
import select
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path


class Model(http.server.BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls += 1
        if self.headers.get("Authorization") == "Bearer reject-console":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Invalid test credential","type":"authentication_error"}}')
            return
        response = json.dumps({
            "id": "console-test", "object": "chat.completion", "created": 0,
            "model": body.get("model", "console-model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_args: object) -> None:
        pass


def management(data: Path, command: str) -> dict:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(6)
        client.connect(str(data / "runtime/manage.sock"))
        client.sendall(json.dumps({"command": command}).encode() + b"\n")
        reply = json.loads(client.makefile("rb").readline())
        assert reply["success"], reply
        return reply["data"]


def api(data: Path, path: str) -> dict:
    access = management(data, "operator_session")
    request = urllib.request.Request(access["base_url"] + path, headers={
        "x-magi-session-token": access["session"]["access_token"], "accept-language": "en",
    })
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as reply:
        return json.load(reply)


def wait_for(predicate, message: str, timeout: float = 35) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    raise AssertionError(message)


def stopped(data: Path) -> bool:
    for name in ("owner.lock", "server.lock", "worker.lock"):
        path = data / "runtime" / name
        if path.exists():
            with path.open("r+") as file:
                try:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
    return True


class Terminal:
    def __init__(self, args: list[str]) -> None:
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(args[0], args, {**os.environ, "TERM": "xterm-256color"})
        self.buffer = ""
        self.transcript = ""
        self.done = False

    def expect(self, value: str, timeout: float = 45) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            stripped = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", self.buffer)
            if value in stripped:
                self.buffer = ""
                return
            if select.select([self.fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(self.fd, 65536).decode(errors="replace")
                except OSError:
                    break
                if not chunk:
                    break
                self.buffer += chunk
                self.transcript += chunk
        raise AssertionError(f"Console did not reach {value!r}. Tail: {self.buffer[-1200:]}")

    def send(self, value: str) -> None:
        os.write(self.fd, value.encode())

    def exit(self) -> int:
        status = None
        def reaped() -> bool:
            nonlocal status
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            return pid != 0
        wait_for(reaped, "Console did not exit", 50)
        self.done = True
        return os.waitstatus_to_exitcode(status)

    def close(self) -> None:
        if not self.done:
            try:
                os.kill(self.pid, signal.SIGTERM)
                self.exit()
            except ProcessLookupError:
                pass
        os.close(self.fd)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, default=Path("target/debug/magi-server"))
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    executable, project = str(args.executable.resolve()), str(args.project.resolve())
    model = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    terminals: list[Terminal] = []
    service = None
    with tempfile.TemporaryDirectory(prefix="mc-", dir="/tmp") as directory:
        root = Path(directory)
        config, data = root / "server.json", root / "data"
        try:
            # First run: initialize, choose language, then cancel before credentials.
            terminal = Terminal([executable, "--config", str(config), "--development-root", project, "--data-dir", str(data), "--port", "0"])
            terminals.append(terminal)
            terminal.expect("data directory (absolute path)")
            terminal.send("\r")
            terminal.expect("Loopback port")
            terminal.send("\r")
            terminal.expect("run mode")
            terminal.send("\r")
            terminal.expect("2/5")
            terminal.send("\r")
            terminal.expect("3/5")
            terminal.send("\x1b[B\r")
            terminal.expect("provider")
            terminal.send("\x03")
            assert terminal.exit() != 0
            wait_for(lambda: stopped(data), "Cancelled wizard left an owned runtime")
            assert json.loads(config.with_suffix(".console.json").read_text())["run_mode"] == "foreground"

            # Resume from saved English, switch to Chinese before selecting a persona.
            terminal = Terminal([executable, "--config", str(config)])
            terminals.append(terminal)
            terminal.expect("2/5")
            terminal.send("\r")
            terminal.expect("3/5")
            assert api(data, "/config/onboarding-template")["data"]["config"]["preferences"]["language"] == "en"
            terminal.send("\x1b[A\r")
            terminal.expect("provider")
            provider_count = sum(p["source"] == "builtin" for p in api(data, "/llm/providers/catalog")["data"]["providers"])
            terminal.send("\x1b[B" * provider_count + "\r")
            terminal.expect("Provider base URL")
            terminal.send(f"http://127.0.0.1:{model.server_port}/v1\r")
            terminal.expect("Provider API key")
            terminal.send("console-secret-should-stay-hidden\r")
            terminal.expect("Core model")
            terminal.send("console-model\r")
            terminal.expect("Fast model")
            terminal.send("\r")
            terminal.expect("5/5", 60)
            terminal.send("\r")
            terminal.expect("Running in foreground", 60)
            assert "console-secret-should-stay-hidden" not in terminal.transcript
            assert api(data, "/config/onboarding-status")["data"]["completed"]
            active = api(data, "/personas/active")["persona_id"]
            persona = next(p for p in api(data, "/personas/")["data"] if p["persona_id"] == active)
            assert persona["locale"] == "zh"
            assert Model.calls >= 1

            # Existing configured instance: status only, same PID and no paired devices.
            before = management(data, "status")
            second = Terminal([executable, "--config", str(config)])
            terminals.append(second)
            second.expect("Service remains running")
            assert second.exit() == 0
            assert management(data, "status")["server_id"] == before["server_id"]
            assert management(data, "clients") == []

            # Reconfiguration reuses masked secrets, runs live APIs, and switches locale.
            llm = api(data, "/config")["data"]["llm"]
            assert llm["selections"]["core"]["provider_id"] == "custom"
            previews = api(data, "/personas/seed-previews?locale=en")["data"]
            payload = {"language": "en", "llm": llm, "persona_slug": previews[0]["seed_slug"]}
            result = subprocess.run([executable, "configure", "--config", str(config), "--from-stdin"], input=json.dumps(payload), capture_output=True, text=True, timeout=90)
            assert result.returncode == 0, result.stderr
            assert api(data, "/config")["data"]["preferences"]["language"] == "en"
            active = api(data, "/personas/active")["persona_id"]
            assert next(p for p in api(data, "/personas/")["data"] if p["persona_id"] == active)["locale"] == "en"
            terminal.send("\x03")
            terminal.exit()
            wait_for(lambda: stopped(data), "Foreground Ctrl+C left an owned runtime", 50)

            # Desktop handoff against another clean data root: real one-time pairing.
            data2, config2 = root / "handoff", root / "handoff.json"
            subprocess.run([executable, "init", "--config", str(config2), "--data-dir", str(data2), "--development-root", project, "--port", "0"], check=True, capture_output=True)
            service = subprocess.Popen([executable, "run", "--config", str(config2), "--log-file", str(root / "handoff.log")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_for(lambda: management(data2, "status")["service_ready"], "Handoff service not ready")
            handoff = Terminal([executable, "--config", str(config2)])
            terminals.append(handoff)
            handoff.expect("2/5")
            handoff.send("\x1b[B\r")
            handoff.expect("Service remains running")
            assert handoff.exit() == 0
            plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", handoff.transcript)
            grant = re.search(r"\b[0-9a-f]{64}\b", plain)
            assert grant, "Missing pairing code"
            status = management(data2, "status")
            request = urllib.request.Request(status["base_url"] + "/auth/pair", data=b'{"name":"Console smoke"}', headers={"x-magi-session-token":grant[0], "Content-Type":"application/json"})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10) as response:
                assert json.load(response)["success"]
            assert not api(data2, "/config/onboarding-status")["data"]["completed"]
            assert service.poll() is None
            payload["llm"]["providers"]["custom"]["api_key"] = "reject-console"
            payload["llm"]["providers"]["custom"]["services"]["chat"]["api_key"] = "reject-console"
            invalid = subprocess.run([executable, "configure", "--config", str(config2), "--from-stdin"], input=json.dumps(payload), capture_output=True, text=True, timeout=90)
            assert invalid.returncode != 0
            assert "reject-console" not in invalid.stdout + invalid.stderr
            assert not api(data2, "/config/onboarding-status")["data"]["completed"]
            payload["llm"]["providers"]["custom"]["api_key"] = "valid-console"
            payload["llm"]["providers"]["custom"]["services"]["chat"]["api_key"] = "valid-console"
            applied = subprocess.run([executable, "configure", "--config", str(config2), "--from-stdin"], input=json.dumps(payload), capture_output=True, text=True, timeout=90)
            assert applied.returncode == 0, applied.stderr
            assert api(data2, "/config/onboarding-status")["data"]["completed"]
            print("PASS: cancellation, resume, language/persona, model verification, reconfigure, running reuse, foreground shutdown, desktop pairing and noninteractive first setup/failure")
        except BaseException:
            for name in ("service.log", "backend.log"):
                log = data / "logs" / name
                if log.exists():
                    Path(f"/tmp/magi-console-failure-{name}").write_bytes(log.read_bytes())
            raise
        finally:
            for terminal in terminals:
                terminal.close()
            if service is not None:
                service.terminate()
                service.wait(timeout=50)
            wait_for(lambda: stopped(data), "Test runtime did not drain", 50)
            model.shutdown()


if __name__ == "__main__":
    main()
