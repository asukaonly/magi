"""Run a trusted plugin's initialization and settings request with the shipped SDK."""

import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

PLUGIN_SOURCE = """\
import os
import sys
from magi_plugin_sdk import Plugin

if sys.platform == "darwin":
    import ctypes
    appkit = ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    appkit.NSApplicationLoad.restype = ctypes.c_bool
    assert appkit.NSApplicationLoad()

class Probe(Plugin):
    def read_settings_resource(self, name):
        return os.getpid()
"""


def main() -> None:
    # The bundle test launches this probe with -I -S, as the service launches workers.
    sdk_paths = list(
        dict.fromkeys([sysconfig.get_path("purelib"), sysconfig.get_path("platlib")])
    )
    sys.path[:0] = sdk_paths
    from magi_plugin_sdk.contracts import PluginManifest
    from magi_plugin_sdk.runtime import (
        PLUGIN_PROTOCOL_VERSION,
        SDK_VERSION,
        PluginConnection,
        PluginHandshake,
    )
    from magi_plugin_sdk.transport import pack, read_frame, write_frame

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
        root = Path(temporary)
        (root / "plugin.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
        manifest = PluginManifest(
            id="bundle-probe",
            name="Bundle probe",
            version="1.0.0",
            execution_mode="trusted_process",
            plugin_dir=str(root),
            entry_class="Probe",
        )
        connection = PluginConnection(
            connection_id="probe",
            plugin_id=manifest.plugin_id,
            display_name="Probe",
            enabled=True,
        )
        handshake = PluginHandshake(
            protocol_version=PLUGIN_PROTOCOL_VERSION,
            sdk_version=SDK_VERSION,
            plugin_id=manifest.plugin_id,
            connection_id=connection.connection_id,
        )
        launch = f"import sys;sys.path[:0]={sdk_paths!r};from magi_plugin_sdk.worker import main;main()"
        with subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", "-u", "-c", launch],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        ) as worker:

            def request(method: str, payload: dict):
                write_frame(
                    worker.stdin,
                    pack(
                        {
                            "kind": "request",
                            "id": method,
                            "method": method,
                            "payload": payload,
                        }
                    ),
                )
                reply = read_frame(worker.stdout)
                assert reply.get("ok") and reply["id"] == method, reply
                return reply["result"]

            try:
                result = request(
                    "initialize",
                    {
                        "handshake": handshake,
                        "manifest": manifest,
                        "connection": connection,
                        "state_dir": root / "state",
                        "resources_dir": root / "resources",
                        "dependency_paths": [],
                        "max_inflight": 4,
                        "callback_timeout": 5,
                        "confinement": "trusted",
                    },
                )
                assert result["handshake"] == handshake and result["pid"] == worker.pid
                assert (
                    request(
                        "invoke",
                        {
                            "target": "plugin",
                            "method": "read_settings_resource",
                            "args": ["status"],
                        },
                    )
                    == worker.pid
                )
                if sys.platform == "darwin":
                    info = subprocess.check_output(
                        ["/usr/bin/lsappinfo", "info", f"#{worker.pid}"], text=True
                    )
                    assert 'type="BackgroundOnly"' in info, info
            finally:
                worker.stdin.close()
        assert worker.returncode == 0, worker.returncode


if __name__ == "__main__":
    main()
