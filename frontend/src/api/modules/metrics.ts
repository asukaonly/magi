import { api } from '../client';

export interface LLMUsageTotals {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  calls_with_usage: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  avg_latency_ms: number;
  total_cost_usd?: number | null;
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
  successful_calls?: number | null;
  failed_calls?: number | null;
  avg_latency_ms?: number | null;
  avg_ttft_ms?: number | null;
  cost_usd?: number | null;
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
  cost_usd?: number | null;
}

export interface LLMUsageTimeseries {
  window_days: number;
  points: LLMUsageTimeseriesPoint[];
}

export const metricsApi = {
  getLLMUsageSummary: (days = 7, modelLimit = 8) =>
    api.get<LLMUsageSummary>('/metrics/llm/usage/summary', {
      params: { days, model_limit: modelLimit },
    }),
  getLLMUsageTimeseries: (days = 7) =>
    api.get<LLMUsageTimeseries>('/metrics/llm/usage/timeseries', { params: { days } }),
};

export default metricsApi;
