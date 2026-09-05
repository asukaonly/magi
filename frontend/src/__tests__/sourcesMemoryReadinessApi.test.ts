import { describe, expect, it, vi, beforeEach } from 'vitest';
import { api } from '@/api/client';
import { sourcesApi } from '@/api/modules/sources';

describe('sources api - getMemoryReadiness', () => {
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

    const res = await sourcesApi.getMemoryReadiness('photo_library', 'photos-a', { maxWaitMs: 3000 });

    expect(get).toHaveBeenCalledWith(
      '/sources/photo_library/memory-readiness',
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

    await sourcesApi.getMemoryReadiness('photo_library', 'photos-b');

    expect(get).toHaveBeenCalledWith('/sources/photo_library/memory-readiness', { params: { connection_id: 'photos-b' } });
  });

  it('url-encodes the source name', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      source_name: 'odd/name',
      l1_event_count: 0,
      l2_ready: false,
    } as any);

    await sourcesApi.getMemoryReadiness('odd/name', 'photos-c', { maxWaitMs: 100 });

    expect(get).toHaveBeenCalledWith(
      '/sources/odd%2Fname/memory-readiness',
      { params: { connection_id: 'photos-c', max_wait_ms: 100 } },
    );
  });
});


describe('sources api - source operations', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('loads status without conflating semantic source names and contribution identifiers', async () => {
    const payload = {
      sources: [{
        source_name: 'browser_history',
        contribution_id: 'chromium.history',
        plugin_id: 'chromium',
        connection_id: 'browser-work',
      }],
    };
    const get = vi.spyOn(api, 'get').mockResolvedValue({ success: true, message: 'ok', data: payload });

    expect(await sourcesApi.getStatus()).toEqual(payload);
    expect(get).toHaveBeenCalledExactlyOnceWith('/sources/status');
  });

  it('preserves the optional day filter on semantic source summaries', async () => {
    const payload = { date: '2026-09-05', weekday: 5, sources: [] };
    const get = vi.spyOn(api, 'get').mockResolvedValue({ success: true, message: 'ok', data: payload });

    expect(await sourcesApi.getTodaySummary('2026-09-05')).toEqual(payload);
    expect(get).toHaveBeenLastCalledWith('/sources/today-summary', { params: { day: '2026-09-05' } });
    await sourcesApi.getTodaySummary();
    expect(get).toHaveBeenLastCalledWith('/sources/today-summary', undefined);
  });

  it('syncs the semantic source for the selected connection with the original payload', async () => {
    const payload = { queued: true, source_name: 'browser/history', connection_id: 'browser-work' };
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: 'ok', data: payload });

    expect(await sourcesApi.requestSync('browser/history', 'browser-work')).toEqual(payload);
    expect(post).toHaveBeenCalledExactlyOnceWith('/sources/browser%2Fhistory/sync', {}, {
      params: { connection_id: 'browser-work' },
    });
  });

  it('preserves first-context and custom backfill options for one connection', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: 'ok', data: { queued: true } });

    await sourcesApi.requestSync('browser_history', 'browser-home', {
      firstContext: true,
      mode: 'backfill',
      backfillScope: 'custom',
      backfillStartDate: '2026-09-01',
      backfillEndDate: '2026-09-05',
    });
    expect(post).toHaveBeenCalledExactlyOnceWith('/sources/browser_history/sync', {
      first_context: true,
      mode: 'backfill',
      backfill_scope: 'custom',
      backfill_start_date: '2026-09-01',
      backfill_end_date: '2026-09-05',
    }, { params: { connection_id: 'browser-home' } });
  });

  it('flushes state for the encoded source name and selected connection', async () => {
    const payload = { queued: true, source_name: 'activity/state' };
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: 'ok', data: payload });

    expect(await sourcesApi.requestStateFlush('activity/state', 'activity-work')).toEqual(payload);
    expect(post).toHaveBeenCalledExactlyOnceWith('/sources/activity%2Fstate/flush-state', {}, {
      params: { connection_id: 'activity-work' },
    });
  });

  it('keeps authorization field values and connection identity in their original locations', async () => {
    const fields = { 'sources.calendar.calendars': ['work'] };
    const payload = { authorized: true, requested_types: [], granted_types: [], denied_types: [] };
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: 'ok', data: payload });

    expect(await sourcesApi.requestAuthorization('calendar/events', 'calendar-work', fields)).toEqual(payload);
    expect(post).toHaveBeenCalledExactlyOnceWith('/sources/calendar%2Fevents/authorize', {
      field_values: fields,
    }, { params: { connection_id: 'calendar-work' } });
  });
});
