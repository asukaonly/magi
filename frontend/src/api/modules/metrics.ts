import { z } from 'zod';
import { api, type ApiResponse } from '../client';

export type UsageDisplayCurrency = 'CNY' | 'USD';
const count = z.number().int().nonnegative();
const amount = z.number().nonnegative();
const displayCosts = z.strictObject({ CNY: amount.nullable().optional(), USD: amount.nullable().optional() })
  .refine((cost) => (cost.CNY === undefined) === (cost.USD === undefined));
const charges = z.array(z.object({ currency: z.string().min(1), amount }));
const tokenCounts = { prompt_tokens: count, completion_tokens: count, total_tokens: count };
const breakdown = z.object({
  ...tokenCounts, calls: count, provider: z.string().optional(), model: z.string().optional(),
  request_kind: z.string().optional(), display_costs: displayCosts, cost_by_currency: charges,
  cost_usd: amount.nullish(), cost_currency: z.string().nullish(),
  cache_read_tokens: count.nullish(), cache_write_tokens: count.nullish(), cache_write_1h_tokens: count.nullish(),
  successful_calls: count.nullish(), failed_calls: count.nullish(), cache_hit_rate: amount.nullish(),
  avg_latency_ms: amount.nullish(), avg_ttft_ms: amount.nullish(),
});
const totals = z.object({
  ...tokenCounts, total_calls: count, successful_calls: count, failed_calls: count, calls_with_usage: count,
  unpriced_calls: count, unpriced_failed_without_usage: count, unpriced_success_without_usage: count,
  display_costs: displayCosts, cost_by_currency: charges, total_cost_usd: amount.nullish(),
  cache_read_tokens: count, cache_write_tokens: count, cache_write_1h_tokens: count.nullish(),
  cache_hit_rate: amount, avg_latency_ms: amount, avg_ttft_ms: amount.nullish(),
}).refine((row) => row.unpriced_calls <= row.total_calls &&
  row.unpriced_failed_without_usage + row.unpriced_success_without_usage <= row.unpriced_calls);
const usageSummary = z.object({
  window_days: count, totals,
  providers: z.array(breakdown.extend({ provider: z.string() })),
  models: z.array(breakdown.extend({ provider: z.string(), model: z.string() })),
  request_kinds: z.array(breakdown.extend({ request_kind: z.string() })),
  daily_display_costs: z.record(z.iso.date(), displayCosts),
});

export type LLMUsageTotals = z.infer<typeof totals>;
export type LLMUsageBreakdownItem = z.infer<typeof breakdown>;
export type LLMUsageSummary = z.infer<typeof usageSummary>;

export interface LLMUsageTimeseriesPoint {
  day: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  cache_write_1h_tokens?: number | null;
  cache_hit_rate?: number | null;
  cost_usd?: number | null;
  cost_by_currency?: Array<{ currency: string; amount: number }> | null;
}

export interface LLMUsageTimeseries {
  window_days: number;
  points: LLMUsageTimeseriesPoint[];
}

export interface RuntimeOverviewSystemMetrics {
  cpu_percent: number;
  memory_percent: number;
  memory_used_gb: number;
  memory_total_gb: number;
}

export interface RuntimeOverviewStatus {
  status: string;
  runtime_ready: boolean;
  runtime_status: string;
  queue_backlog_healthy?: boolean | null;
  pending_commands?: number | null;
}

export interface RuntimeOverviewModelExecution {
  avg_ttft_ms?: number | null;
  ttft_available: boolean;
  core_model_success_rate?: number | null;
  core_model_success_rate_available: boolean;
}

export interface RuntimeOverviewPendingLayer {
  pending: number;
  worker_running: boolean;
  vector_enabled: boolean;
  async_embeddings: boolean;
}

export interface RuntimeOverviewMemory {
  total_pending: number;
  l2: {
    is_running: boolean;
    extract_pending: number;
    reconcile_pending: number;
    snapshot_pending: number;
    total_pending: number;
  };
  embeddings: {
    total_pending: number;
    l1: RuntimeOverviewPendingLayer;
    l3: RuntimeOverviewPendingLayer;
    l4: RuntimeOverviewPendingLayer;
  };
}

export interface RuntimeOverviewSchedulerTarget {
  target_type: string;
  target_key: string;
  running: boolean;
  last_error?: string | null;
  next_run_at?: number | null;
  updated_at?: number | null;
}

export interface RuntimeOverviewScheduler {
  enabled_schedule_count: number;
  running_target_count: number;
  errored_target_count: number;
  upcoming_target_count: number;
  recent_targets: RuntimeOverviewSchedulerTarget[];
}

export interface RuntimeOverview {
  captured_at_ms: number;
  system: RuntimeOverviewSystemMetrics;
  runtime: RuntimeOverviewStatus;
  model_execution: RuntimeOverviewModelExecution | null;
  memory: RuntimeOverviewMemory | null;
  scheduler: RuntimeOverviewScheduler | null;
}

export const metricsApi = {
  getLLMUsageSummary: async (days = 7, modelLimit = 8): Promise<ApiResponse<LLMUsageSummary>> => {
    const result = await api.get<unknown>('/metrics/llm/usage/summary', {
      params: { days, model_limit: modelLimit, include_estimates: true },
    });
    return { ...result, data: result.success ? usageSummary.parse(result.data) : undefined };
  },
  getLLMUsageTimeseries: (days = 7) =>
    api.get<LLMUsageTimeseries>('/metrics/llm/usage/timeseries', { params: { days } }),
  getRuntimeOverview: () => api.get<RuntimeOverview>('/metrics/runtime/overview'),
};

export default metricsApi;
