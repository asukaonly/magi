"""Loopback-only HTTPS proxy for service acceptance; never installs a trust root."""
from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import subprocess
import threading


class LocalTLSProxy:
    def __init__(self, upstream: str, root: Path) -> None:
        certificate, key = root / "test-cert.pem", root / "test-key.pem"
        config = root / "test-tls.cnf"
        config.write_text("[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=extensions\n"
                          "[dn]\nCN=localhost\n[extensions]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n"
                          "basicConstraints=critical,CA:TRUE\nkeyUsage=digitalSignature,keyEncipherment,keyCertSign\n"
                          "extendedKeyUsage=serverAuth\n")
        subprocess.run(["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "1", "-config", str(config), "-keyout", str(key), "-out", str(certificate)],
                       capture_output=True, timeout=15, check=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        self.client_context = ssl.create_default_context(cafile=str(certificate))

        class Forwarder(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:
                pass

            def forward(self) -> None:
                size = int(self.headers.get("Content-Length", "0"))
                if not self.path.startswith("/api/") or not 0 <= size <= 2 * 1024 * 1024:
                    self.send_error(400)
                    return
                headers = {name: value for name, value in self.headers.items()
                           if name.lower() not in {"host", "connection", "transfer-encoding"}}
                connection = http.client.HTTPConnection(upstream, timeout=30)
                try:
                    connection.request(self.command, self.path, self.rfile.read(size), headers)
                    response = connection.getresponse()
                    self.send_response(response.status)
                    for name, value in response.getheaders():
                        if name.lower() not in {"connection", "transfer-encoding", "keep-alive"}:
                            self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    while data := response.read1(64 * 1024):
                        self.wfile.write(data)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except http.client.IncompleteRead:
                    # Service shutdown may terminate an already-disconnected SSE stream.
                    if response.getheader("Content-Type", "").split(";", 1)[0] != "text/event-stream":
                        raise
                finally:
                    self.close_connection = True
                    connection.close()

            do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = forward

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Forwarder)
        self.server.daemon_threads = True
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        untrusted = http.client.HTTPSConnection("localhost", self.server.server_port, timeout=5)
        try:
            untrusted.request("GET", "/api/health")
        except ssl.SSLCertVerificationError:
            pass
        else:
            self.close()
            raise AssertionError("The test certificate must require explicit local trust")
        finally:
            untrusted.close()

    def connection(self) -> http.client.HTTPSConnection:
        return http.client.HTTPSConnection("localhost", self.server.server_port,
                                          context=self.client_context, timeout=20)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
