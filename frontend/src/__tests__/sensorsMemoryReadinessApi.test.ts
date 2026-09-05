import { describe, expect, it, vi, beforeEach } from 'vitest';
import { api } from '@/api/client';
import { sensorsApi } from '@/api/modules/sensors';

describe('sensors api - getMemoryReadiness', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('GETs the source readiness path with max_wait_ms and unwraps the payload', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      source_name: 'photo_library',
      l1_event_count: 5,
      l2_ready: true,
      l2_total_count: 5,
      l2_processed_count: 5,
      l2_remaining_count: 0,
    } as any);

    const res = await sensorsApi.getMemoryReadiness('photo_library', 'photos-a', { maxWaitMs: 3000 });

    expect(get).toHaveBeenCalledWith(
      '/sensors/photo_library/memory-readiness',
      { params: { connection_id: 'photos-a', max_wait_ms: 3000 } },
    );
    expect(res.l2_ready).toBe(true);
    expect(res.l1_event_count).toBe(5);
    expect(res.l2_remaining_count).toBe(0);
  });

  it('keeps the connection selector when maxWaitMs is not provided', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      source_name: 'photo_library',
      l1_event_count: 0,
      l2_ready: false,
    } as any);

    await sensorsApi.getMemoryReadiness('photo_library', 'photos-b');

    expect(get).toHaveBeenCalledWith('/sensors/photo_library/memory-readiness', { params: { connection_id: 'photos-b' } });
  });

  it('url-encodes the source name', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      source_name: 'odd/name',
      l1_event_count: 0,
      l2_ready: false,
    } as any);

    await sensorsApi.getMemoryReadiness('odd/name', 'photos-c', { maxWaitMs: 100 });

    expect(get).toHaveBeenCalledWith(
      '/sensors/odd%2Fname/memory-readiness',
      { params: { connection_id: 'photos-c', max_wait_ms: 100 } },
    );
  });
});
