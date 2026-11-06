import { beforeEach, expect, it, vi } from 'vitest';
const transport = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/api/client', () => ({ api: transport, unwrapGatewayPayload: (value: unknown) => value }));
import { timelineApi } from '@/api/modules/timeline';

const period = { start: 0, end: 86400, target_start: 0, scale: 'day', summary: 'Reviewed results', event_count: 10, source_types: ['chrome_history'], has_summary: false };
const review = { periods: [period], topics: [], summary_status: 'pending', summary_updated_at: null, active_days: 1 };
beforeEach(() => vi.resetAllMocks());
it('validates bounded period data and forwards cancellation and timezone', async () => {
  transport.get.mockResolvedValue({ period_review: review });
  const controller = new AbortController();
  expect((await timelineApi.getViewport({ scale: 'week', start: 0, end: 86400, timezone: 'Asia/Shanghai', signal: controller.signal })).period_review).toEqual(review);
  expect(transport.get.mock.calls[0][1]).toMatchObject({ signal: controller.signal, params: { timezone: 'Asia/Shanghai' } });
});
it.each([
  undefined, { ...review, periods: Array.from({ length: 1000 }, () => period) },
  { ...review, periods: [{ ...period, start: 'yesterday' }] },
  { ...review, summary_status: 'invented' }, { ...review, active_days: -1 },
])('rejects malformed period contracts', async period_review => {
  transport.get.mockResolvedValue({ period_review });
  await expect(timelineApi.getViewport({ scale: 'month', start: 0, end: 86400 })).rejects.toThrow();
});
