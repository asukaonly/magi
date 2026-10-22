import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { personalTasksApi } from '@/api/modules/personalTasks';
import { personalDetail, personalItem } from './fixtures/personalTasks';

beforeEach(() => vi.restoreAllMocks());

describe('personal task response boundaries', () => {
  it('validates detail identity and preserves the full context', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({success: true, message: '', data: personalDetail()});
    expect((await personalTasksApi.get('item-one')).item.body_md).toContain('Local deployment');
    get.mockResolvedValue({success: true, message: '', data: personalDetail(personalItem({id: 'another-item'}))});
    await expect(personalTasksApi.get('item-one')).rejects.toThrow('identity mismatch');
  });

  it('rejects partial or invalid persisted records', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({success: true, message: '', data: {items: [{...personalItem(), status: 'unknown'}], total: 1, next_offset: null, counts: {}}});
    await expect(personalTasksApi.list({})).rejects.toThrow();
  });

  it('does not accept a mutation receipt for another item or an empty result', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({success: true, message: '', data: {item: personalItem({id: 'wrong'}), deleted_ids: [], replayed: false, reminders_pending: false}});
    const command = {request_id: 'request', action: 'update' as const, item_id: 'item-one', expected_version: 1, fields: {title: 'Changed'}};
    await expect(personalTasksApi.mutate(command)).rejects.toThrow('identity mismatch');
    post.mockResolvedValue({success: true, message: '', data: {item: null, deleted_ids: [], replayed: false, reminders_pending: false}});
    await expect(personalTasksApi.mutate({...command, item_id: undefined, action: 'create'})).rejects.toThrow('no result');
    post.mockResolvedValue({success: true, message: '', data: {item: null, deleted_ids: ['item-one'], replayed: true, reminders_pending: false}});
    expect((await personalTasksApi.mutate({...command, action: 'delete'})).replayed).toBe(true);
  });
});
