import { expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { metricsApi } from '@/api/modules/metrics';

vi.mock('@/api/client', () => ({ api: { get: vi.fn() } }));

const totals = {
  total_calls: 1, successful_calls: 1, failed_calls: 0, calls_with_usage: 1,
  unpriced_calls: 0, unpriced_failed_without_usage: 0, unpriced_success_without_usage: 0,
  display_costs: { CNY: null, USD: 1 }, cost_by_currency: [{ currency: 'USD', amount: 1 }],
  prompt_tokens: 10, completion_tokens: 1, total_tokens: 11,
  cache_read_tokens: 0, cache_write_tokens: 0, cache_hit_rate: 0, avg_latency_ms: 10,
};
const summary = { window_days: 7, totals, providers: [], models: [], request_kinds: [],
  daily_display_costs: { '2026-11-20': totals.display_costs } };

it('requests the daily estimates and accepts an unavailable exchange rate', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ success: true, message: '', data: summary });
  expect((await metricsApi.getLLMUsageSummary()).data).toEqual(summary);
  expect(api.get).toHaveBeenCalledWith('/metrics/llm/usage/summary', { params: { days: 7, model_limit: 8, include_estimates: true } });
});

it.each([{ display_costs: { CNY: '7', USD: 1 } }, { display_costs: { CNY: 7 } },
  { unpriced_failed_without_usage: 1 }])('rejects invalid amounts and inconsistent fee reasons', async (invalid) => {
  vi.mocked(api.get).mockResolvedValueOnce({ success: true, message: '', data: { ...summary, totals: { ...totals, ...invalid } } });
  await expect(metricsApi.getLLMUsageSummary()).rejects.toThrow();
});
