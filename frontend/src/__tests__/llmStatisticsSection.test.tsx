import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LLMStatisticsSection } from '@/components/settings/LLMStatisticsSection';
import { metricsApi } from '@/api/modules/metrics';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/api/modules/metrics', () => ({
  metricsApi: {
    getLLMUsageSummary: vi.fn(),
    getLLMUsageTimeseries: vi.fn(),
  },
}));

const summaryFixture = {
  window_days: 7,
  totals: {
    total_calls: 120,
    successful_calls: 114,
    failed_calls: 6,
    calls_with_usage: 110,
    prompt_tokens: 120000,
    completion_tokens: 54000,
    total_tokens: 174000,
    avg_latency_ms: 1860,
    total_cost_usd: 12.45,
    avg_ttft_ms: 620,
  },
  providers: [
    { provider: 'openai', calls: 70, prompt_tokens: 70000, completion_tokens: 28000, total_tokens: 98000, cost_usd: 8.4 },
    { provider: 'anthropic', calls: 50, prompt_tokens: 50000, completion_tokens: 26000, total_tokens: 76000, cost_usd: 4.05 },
  ],
  models: [
    { provider: 'openai', model: 'gpt-5', calls: 60, prompt_tokens: 60000, completion_tokens: 24000, total_tokens: 84000, cost_usd: 7.1, failed_calls: 2, avg_ttft_ms: 580 },
    { provider: 'anthropic', model: 'claude-sonnet', calls: 50, prompt_tokens: 50000, completion_tokens: 22000, total_tokens: 72000, cost_usd: 3.8, failed_calls: 1, avg_ttft_ms: 640 },
  ],
  request_kinds: [
    { request_kind: 'chat', calls: 90, prompt_tokens: 90000, completion_tokens: 40000, total_tokens: 130000, failed_calls: 4 },
    { request_kind: 'memory', calls: 30, prompt_tokens: 30000, completion_tokens: 14000, total_tokens: 44000, failed_calls: 2 },
  ],
};

const timeseriesFixture = {
  window_days: 7,
  points: [
    { day: '03-18', calls: 16, prompt_tokens: 14000, completion_tokens: 6000, total_tokens: 20000, cost_usd: 1.4 },
    { day: '03-19', calls: 18, prompt_tokens: 16000, completion_tokens: 7000, total_tokens: 23000, cost_usd: 1.7 },
    { day: '03-20', calls: 15, prompt_tokens: 12000, completion_tokens: 5000, total_tokens: 17000, cost_usd: 1.2 },
  ],
};

beforeEach(() => {
  vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValue({ data: summaryFixture } as any);
  vi.mocked(metricsApi.getLLMUsageTimeseries).mockResolvedValue({ data: timeseriesFixture } as any);
  vi.stubGlobal(
    'ResizeObserver',
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

describe('LLMStatisticsSection', () => {
  it('renders the shared statistics frame regions', async () => {
    render(<LLMStatisticsSection />);

    expect(await screen.findByTestId('statistics-page-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-signal-ribbon')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-main-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-summary-rail')).toBeInTheDocument();
  });

  it('loads toolbar filters, omits repeated local title copy, and switches windows', async () => {
    const user = userEvent.setup();
    render(<LLMStatisticsSection />);

    await waitFor(() => {
      expect(metricsApi.getLLMUsageSummary).toHaveBeenCalledWith(7, 8);
      expect(metricsApi.getLLMUsageTimeseries).toHaveBeenCalledWith(7);
    });

    expect(screen.queryByRole('heading', { name: 'settings.tabs.statisticsLlm' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '7D' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '30D' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'provider-filter' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'model-filter' })).toBeInTheDocument();
    expect(screen.getAllByText('gpt-5').length).toBeGreaterThan(0);
    expect(screen.getAllByText('openai').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: '30D' }));

    await waitFor(() => {
      expect(metricsApi.getLLMUsageSummary).toHaveBeenLastCalledWith(30, 8);
      expect(metricsApi.getLLMUsageTimeseries).toHaveBeenLastCalledWith(30);
    });
  });

  it('shows an explicit empty state when no calls are available', async () => {
    vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValueOnce({
      data: {
        ...summaryFixture,
        totals: {
          ...summaryFixture.totals,
          total_calls: 0,
          successful_calls: 0,
          failed_calls: 0,
          total_tokens: 0,
          prompt_tokens: 0,
          completion_tokens: 0,
          total_cost_usd: 0,
        },
      },
    } as any);
    vi.mocked(metricsApi.getLLMUsageTimeseries).mockResolvedValueOnce({ data: { window_days: 7, points: [] } } as any);

    render(<LLMStatisticsSection />);

    expect(await screen.findByText('settings.usage.emptyTitle')).toBeInTheDocument();
  });
});
