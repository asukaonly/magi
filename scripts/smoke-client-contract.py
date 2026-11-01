#!/usr/bin/env python3
"""Verify the client contract through a real temporary service, without a desktop host."""

from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import tempfile
import threading
import time
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="magi-client-", dir="/tmp") as temporary:
        root = Path(temporary).resolve()
        executable = str(args.executable.resolve())
        config = root / "server.json"
        subprocess.run([executable, "init", "--config", str(config), "--data-dir", str(root / "data"),
                        "--port", "0", "--development-root", str(args.project.resolve())], check=True, capture_output=True)
        with (root / "service.log").open("w") as log:
            process = subprocess.Popen([executable, "run", "--config", str(config)],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, text=True)
            try:
                started: Queue[str] = Queue()
                threading.Thread(target=lambda: started.put(process.stdout.readline()), daemon=True).start()
                authority = json.loads(started.get(timeout=20))["baseUrl"].removeprefix("http://").removesuffix("/api")

                def operator(command: str) -> dict:
                    result = subprocess.run([executable, command, "--config", str(config), "--json"], check=True, capture_output=True, text=True)
                    return json.loads(result.stdout)

                deadline = time.monotonic() + 120
                while not operator("status").get("service_ready"):
                    if time.monotonic() > deadline or process.poll() is not None:
                        raise RuntimeError("Temporary service did not become ready")
                    time.sleep(0.25)

                def call(method: str, path: str, token: str | None = None, body=None):
                    connection = http.client.HTTPConnection(authority, timeout=20)
                    try:
                        headers = {"Content-Type": "application/json"}
                        if token:
                            headers["x-magi-session-token"] = token
                        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
                        response = connection.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        connection.close()

                def pair(name: str) -> str:
                    grant = operator("pair")
                    status, paired = call("POST", "/api/auth/pair", grant["pairing_token"], {"name": name})
                    assert status == 200
                    status, session = call("POST", "/api/auth/session", paired["data"]["client_credential"], {})
                    assert status == 200
                    return session["data"]["access_token"]

                def frame(token: str, scope="product", after=None):
                    connection = http.client.HTTPConnection(authority, timeout=10)
                    try:
                        headers = {"x-magi-session-token": token, "Accept": "text/event-stream"}
                        if after:
                            headers["Last-Event-ID"] = after
                        connection.request("GET", f"/api/events?scope={scope}", headers=headers)
                        response = connection.getresponse()
                        assert response.status == 200
                        while line := response.readline(128 * 1024).decode().strip():
                            if line.startswith("data:"):
                                data = json.loads(line[5:])
                                assert data["contract_version"] == 1
                                assert data["event_id"] == f'{data["epoch"]}:{data["sequence"]}'
                                return data
                        raise AssertionError("Missing product event")
                    finally:
                        connection.close()

                first, second = pair("First HTTP client"), pair("Second HTTP client")
                assert call("GET", "/api/messages/sessions")[0] == 401
                status, info = call("GET", "/api/server/info", first)
                assert status == 200 and info["data"]["client_contract"]["version"] == 1
                status, schema = call("GET", "/api/openapi.json", first)
                assert status == 200 and "ProductEvent" in schema["components"]["schemas"]
                observation = schema["components"]["schemas"]["SourceObservation"]
                assert "change" in observation["properties"] and "plugin_target" not in observation["properties"]
                assert "/api/delivery/collector/{connection_id}" in schema["paths"]
                initial = frame(second)
                assert initial["event_type"] == "resync_required"
                key = uuid4().hex
                status, created = call("POST", f"/api/messages/session/new?idempotency_key={key}", first)
                assert status == 201
                session_id = created["session_id"]
                assert call("POST", f"/api/messages/session/new?idempotency_key={key}", second)[1]["session_id"] == session_id
                assert call("GET", f"/api/messages/session/{session_id}", second)[0] == 200
                snapshot = call("GET", f"/api/messages/session/{session_id}/turn/unsubmitted", second)[1]
                assert snapshot["acceptance"] == "absent" and snapshot["can_resubmit"] is True
                body = {"kind": "turn", "session_id": session_id, "turn_id": "unsubmitted"}
                assert call("POST", "/api/messages/confirmation", second, body)[1]["status"] == "absent"
                changed = frame(second, after=initial["event_id"])
                assert changed["event_type"] == "state.changed" and changed["data"]["resource"] == "messages"
                assert frame(first, scope="diagnostics", after=changed["event_id"])["event_type"] == "resync_required"
                assert call("DELETE", f"/api/messages/session/{session_id}", first)[0] == 200
                assert call("POST", "/api/messages/confirmation", second, body)[1]["status"] == "concluded"
                print("Independent HTTP client contract passed: pairing, schemas, shared state, idempotency, events, retirement")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    main()
