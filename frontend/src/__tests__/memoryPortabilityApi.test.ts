import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/api/client';
import {
  memoryPortabilityApi,
  type MemoryPortabilityOperation,
} from '@/api/modules/memoryPortability';

const operation: MemoryPortabilityOperation = {
  operation_id: 'operation-1',
  kind: 'backup',
  status: 'pending',
  phase: 'queued',
  progress_percent: 0,
  record_counts: {},
  output_path: null,
  file_size_bytes: null,
  created_at: '2026-08-18T09:00:00Z',
  completed_at: null,
  error_code: null,
  error_message: null,
  rollback_performed: false,
  safety_backup_path: null,
  index_rebuild_status: null,
};

describe('memoryPortabilityApi contract', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sends backup and readable export requests with exact disk-path payloads', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      message: 'ok',
      data: operation,
    } as any);

    await memoryPortabilityApi.createBackup({
      destinationDirectory: '/private/backup folder',
      encryption: 'password',
      password: 'a private password',
    });
    await memoryPortabilityApi.createBackup({
      destinationDirectory: '/private/plain backup',
      encryption: 'none',
    });
    await memoryPortabilityApi.createExport({
      destinationDirectory: '/private/readable export',
    });

    expect(postSpy).toHaveBeenNthCalledWith(1, '/memory/portability/backups', {
      destination_directory: '/private/backup folder',
      encryption: 'password',
      password: 'a private password',
    });
    expect(postSpy).toHaveBeenNthCalledWith(2, '/memory/portability/backups', {
      destination_directory: '/private/plain backup',
      encryption: 'none',
    });
    expect(postSpy).toHaveBeenNthCalledWith(3, '/memory/portability/exports', {
      destination_directory: '/private/readable export',
      include_l0: true,
    });
  });

  it('inspects, confirms, and discards restore candidates without sending file contents', async () => {
    const postSpy = vi.spyOn(api, 'post')
      .mockResolvedValueOnce({
        success: true,
        message: 'password needed',
        data: { state: 'password_required', encrypted: true },
      } as any)
      .mockResolvedValueOnce({
        success: true,
        message: 'ready',
        data: {
          state: 'ready',
          candidate_id: 'candidate/with slash',
          encrypted: true,
          format_version: 1,
          magi_version: '0.1.26',
          created_at: '2026-08-18T09:00:00Z',
          scope: ['l1'],
          record_counts: { l1_events: 4 },
          compatibility: 'compatible',
          warnings: [],
          expires_at: '2026-08-18T09:30:00Z',
          source_fingerprint: 'abc',
        },
      } as any)
      .mockResolvedValueOnce({ success: true, message: 'ok', data: operation } as any);
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue({} as any);

    await memoryPortabilityApi.inspectRestore({ sourcePath: '/tmp/private.magibackup' });
    const ready = await memoryPortabilityApi.inspectRestore({
      sourcePath: '/tmp/private.magibackup',
      password: 'secret',
    });
    if (ready.state !== 'ready') {
      throw new Error('Expected ready inspection');
    }
    await memoryPortabilityApi.confirmRestore(ready.candidate_id);
    await memoryPortabilityApi.discardRestoreCandidate(ready.candidate_id);

    expect(postSpy).toHaveBeenNthCalledWith(
      1,
      '/memory/portability/restores/inspect',
      { source_path: '/tmp/private.magibackup' },
      { timeout: 120_000 },
    );
    expect(postSpy).toHaveBeenNthCalledWith(
      2,
      '/memory/portability/restores/inspect',
      { source_path: '/tmp/private.magibackup', password: 'secret' },
      { timeout: 120_000 },
    );
    expect(postSpy).toHaveBeenNthCalledWith(
      3,
      '/memory/portability/restores/candidate%2Fwith%20slash/confirm',
      {},
    );
    expect(deleteSpy).toHaveBeenCalledWith(
      '/memory/portability/restores/candidate%2Fwith%20slash',
    );
  });

  it('loads the active operation and polls a specific encoded operation id', async () => {
    const getSpy = vi.spyOn(api, 'get')
      .mockResolvedValueOnce({ success: true, message: 'ok', data: operation } as any)
      .mockResolvedValueOnce({ success: true, message: 'ok', data: operation } as any);

    await expect(memoryPortabilityApi.getActiveOperation()).resolves.toEqual(operation);
    await expect(memoryPortabilityApi.getOperation('operation/1')).resolves.toEqual(operation);

    expect(getSpy).toHaveBeenNthCalledWith(1, '/memory/portability/operations/active');
    expect(getSpy).toHaveBeenNthCalledWith(
      2,
      '/memory/portability/operations/operation%2F1',
    );
  });
});
