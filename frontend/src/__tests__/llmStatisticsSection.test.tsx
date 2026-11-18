import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createInstance } from 'i18next';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LLMStatisticsSection } from '@/components/settings/LLMStatisticsSection';
import { metricsApi, type LLMUsageSummary, type LLMUsageTimeseries } from '@/api/modules/metrics';
import { APP_EVENTS } from '@/constants/events';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';

const { translate } = vi.hoisted(() => ({ translate: vi.fn((key: string) => key) }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: translate }),
}));

vi.mock('@/api/modules/metrics', () => ({
  metricsApi: {
    getLLMUsageSummary: vi.fn(),
    getLLMUsageTimeseries: vi.fn(),
  },
}));

const summaryFixture: LLMUsageSummary = {
  window_days: 7,
  totals: {
    total_calls: 120,
    successful_calls: 114,
    failed_calls: 6,
    calls_with_usage: 110,
    prompt_tokens: 120000,
    completion_tokens: 54000,
    total_tokens: 174000,
    cache_read_tokens: 75000,
    cache_write_tokens: 18000,
    cache_hit_rate: 62.5,
    avg_latency_ms: 1860,
    total_cost_usd: 12.45,
    cost_by_currency: [
      { currency: 'USD', amount: 8.4 },
      { currency: 'CNY', amount: 28.05 },
    ],
    avg_ttft_ms: 620,
  },
  providers: [
    { provider: 'openai', calls: 70, prompt_tokens: 70000, completion_tokens: 28000, total_tokens: 98000, cache_read_tokens: 50000, cache_write_tokens: 12000, cache_hit_rate: 71.43, cost_usd: 8.4, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 8.4 }] },
    { provider: 'anthropic', calls: 50, prompt_tokens: 50000, completion_tokens: 26000, total_tokens: 76000, cache_read_tokens: 25000, cache_write_tokens: 6000, cache_hit_rate: 50, cost_usd: 4.05, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 4.05 }] },
  ],
  models: [
    { provider: 'openai', model: 'gpt-5', calls: 60, prompt_tokens: 60000, completion_tokens: 24000, total_tokens: 84000, cache_read_tokens: 42000, cache_write_tokens: 10000, cache_hit_rate: 70, cost_usd: 7.1, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 7.1 }], failed_calls: 2, avg_ttft_ms: 580 },
    { provider: 'anthropic', model: 'claude-sonnet', calls: 50, prompt_tokens: 50000, completion_tokens: 22000, total_tokens: 72000, cache_read_tokens: 25000, cache_write_tokens: 6000, cache_hit_rate: 50, cost_usd: 3.8, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 3.8 }], failed_calls: 1, avg_ttft_ms: 640 },
  ],
  request_kinds: [
    { request_kind: 'task_agent:chat_direct', calls: 90, prompt_tokens: 90000, completion_tokens: 40000, total_tokens: 130000, cache_read_tokens: 60000, cache_write_tokens: 14000, cache_hit_rate: 66.67, cost_usd: 8.9, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 8.9 }], failed_calls: 4, avg_latency_ms: 1200, avg_ttft_ms: 320 },
    { request_kind: 'function_calling:worker_tools', calls: 12, prompt_tokens: 18000, completion_tokens: 3000, total_tokens: 21000, cache_read_tokens: 3000, cache_write_tokens: 1500, cache_hit_rate: 16.67, cost_usd: 1.1, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 1.1 }], failed_calls: 1, avg_latency_ms: 1500 },
    { request_kind: 'task_agent:failure_status', calls: 2, prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500, cache_read_tokens: 0, cache_write_tokens: 0, cache_hit_rate: 0, cost_usd: 0.05, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 0.05 }], failed_calls: 0, avg_latency_ms: 900 },
    { request_kind: 'memory:l2_phase1_extract', calls: 30, prompt_tokens: 30000, completion_tokens: 14000, total_tokens: 44000, cache_read_tokens: 12000, cache_write_tokens: 4000, cache_hit_rate: 40, cost_usd: 3.2, cost_currency: 'USD', cost_by_currency: [{ currency: 'USD', amount: 3.2 }], failed_calls: 2, avg_latency_ms: 2400 },
  ],
};

const timeseriesFixture: LLMUsageTimeseries = {
  window_days: 7,
  points: [
    { day: '03-18', calls: 16, prompt_tokens: 14000, completion_tokens: 6000, total_tokens: 20000, cache_read_tokens: 7000, cache_write_tokens: 2000, cache_hit_rate: 50, cost_usd: 1.4 },
    { day: '03-19', calls: 18, prompt_tokens: 16000, completion_tokens: 7000, total_tokens: 23000, cache_read_tokens: 9000, cache_write_tokens: 3000, cache_hit_rate: 56.25, cost_usd: 1.7 },
    { day: '03-20', calls: 15, prompt_tokens: 12000, completion_tokens: 5000, total_tokens: 17000, cache_read_tokens: 8000, cache_write_tokens: 2500, cache_hit_rate: 66.67, cost_usd: 1.2 },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  translate.mockImplementation((key) => key);
  vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValue({ success: true, message: '', data: summaryFixture });
  vi.mocked(metricsApi.getLLMUsageTimeseries).mockResolvedValue({ success: true, message: '', data: timeseriesFixture });
  vi.stubGlobal(
    'ResizeObserver',
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

it('reconciles the selected metrics window without resetting filters', async () => {
  render(<LLMStatisticsSection />);
  await userEvent.click(await screen.findByRole('button', { name: 'settings.usage.windows.30' }));
  await screen.findByRole('combobox', { name: 'settings.usage.providerFilter' });
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'settings.usage.providerFilter' }), 'openai');
  vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValue({ success: true, message: '', data: { ...summaryFixture, totals: { ...summaryFixture.totals, total_tokens: 999 } } });
  act(() => window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED)));
  await screen.findByText('999', {}, { timeout: 3000 });
  expect(metricsApi.getLLMUsageSummary).toHaveBeenLastCalledWith(30, 8);
  expect(screen.getByRole('combobox', { name: 'settings.usage.providerFilter' })).toHaveValue('openai');
  vi.mocked(metricsApi.getLLMUsageSummary).mockRejectedValue(new Error('Disconnected'));
  const previousReads = vi.mocked(metricsApi.getLLMUsageSummary).mock.calls.length;
  act(() => window.dispatchEvent(new Event('focus')));
  await waitFor(() => expect(metricsApi.getLLMUsageSummary).toHaveBeenCalledTimes(previousReads + 1), { timeout: 3000 });
  expect(screen.getByText('999')).toBeInTheDocument();
});

describe('LLMStatisticsSection', () => {
  it.each(['getLLMUsageSummary', 'getLLMUsageTimeseries'] as const)(
    'shows an error and recovers after %s rejects',
    async (method) => {
      vi.mocked(metricsApi[method]).mockRejectedValueOnce(new Error('503 Service unavailable'));
      const user = userEvent.setup();
      render(<LLMStatisticsSection />);

      expect(await screen.findByRole('alert')).toHaveTextContent('settings.usage.loadErrorTitle');
      expect(screen.queryByText('settings.usage.emptyTitle')).not.toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'settings.usage.retry' }));

      expect(await screen.findByTestId('statistics-page-toolbar')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(metricsApi[method]).toHaveBeenCalledTimes(2);
    }
  );

  it('does not treat an incomplete response as empty usage', async () => {
    vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValueOnce({ success: true, message: '' });
    render(<LLMStatisticsSection />);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('settings.usage.emptyTitle')).not.toBeInTheDocument();
  });

  it('does not show old statistics when a different window fails', async () => {
    const user = userEvent.setup();
    render(<LLMStatisticsSection />);
    await screen.findByTestId('statistics-page-toolbar');
    vi.mocked(metricsApi.getLLMUsageSummary).mockRejectedValueOnce(new Error('Request failed'));

    await user.click(screen.getByRole('button', { name: 'settings.usage.windows.30' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByTestId('statistics-page-signal-ribbon')).not.toBeInTheDocument();
    expect(screen.queryByText('settings.usage.emptyTitle')).not.toBeInTheDocument();
  });

  it('handles a pending rejection after the section unmounts', async () => {
    let rejectRequest: (reason: Error) => void = () => {};
    const pending = new Promise<Awaited<ReturnType<typeof metricsApi.getLLMUsageSummary>>>(
      (_resolve, reject) => { rejectRequest = reject; }
    );
    vi.mocked(metricsApi.getLLMUsageSummary).mockReturnValueOnce(pending);
    const { unmount } = render(<LLMStatisticsSection />);
    expect(screen.getByText('settings.usage.loading')).toBeInTheDocument();

    unmount();
    await act(async () => { rejectRequest(new Error('Request failed after unmount')); });

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('renders the statistics frame without the removed summary rail', async () => {
    render(<LLMStatisticsSection />);

    expect(await screen.findByTestId('statistics-page-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-signal-ribbon')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-main-canvas')).toBeInTheDocument();
    expect(screen.queryByTestId('statistics-page-summary-rail')).not.toBeInTheDocument();
  });

  it('renders the total cost per native currency joined with a separator', async () => {
    render(<LLMStatisticsSection />);

    expect(await screen.findByText('$8.40 · ¥28.1')).toBeInTheDocument();
  });

  it('loads toolbar filters, uses i18n window labels, and switches windows', async () => {
    const user = userEvent.setup();
    render(<LLMStatisticsSection />);

    await waitFor(() => {
      expect(metricsApi.getLLMUsageSummary).toHaveBeenCalledWith(7, 8);
      expect(metricsApi.getLLMUsageTimeseries).toHaveBeenCalledWith(7);
    });

    expect(screen.queryByRole('heading', { name: 'settings.tabs.statisticsLlm' })).not.toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'settings.usage.windows.7' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.usage.windows.30' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'settings.usage.providerFilter' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'settings.usage.modelFilter' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'settings.statistics.llm.tabs.models' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'settings.statistics.llm.tabs.providers' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'settings.statistics.llm.tabs.requestKinds' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'settings.fields.model' })).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.calls')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.totalTokens')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.promptTokens')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.completionTokens')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.cacheHitRate')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.cacheReadTokens')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.cost')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.avgLatency')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.avgTTFT')).toBeInTheDocument();
    expect(screen.getAllByText('gpt-5').length).toBeGreaterThan(0);
    expect(screen.getByText('63%')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'settings.statistics.llm.tabs.providers' }));
    expect(screen.getByRole('columnheader', { name: 'settings.fields.provider' })).toBeInTheDocument();
    expect(screen.getAllByText('openai').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: 'settings.statistics.llm.tabs.requestKinds' }));
    expect(screen.getByText('settings.statistics.llm.table.columns.scenario')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.table.columns.stage')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.requestKindScenarios.generalChat')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.requestKindStages.directReply')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.requestKindScenarios.toolConversation')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.requestKindStages.workerToolDecision')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.requestKindScenarios.taskAggregation')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.requestKindStages.failureStatus')).toBeInTheDocument();
    expect(screen.getByText('settings.tabs.memoryKnowledge')).toBeInTheDocument();
    expect(screen.getByText('settings.statistics.llm.requestKindStages.eventExtraction')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.usage.windows.30' }));

    await waitFor(() => {
      expect(metricsApi.getLLMUsageSummary).toHaveBeenLastCalledWith(30, 8);
      expect(metricsApi.getLLMUsageTimeseries).toHaveBeenLastCalledWith(30);
    });
  });

  it.each([['en', en], ['zh-CN', zh]] as const)('displays settings names and readable scenario steps in %s', async (language, app) => {
    const i18n = createInstance();
    await i18n.init({ lng: language, defaultNS: 'app', resources: { [language]: { app } }, fallbackLng: false });
    translate.mockImplementation((key) => i18n.t(key));
    const tabs = app.settings.tabs;
    const { requestKindStages: stages, requestKindScenarios: scenarios } = app.settings.statistics.llm;
    const rows = [
      ['memory:shared_post_turn_understanding', tabs.memoryWorkbench, stages.postTurnAttention],
      ['memory:l1_future_step', tabs.memoryEvents, stages.uncategorized],
      ['memory:l2_self_report_review', tabs.memoryKnowledge, stages.selfReportReview],
      ['memory:l3_temporal_summary_prose', tabs.memoryReflection, stages.temporalProse],
      ['memory:l3_temporal_summary_structure', tabs.memoryReflection, stages.temporalReview],
      ['memory:l3_temporal_summary_repair', tabs.memoryReflection, stages.temporalRepair],
      ['memory:l4_strategy_extraction', tabs.memorySkills, stages.strategyExtraction],
      ['plugin:future_step', scenarios.other, stages.uncategorized],
    ];
    vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValueOnce({
      success: true, message: '', data: {
        ...summaryFixture,
        request_kinds: rows.map(([request_kind]) => ({ ...summaryFixture.request_kinds[0], request_kind })),
      },
    });
    render(<LLMStatisticsSection />);
    await userEvent.click(await screen.findByRole('tab', { name: app.settings.statistics.llm.tabs.requestKinds }));
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('row').slice(1).map((row) =>
      within(row).getAllByRole('cell').slice(0, 2).map((cell) => cell.textContent)
    )).toEqual(rows.map(([, scenario, stage]) => [scenario, stage]));
    expect(table).not.toHaveTextContent(/\bL[0-4]\b|memory:|plugin:/i);
  });

  it('shows an explicit empty state when no calls are available', async () => {
    vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValueOnce({
      success: true,
      message: '',
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
    });
    vi.mocked(metricsApi.getLLMUsageTimeseries).mockResolvedValueOnce({ success: true, message: '', data: { window_days: 7, points: [] } });

    render(<LLMStatisticsSection />);

    expect(await screen.findByText('settings.usage.emptyTitle')).toBeInTheDocument();
  });

  it('keeps tab rendering stable when multiple providers share the same model name', async () => {
    const user = userEvent.setup();
    vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValueOnce({
      success: true,
      message: '',
      data: {
        ...summaryFixture,
        models: [
          { provider: 'zhipu', model: 'glm', calls: 20, prompt_tokens: 20000, completion_tokens: 9000, total_tokens: 29000, cost_usd: 1.2 },
          { provider: 'openai', model: 'glm', calls: 10, prompt_tokens: 12000, completion_tokens: 4000, total_tokens: 16000, cost_usd: 0.8 },
        ],
      },
    });

    render(<LLMStatisticsSection />);

    expect(await screen.findAllByText('glm')).toHaveLength(3);

    await user.click(screen.getByRole('tab', { name: 'settings.statistics.llm.tabs.providers' }));
    expect(screen.getAllByText('openai').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: 'settings.statistics.llm.tabs.models' }));
    expect(screen.getAllByText('glm')).toHaveLength(3);
  });
});

it('keeps multiple billing currencies in one provider row', async () => {
  vi.mocked(metricsApi.getLLMUsageSummary).mockResolvedValueOnce({
    success: true, message: '', data: {
      ...summaryFixture,
      providers: [{ ...summaryFixture.providers[0], cost_usd: null, cost_currency: null,
        cost_by_currency: [{ currency: 'USD', amount: 1.25 }, { currency: 'CNY', amount: 9.6 }] }],
    },
  });
  render(<LLMStatisticsSection />);
  await userEvent.click(await screen.findByRole('tab', { name: 'settings.statistics.llm.tabs.providers' }));
  expect(await screen.findByText('$1.25 · ¥9.60')).toBeInTheDocument();
});
