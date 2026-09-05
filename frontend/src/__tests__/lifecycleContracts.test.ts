import { afterEach, describe, expect, it, vi } from 'vitest';
import examples from '../../../contracts/api/frontend-lifecycle-examples.json';
import {
  parseHistoryImportJob, parseHistoryImportAppend, parseHistoryImporters, parseHistoryImportList,
  parseHistorySourcePreview, parseMemoryOperation, parseClearMemory, parseDeletedEvent,
  parseForgottenEntity, parseForgottenEpisode,
} from '@/api/lifecycle-contract';
import { messagesApi } from '@/api/modules/messages';
import { memoryApi } from '@/api/modules/memory';
import { api, apiClient } from '@/api/client';
import { historyImportsApi } from '@/api/modules/historyImports';

afterEach(() => { vi.restoreAllMocks(); });

describe('production data lifecycle serialization', () => {
  it('consumes production import, portability and deletion fixtures', () => {
    expect(parseHistoryImportJob(examples.importJob).job_id).toBe('fixture-import');
    expect(parseHistoryImportAppend(examples.importAppend, 'fixture-import').added_source_count).toBe(1);
    expect(parseHistoryImporters([examples.importer])).toHaveLength(1);
    expect(parseHistoryImportList([examples.importJob])).toHaveLength(1);
    expect(parseHistorySourcePreview(examples.sourcePreview, 'fixture-source').truncated).toBe(false);
    expect(parseMemoryOperation(examples.completedExport).output_path).toBe('/fixture/export.zip');
    expect(parseMemoryOperation(examples.inspection).inspection?.state).toBe('ready');
    expect(parseClearMemory(examples.clearMemory).success).toBe(true);
    expect(parseDeletedEvent(examples.deleteEvent, 'fixture-event').deleted).toBe(true);
    expect(parseForgottenEntity(examples.forgetEntity).l1_events_deleted).toBe(1);
    expect(parseForgottenEpisode(examples.forgetEpisode, 'fixture-episode').event_ids).toEqual(['fixture-event']);
  });

  it.each([
    { ...examples.importJob, status: 'invented' },
    { ...examples.importJob, imported_count: '3' },
    { ...examples.importJob, participants: [{}] },
    { ...examples.importJob, quick_ready: undefined },
    { success: true, data: examples.importJob },
  ])('rejects invalid import snapshots instead of granting readiness', (payload) => {
    expect(() => parseHistoryImportJob(payload)).toThrow();
  });

  it('rejects identity drift, incomplete outputs and partial clear confirmations', () => {
    expect(() => parseHistoryImportJob(examples.importJob, 'another')).toThrow();
    expect(() => parseHistoryImportList({ items: [] })).toThrow();
    expect(() => parseMemoryOperation({ ...examples.completedExport, output_path: null })).toThrow();
    expect(() => parseMemoryOperation({ ...examples.inspection, inspection: null })).toThrow();
    expect(() => parseMemoryOperation({ ...examples.operation, progress_percent: 101 })).toThrow();
    expect(() => parseClearMemory({ ...examples.clearMemory, success: false })).toThrow();
    expect(() => parseClearMemory({ ...examples.clearMemory, results: { ...examples.clearMemory.results, l1: { cleared: false, count: 0 } } })).toThrow();
    expect(() => parseDeletedEvent(examples.deleteEvent, 'another')).toThrow();
    expect(() => parseForgottenEpisode(examples.forgetEpisode, 'another')).toThrow();
  });

  it('only accepts matching confirmed chat deletion snapshots at the API boundary', async () => {
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue(examples.deleteMessage as never);
    await expect(messagesApi.deleteMessage('fixture-user', 'fixture-session', 'fixture-message')).resolves.toEqual(examples.deleteMessage);
    await expect(messagesApi.deleteMessage('fixture-user', 'fixture-session', 'another-message')).rejects.toThrow();
    deleteSpy.mockResolvedValue({ ...examples.deleteSession, success: false } as never);
    await expect(messagesApi.deleteSession('fixture-user', 'fixture-session')).rejects.toThrow();
    deleteSpy.mockResolvedValue(examples.deleteSession as never);
    await expect(messagesApi.deleteSession('fixture-user', 'fixture-session')).resolves.toEqual(examples.deleteSession);
    vi.spyOn(api, 'post').mockResolvedValue(examples.clearHistory as never);
    await expect(messagesApi.clearHistory('fixture-user', 'fixture-session')).resolves.toEqual(examples.clearHistory);
    await expect(messagesApi.clearHistory('fixture-user', 'another-session')).rejects.toThrow();
  });

  it('rejects unconfirmed memory deletion and validates import removal status', async () => {
    vi.spyOn(api, 'delete').mockResolvedValue({ ...examples.deleteEvent, deleted: false } as never);
    await expect(memoryApi.deleteL1Event('fixture-event')).rejects.toThrow();
    const deletion = vi.spyOn(apiClient, 'delete').mockResolvedValue({ status: 200, data: { success: false } });
    await expect(historyImportsApi.delete('fixture-import')).rejects.toThrow();
    deletion.mockResolvedValue({ status: 204 });
    await expect(historyImportsApi.delete('fixture-import')).resolves.toBeUndefined();
  });
});
