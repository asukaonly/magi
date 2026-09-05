import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, apiClient } from '@/api/client';
import { memoryPortabilityApi, type MemoryPortabilityOperation } from '@/api/modules/memoryPortability';
import examples from '../../../contracts/api/frontend-lifecycle-examples.json';

const operation: MemoryPortabilityOperation = { ...examples.operation, kind: 'backup', status: 'pending' };

describe('memoryPortabilityApi contract', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('sends exact backup/export payloads and accepts only the requested operation kind', async () => {
    const postSpy = vi.spyOn(api, 'post')
      .mockResolvedValueOnce(operation as never)
      .mockResolvedValueOnce(operation as never)
      .mockResolvedValue({ ...operation, kind: 'export' } as never);
    await memoryPortabilityApi.createBackup({ destinationDirectory: '/private/backup folder', encryption: 'password', password: 'a private password' });
    await memoryPortabilityApi.createBackup({ destinationDirectory: '/private/plain backup', encryption: 'none' });
    await memoryPortabilityApi.createExport({ destinationDirectory: '/private/readable export' });
    expect(postSpy).toHaveBeenNthCalledWith(1, '/memory/portability/backups', { destination_directory: '/private/backup folder', encryption: 'password', password: 'a private password' });
    expect(postSpy).toHaveBeenNthCalledWith(2, '/memory/portability/backups', { destination_directory: '/private/plain backup', encryption: 'none' });
    expect(postSpy).toHaveBeenNthCalledWith(3, '/memory/portability/exports', { destination_directory: '/private/readable export', include_l0: false });
    await memoryPortabilityApi.createExport({ destinationDirectory: '/private/with attention', includeL0: true });
    expect(postSpy).toHaveBeenLastCalledWith('/memory/portability/exports', { destination_directory: '/private/with attention', include_l0: true });
    await expect(memoryPortabilityApi.createBackup({ destinationDirectory: '/private/plain backup', encryption: 'none' })).rejects.toThrow('Invalid memory portability operation');
  });

  it('starts inspection and restore operations and requires confirmed candidate deletion', async () => {
    const inspection = { ...operation, kind: 'inspect' };
    const postSpy = vi.spyOn(api, 'post')
      .mockResolvedValueOnce(inspection as never)
      .mockResolvedValueOnce({ ...inspection, operation_id: 'inspection-2' } as never)
      .mockResolvedValueOnce({ ...operation, kind: 'restore' } as never);
    const deleteSpy = vi.spyOn(apiClient, 'delete').mockResolvedValue({ status: 204 });
    expect((await memoryPortabilityApi.inspectRestore({ sourcePath: '/tmp/private.magibackup' })).kind).toBe('inspect');
    expect((await memoryPortabilityApi.inspectRestore({ sourcePath: '/tmp/private.magibackup', password: 'secret' })).operation_id).toBe('inspection-2');
    await memoryPortabilityApi.confirmRestore('candidate/with slash');
    await memoryPortabilityApi.discardRestoreCandidate('candidate/with slash');
    expect(postSpy).toHaveBeenNthCalledWith(1, '/memory/portability/restores/inspect', { source_path: '/tmp/private.magibackup' });
    expect(postSpy).toHaveBeenNthCalledWith(2, '/memory/portability/restores/inspect', { source_path: '/tmp/private.magibackup', password: 'secret' });
    expect(postSpy).toHaveBeenNthCalledWith(3, '/memory/portability/restores/candidate%2Fwith%20slash/confirm', {});
    expect(deleteSpy).toHaveBeenCalledWith('/memory/portability/restores/candidate%2Fwith%20slash');
    deleteSpy.mockResolvedValue({ status: 200, data: { success: false } });
    await expect(memoryPortabilityApi.discardRestoreCandidate('candidate/with slash')).rejects.toThrow('not confirmed');
  });

  it('distinguishes no active job from malformed responses and checks the requested identity', async () => {
    const getSpy = vi.spyOn(api, 'get')
      .mockResolvedValueOnce(null as never)
      .mockResolvedValueOnce(operation as never)
      .mockResolvedValueOnce({ ...operation, operation_id: 'operation/1' } as never);
    await expect(memoryPortabilityApi.getActiveOperation()).resolves.toBeNull();
    await expect(memoryPortabilityApi.getLatestOperation()).resolves.toEqual(operation);
    expect((await memoryPortabilityApi.getOperation('operation/1')).operation_id).toBe('operation/1');
    expect(getSpy).toHaveBeenLastCalledWith('/memory/portability/operations/operation%2F1');
    getSpy.mockResolvedValue(operation as never);
    await expect(memoryPortabilityApi.getOperation('another-job')).rejects.toThrow('Invalid memory portability operation');
    getSpy.mockResolvedValue({ success: false, data: null } as never);
    await expect(memoryPortabilityApi.getActiveOperation()).rejects.toThrow('Invalid memory portability operation');
  });
});
