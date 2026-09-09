#!/usr/bin/env python3
"""Exercise a relocated service bundle using only isolated temporary business data."""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from queue import Queue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--deny-checkout", type=Path, help="On macOS, deny the service access to this source tree")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="ms-bundle-", dir="/private/tmp" if sys.platform == "darwin" else None)).resolve()
    bundle = root / "relocated service"
    shutil.copytree(args.bundle.resolve(), bundle, symlinks=True)
    executable = bundle / ("magi-server.exe" if os.name == "nt" else "magi-server")
    config = root / "server.json"
    environment = {key: os.environ[key] for key in ("HOME", "USERPROFILE", "SYSTEMROOT", "LANG", "TMPDIR") if key in os.environ}
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin" if os.name != "nt" else os.environ.get("SYSTEMROOT", r"C:\Windows") + r"\System32"
    subprocess.run([str(executable), "init", "--config", str(config), "--data-dir", str(root / "data"), "--port", "0"], check=True, cwd=root, env=environment)
    prefix: list[str] = []
    if args.deny_checkout:
        checkout = args.deny_checkout.resolve()
        # json.dumps provides the quoted string syntax expected by Seatbelt.
        profile = f'(version 1)(allow default)(deny file-read* (subpath {json.dumps(str(checkout))})(subpath "/opt/homebrew"))'
        prefix = ["/usr/bin/sandbox-exec", "-p", profile]
    log = (root / "service.log").open("w")
    process = subprocess.Popen(prefix + [str(executable), "run", "--config", str(config)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, text=True, cwd=root, env=environment)
    try:
        lines: Queue[str] = Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        info = json.loads(lines.get(timeout=15))
        authority = info["baseUrl"].removeprefix("http://").removesuffix("/api")

        def operator(command: str) -> dict:
            result = subprocess.run([str(executable), command, "--config", str(config)], capture_output=True, text=True, env=environment, cwd=root, timeout=10, check=True)
            return json.loads(result.stdout)

        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Packaged service exited during startup")
            status = operator("status")
            if status.get("service_ready"):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Packaged runtime never became ready")
        grant = operator("pair")

        def call(method: str, path: str, payload: dict | None = None, token: str | None = None) -> tuple[int, dict]:
            connection = http.client.HTTPConnection(authority, timeout=10)
            headers = {"content-type": "application/json"}
            if token:
                headers["x-magi-session-token"] = token
            try:
                connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
                response = connection.getresponse()
                body = response.read()
                try:
                    value = json.loads(body)
                except ValueError:
                    raise AssertionError(f"Non-JSON response: {method} {path} status={response.status} body={body[:400]!r}") from None
                return response.status, value
            finally:
                connection.close()

        code, paired = call("POST", "/api/auth/pair", {"name": "Relocated bundle validation"}, token=grant["pairing_token"])
        assert code == 200, (code, paired)
        credentials = paired["data"]
        code, session = call("POST", "/api/auth/session", {}, token=credentials["client_credential"])
        assert code == 200, (code, session)
        token = session["data"]["access_token"]
        for endpoint in ("/api/server/info", "/api/config/", "/api/messages/sessions"):
            code, result = call("GET", endpoint, token=token)
            assert code == 200, (endpoint, code, result)
        code, _ = call("GET", "/api/config/")
        assert code == 401, code
        # Isolated plugin startup must use the shipped SDK, without sitecustomize or a checkout.
        python = bundle / ("plugin-python/python.exe" if os.name == "nt" else "plugin-python/bin/python")
        probe = "import sys,sysconfig;sys.path[:0]=list(dict.fromkeys([sysconfig.get_path('purelib'),sysconfig.get_path('platlib')]));from magi_plugin_sdk.worker import main;from magi_plugin_sdk.runtime import SDK_VERSION;print(SDK_VERSION)"
        subprocess.run(prefix + [str(python), "-I", "-S", "-c", probe], check=True, cwd=root, env=environment, timeout=15)
        print(json.dumps({"result": "passed", "data_root": str(root), "source_access_denied": bool(args.deny_checkout), "server_id": credentials["server_id"]}), flush=True)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()
        shutil.rmtree(bundle)
        print(f"Service exit: {process.returncode}; validation evidence: {root}", flush=True)


if __name__ == "__main__":
    main()
