#!/usr/bin/env python3
"""Exercise service-owned backup, upload, restore and disconnected confirmation."""
from __future__ import annotations

import argparse
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
    parser.add_argument('--project', type=Path, help='Use a source worker instead of the packaged runtime')
    parser.add_argument('--restart-during-restore', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix='ms-restore-', dir='/private/tmp' if os.uname().sysname == 'Darwin' else None)).resolve()
    config = root / 'server.json'
    executable = str(args.executable.resolve())
    init_args = [executable, 'init', '--config', str(config), '--data-dir', str(root / 'data'), '--port', '0']
    if args.project:
        init_args.extend(['--development-root', str(args.project.resolve())])
    subprocess.run(init_args, check=True, capture_output=True)
    log = (root / 'service.log').open('w')
    process = subprocess.Popen([executable, 'run', '--config', str(config)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, text=True)
    print(json.dumps({'data_root': str(root)}), flush=True)
    try:
        lines: Queue[str] = Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        info = json.loads(lines.get(timeout=15))
        authority = info['baseUrl'].removeprefix('http://').removesuffix('/api')
        def operator(command: str) -> dict:
            result = subprocess.run([executable, command, '--config', str(config)], capture_output=True, text=True, check=True, timeout=10)
            return json.loads(result.stdout)
        def wait_ready() -> None:
            deadline = time.monotonic() + 180
            while not operator('status').get('runtime_ready'):
                if time.monotonic() > deadline or process.poll() is not None: raise RuntimeError('Service did not become ready')
                time.sleep(0.25)
        wait_ready()
        token = None
        def call(method: str, path: str, payload=None, *, credential=None, disconnect=False):
            connection = http.client.HTTPConnection(authority, timeout=40)
            headers = {'content-type': 'application/octet-stream' if isinstance(payload, bytes) else 'application/json'}
            if credential or token: headers['x-magi-session-token'] = credential or token
            try:
                connection.request(method, path, payload if isinstance(payload, bytes) else json.dumps(payload) if payload is not None else None, headers)
                response = connection.getresponse()
                if disconnect:
                    assert response.status == 202, response.status
                    return None
                raw = response.read()
                try: result = json.loads(raw)
                except ValueError: result = raw.decode()
                return response.status, result
            finally: connection.close()
        grant = operator('pair')
        code, paired = call('POST', '/api/auth/pair', {'name': 'Restore validation'}, credential=grant['pairing_token'])
        assert code == 200, paired
        code, session = call('POST', '/api/auth/session', {}, credential=paired['data']['client_credential'])
        assert code == 200, session
        token = session['data']['access_token']
        _, initial = call('GET', '/api/server/info')
        original = initial['data']['maintenance']
        def wait_operation(operation: dict) -> dict:
            deadline = time.monotonic() + 180
            while operation['status'] in ('pending', 'running'):
                assert time.monotonic() < deadline, operation
                time.sleep(0.25)
                code, operation = call('GET', f'/api/memory/portability/operations/{operation["operation_id"]}')
                assert code == 200, operation
            assert operation['status'] == 'succeeded', operation
            return operation
        destination = root / 'backups'
        destination.mkdir()
        code, operation = call('POST', '/api/memory/portability/backups', {'destination_directory': str(destination), 'encryption': 'none'})
        assert code == 202, (code, operation)
        backup = wait_operation(operation)
        artifact = Path(backup['output_path'])
        content = artifact.read_bytes()
        resource_id = str(uuid4())
        spec = {'resource_id': resource_id, 'name': artifact.name, 'source_name': artifact.name, 'last_modified_ms': int(artifact.stat().st_mtime * 1000), 'purpose': 'restore', 'size': len(content)}
        code, uploaded = call('POST', '/api/files/uploads', spec)
        assert code == 200, uploaded
        for offset in range(0, len(content), 1024 * 1024):
            chunk = content[offset:offset + 1024 * 1024]
            code, uploaded = call('PUT', f'/api/files/uploads/{resource_id}?offset={offset}&sha256={hashlib.sha256(chunk).hexdigest()}', chunk)
            assert code == 200, uploaded
        code, inspection = call('POST', '/api/memory/portability/restores/inspect', {'resource_id': resource_id})
        assert code == 202, inspection
        inspected = wait_operation(inspection)
        candidate_id = inspected['inspection']['candidate_id']
        original_pid = (root / 'data/runtime/worker.ready').read_text()
        endpoint = f'/api/memory/portability/restores/{candidate_id}/confirm'
        call('POST', endpoint, {}, disconnect=True)
        deadline = time.monotonic() + 180
        observed_phases = set()
        restarted = False
        while time.monotonic() < deadline:
            code, envelope = call('GET', f'/api/server/maintenance/{candidate_id}')
            if code == 404:
                time.sleep(0.1)
                continue
            assert code == 200, (code, envelope)
            maintenance = envelope['data']
            observed_phases.add(maintenance['phase'])
            assert maintenance['kind'] == 'restore', maintenance
            if args.restart_during_restore and not restarted and maintenance['phase'] == 'restoring':
                worker_pid = int((root / 'data/runtime/worker.ready').read_text())
                process.kill()
                process.wait(timeout=5)
                worker_deadline = time.monotonic() + 30
                while True:
                    try: os.kill(worker_pid, 0)
                    except ProcessLookupError: break
                    if time.monotonic() > worker_deadline: raise RuntimeError('Orphan worker did not release the data root')
                    time.sleep(0.1)
                process = subprocess.Popen([executable, 'run', '--config', str(config)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, text=True)
                restart_lines: Queue[str] = Queue()
                threading.Thread(target=lambda: restart_lines.put(process.stdout.readline()), daemon=True).start()
                restarted_info = json.loads(restart_lines.get(timeout=15))
                authority = restarted_info['baseUrl'].removeprefix('http://').removesuffix('/api')
                code, session = call('POST', '/api/auth/session', {}, credential=paired['data']['client_credential'])
                assert code == 200, session
                token = session['data']['access_token']
                restarted = True
                continue
            assert maintenance['phase'] != 'failed', maintenance
            if maintenance['phase'] == 'completed': break
            assert call('GET', '/api/config/')[0] == 503
            time.sleep(0.1)
        else: raise RuntimeError('Restore did not complete')
        if not args.restart_during_restore: assert maintenance['result']['success'] is True, maintenance
        if args.restart_during_restore: assert restarted, observed_phases
        wait_ready()
        assert (root / 'data/runtime/worker.ready').read_text() != original_pid
        code, repeated = call('POST', endpoint, {})
        assert code == 202 and repeated['data']['phase'] == 'completed', repeated
        assert repeated['data']['operation_id'] == candidate_id
        assert repeated['data']['content_epoch'] == original['content_epoch']
        assert repeated['data']['data_epoch'] == candidate_id
        code, operation = call('GET', f'/api/memory/portability/operations/{candidate_id}')
        assert code == 200 and operation['status'] in ('succeeded', 'failed'), operation
        if not args.restart_during_restore: assert operation['status'] == 'succeeded', operation
        if operation['status'] == 'succeeded': assert operation['safety_backup_path'] and Path(operation['safety_backup_path']).is_file()
        # Restored or safely rolled-back storage must support a fresh consistent backup.
        code, after = call('POST', '/api/memory/portability/backups', {'destination_directory': str(destination), 'encryption': 'none'})
        assert code == 202, after
        wait_operation(after)
        assert not (root / 'data/service/memory-restore.pending.json').exists()
        print(json.dumps({'result': 'passed', 'data_root': str(root), 'backup_bytes': len(content), 'phases': sorted(observed_phases), 'disconnected_confirmation': True, 'idempotent_confirmation': True, 'content_epoch_preserved': True, 'service_restart': restarted, 'restore_outcome': operation['status']}), flush=True)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try: process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(); raise RuntimeError('Service did not stop cleanly')
        log.close()
        if process.returncode != 0: raise RuntimeError(f'Service exit status {process.returncode}')


if __name__ == '__main__':
    main()
