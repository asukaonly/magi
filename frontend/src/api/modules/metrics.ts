import { api } from '../client';

export interface LLMUsageTotals {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  calls_with_usage: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_write_1h_tokens?: number | null;
  cache_hit_rate: number;
  avg_latency_ms: number;
  total_cost_usd?: number | null;
  cost_by_currency?: Array<{ currency: string; amount: number }> | null;
  avg_ttft_ms?: number | null;
}

export interface LLMUsageBreakdownItem {
  provider?: string;
  model?: string;
  request_kind?: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  cache_write_1h_tokens?: number | null;
  cache_hit_rate?: number | null;
  successful_calls?: number | null;
  failed_calls?: number | null;
  avg_latency_ms?: number | null;
  avg_ttft_ms?: number | null;
  cost_usd?: number | null;
  cost_currency?: string | null;
}

export interface LLMUsageSummary {
  window_days: number;
  totals: LLMUsageTotals;
  providers: LLMUsageBreakdownItem[];
  models: LLMUsageBreakdownItem[];
  request_kinds: LLMUsageBreakdownItem[];
}

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
  intent_success_rate?: number | null;
  intent_success_rate_available: boolean;
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
  model_execution: RuntimeOverviewModelExecution;
  memory: RuntimeOverviewMemory;
  scheduler: RuntimeOverviewScheduler;
}

export const metricsApi = {
  getLLMUsageSummary: (days = 7, modelLimit = 8) =>
    api.get<LLMUsageSummary>('/metrics/llm/usage/summary', {
      params: { days, model_limit: modelLimit },
    }),
  getLLMUsageTimeseries: (days = 7) =>
    api.get<LLMUsageTimeseries>('/metrics/llm/usage/timeseries', { params: { days } }),
  getRuntimeOverview: () => api.get<RuntimeOverview>('/metrics/runtime/overview'),
};

export default metricsApi;
