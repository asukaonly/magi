#!/usr/bin/env python3
"""Exercise authenticated file transfers through the real gateway and Python IPC."""
from __future__ import annotations
import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
from queue import Queue
import signal
import subprocess
import tempfile
import threading
import time
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='ms-transfer-', dir='/private/tmp' if os.uname().sysname == 'Darwin' else None)).resolve()
    config = root / 'server.json'
    executable = str(args.executable.resolve())
    subprocess.run([executable, 'init', '--config', str(config), '--data-dir', str(root / 'data'), '--development-root', str(args.project.resolve()), '--port', '0'], check=True, capture_output=True)
    content = bytes(range(256)) * 4097
    artifact = root / 'fixture.magibackup'
    artifact.write_bytes(content)
    operation_id = str(uuid4())
    operations = root / 'data/runtime/memory-portability/operations'
    operations.mkdir(parents=True)
    (operations / f'{operation_id}.json').write_text(json.dumps({'owner_pid': os.getpid(), 'operation': {'operation_id': operation_id, 'kind': 'backup', 'status': 'succeeded', 'phase': 'completed', 'progress_percent': 100, 'created_at': '2026-09-08T00:00:00Z', 'output_path': str(artifact), 'file_size_bytes': len(content)}}))
    log = (root / 'service.log').open('w')
    process = subprocess.Popen([executable, 'run', '--config', str(config)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, text=True)
    try:
        lines: Queue[str] = Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        info = json.loads(lines.get(timeout=15))
        authority = info['baseUrl'].removeprefix('http://').removesuffix('/api')
        def operator(command: str) -> dict:
            result = subprocess.run([executable, command, '--config', str(config)], capture_output=True, text=True, check=True, timeout=10)
            return json.loads(result.stdout)
        deadline = time.monotonic() + 100
        while not operator('status').get('runtime_ready'):
            if time.monotonic() > deadline or process.poll() is not None: raise RuntimeError('Service did not become ready')
            time.sleep(0.25)
        def call(method: str, path: str, payload=None, token=None):
            connection = http.client.HTTPConnection(authority, timeout=20)
            headers = {'content-type': 'application/octet-stream' if isinstance(payload, bytes) else 'application/json'}
            if token: headers['x-magi-session-token'] = token
            try:
                connection.request(method, path, payload if isinstance(payload, bytes) else json.dumps(payload) if payload is not None else None, headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally: connection.close()
        grant = operator('pair')
        code, paired = call('POST', '/api/auth/pair', {'name': 'File transfer validation'}, grant['pairing_token'])
        assert code == 200
        code, session = call('POST', '/api/auth/session', {}, paired['data']['client_credential'])
        assert code == 200
        token = session['data']['access_token']
        code, listing = call('GET', '/api/files/browse', token=token)
        assert code == 200 and 'entries' in listing, (code, listing)
        resource_id = str(uuid4())
        spec = {'resource_id': resource_id, 'name': 'sample.bin', 'source_name': 'sample.bin', 'last_modified_ms': 1600000000000, 'purpose': 'history', 'size': len(content)}
        code, uploaded = call('POST', '/api/files/uploads', spec, token)
        assert code == 200, (code, uploaded)
        for offset in range(0, len(content), 1024 * 1024):
            chunk = content[offset:offset + 1024 * 1024]
            route = f'/api/files/uploads/{resource_id}?offset={offset}&sha256={hashlib.sha256(chunk).hexdigest()}'
            code, response = call('PUT', route, chunk, token)
            assert code == 200 and response['received'] == offset + len(chunk), (code, response)
            code, repeated = call('PUT', route, chunk, token)
            assert code == 200 and repeated == response, (code, repeated)
        assert (root / 'data/runtime/file-transfers' / resource_id / 'content/sample.bin').read_bytes() == content
        route = f'/api/files/outputs/{operation_id}'
        code, metadata = call('GET', route, token=token)
        assert code == 200, (code, metadata)
        received = bytearray()
        for offset in range(0, metadata['size'], 1024 * 1024):
            code, chunk = call('GET', f'{route}/chunks?offset={offset}&version={metadata["version"]}', token=token)
            assert code == 200, (code, chunk)
            decoded = base64.b64decode(chunk['data'])
            assert hashlib.sha256(decoded).hexdigest() == chunk['sha256']
            received.extend(decoded)
        assert bytes(received) == content
        for path in ['/api/files/browse', route, f'{route}/chunks?offset=0&version={metadata["version"]}']:
            assert call('GET', path)[0] == 401
        print(json.dumps({'result': 'passed', 'data_root': str(root), 'bytes': len(content), 'authenticated_upload_download': True, 'identical_chunk_retry': True}), flush=True)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try: process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(); raise RuntimeError('Service did not stop cleanly')
        log.close()
        if process.returncode != 0: raise RuntimeError(f'Service exit status {process.returncode}')


if __name__ == '__main__':
    main()
