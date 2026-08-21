import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  unwrapGatewayPayload: <T,>(payload: { success?: boolean; data?: T } | T): T => {
    if (
      payload &&
      typeof payload === 'object' &&
      'success' in (payload as Record<string, unknown>) &&
      'data' in (payload as Record<string, unknown>)
    ) {
      return (payload as { data: T }).data;
    }
    return payload as T;
  },
}));

import { api } from '@/api/client';
import {
  fetchAvailability,
  refreshAvailability,
  type AvailabilityEntry,
} from '@/api/modules/availability';

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);

describe('availability client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetchAvailability calls GET /availability with comma-joined ids', async () => {
    mockedGet.mockResolvedValue({
      entries: [
        {
          plugin_id: 'chrome-history',
          available: true,
          reason: 'available',
          detail: null,
          checked_at: '2026-05-28T00:00:00Z',
        },
      ],
    } as any);

    const entries: AvailabilityEntry[] = await fetchAvailability([
      'chrome-history',
      'git-activity',
    ]);

    expect(mockedGet).toHaveBeenCalledWith('/availability', {
      params: { plugin_ids: 'chrome-history,git-activity' },
    });
    expect(entries).toHaveLength(1);
    expect(entries[0].plugin_id).toBe('chrome-history');
  });

  it('fetchAvailability without ids requests all', async () => {
    mockedGet.mockResolvedValue({ entries: [] } as any);
    await fetchAvailability();
    expect(mockedGet).toHaveBeenCalledWith('/availability', { params: {} });
  });

  it('fetchAvailability unwraps legacy success envelope', async () => {
    mockedGet.mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        entries: [
          {
            plugin_id: 'git-activity',
            available: false,
            reason: 'missing_executable',
            detail: 'git not on PATH',
            checked_at: '2026-05-28T00:00:00Z',
          },
        ],
      },
    } as any);

    const entries = await fetchAvailability(['git-activity']);
    expect(entries).toHaveLength(1);
    expect(entries[0].available).toBe(false);
    expect(entries[0].reason).toBe('missing_executable');
  });

  it('refreshAvailability posts ids', async () => {
    mockedPost.mockResolvedValue({
      invalidated_plugin_ids: ['chrome-history'],
    } as any);
    const result = await refreshAvailability(['chrome-history']);
    expect(mockedPost).toHaveBeenCalledWith('/availability/refresh', {
      plugin_ids: ['chrome-history'],
    });
    expect(result).toEqual(['chrome-history']);
  });

  it('refreshAvailability without args clears all', async () => {
    mockedPost.mockResolvedValue({ invalidated_plugin_ids: [] } as any);
    await refreshAvailability();
    expect(mockedPost).toHaveBeenCalledWith('/availability/refresh', {});
  });
});
