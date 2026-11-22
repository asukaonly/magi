import { useCallback, useEffect, useMemo, useState, type FC } from 'react';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { useTranslation } from 'react-i18next';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { metricsApi, type LLMUsageSummary, type LLMUsageTimeseriesPoint, type UsageDisplayCurrency } from '@/api/modules/metrics';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { formatUsageCost, UsageCostSummary } from './UsageCostSummary';
import { getUsageScenarioLabels } from './llmUsageScenarioLabels';
import { StatisticsPageFrame } from './StatisticsPageFrame';

const WINDOW_OPTIONS = [7, 30] as const;
const TABLE_TABS = ['models', 'providers', 'requestKinds'] as const;

type TableTab = (typeof TABLE_TABS)[number];

type UsageLoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'success'; summary: LLMUsageSummary; points: LLMUsageTimeseriesPoint[] };

const EMPTY_POINTS: LLMUsageTimeseriesPoint[] = [];

const formatCompactNumber = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);

const uniqueStrings = (values: Array<string | undefined>) => [...new Set(values.filter((value): value is string => Boolean(value)))];

const formatInteger = (value?: number | null) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(Number(value || 0));

const formatLatency = (value: number | null | undefined, locale: string) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '—';
  const seconds = value >= 1000;
  return new Intl.NumberFormat(locale, {
    style: 'unit', unit: seconds ? 'second' : 'millisecond', unitDisplay: 'narrow', maximumFractionDigits: seconds ? 1 : 0,
  }).format(seconds ? value / 1000 : value);
};

const formatPercent = (value: number) => `${Math.round(value)}%`;

const CURRENCY_PREFERENCE = 'magi_usage_display_currency';
const selectClass = 'h-8 max-w-full rounded-sm border border-border bg-transparent px-2 text-sm text-foreground focus-visible:outline-primary';
const tabClass = 'border-b-2 border-transparent px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground aria-selected:border-primary aria-selected:text-foreground aria-pressed:border-primary aria-pressed:text-foreground';

const computeSuccessRate = (summary: LLMUsageSummary | null) => {
  const totals = summary?.totals;
  if (!totals || totals.total_calls <= 0) return 0;
  return (totals.successful_calls / totals.total_calls) * 100;
};

const buildBreakdownRowKey = (
  activeTab: TableTab,
  item: {
    provider?: string;
    model?: string;
    request_kind?: string;
  },
  index: number
) => {
  if (activeTab === 'models') {
    return `${activeTab}-${item.provider || 'unknown'}-${item.model || 'unknown'}-${index}`;
  }
  if (activeTab === 'providers') {
    return `${activeTab}-${item.provider || 'unknown'}-${index}`;
  }
  return `${activeTab}-${item.request_kind || 'unknown'}-${index}`;
};

export const LLMStatisticsSection: FC = () => <LLMStatisticsSectionInner />;

const LLMStatisticsSectionInner: FC = () => {
  const { t, i18n } = useTranslation('app');
  const locale = i18n?.resolvedLanguage || document.documentElement.lang || 'en';
  const [preferredCurrency, setPreferredCurrency] = useState(() => localStorage.getItem(CURRENCY_PREFERENCE));
  const currency: UsageDisplayCurrency = preferredCurrency === 'CNY' || preferredCurrency === 'USD'
    ? preferredCurrency : locale.startsWith('zh') ? 'CNY' : 'USD';
  const [trend, setTrend] = useState<'tokens' | 'cost'>('tokens');
  const [windowDays, setWindowDays] = useState<(typeof WINDOW_OPTIONS)[number]>(7);
  const [loadState, setLoadState] = useState<UsageLoadState>({ status: 'loading' });
  const [retryAttempt, setRetryAttempt] = useState(0);
  const summary = loadState.status === 'success' ? loadState.summary : null;
  const timeseries = loadState.status === 'success' ? loadState.points : EMPTY_POINTS;
  const [providerFilter, setProviderFilter] = useState('all');
  const [modelFilter, setModelFilter] = useState('all');
  const [activeTab, setActiveTab] = useState<TableTab>('models');

  const beginRead = useRequestOwner(String(windowDays));
  const load = useCallback(async (silent = false) => {
    const isCurrent = beginRead('usage');
    if (!silent) setLoadState({ status: 'loading' });
    try {
      const [summaryResponse, timeseriesResponse] = await Promise.all([
        metricsApi.getLLMUsageSummary(windowDays, 8),
        metricsApi.getLLMUsageTimeseries(windowDays),
      ]);
      if (!isCurrent()) {
        return;
      }
      if (!summaryResponse.success || !summaryResponse.data ||
          !timeseriesResponse.success || !timeseriesResponse.data) {
        throw new Error('Usage metrics response is incomplete');
      }
      setLoadState({
        status: 'success',
        summary: summaryResponse.data,
        points: timeseriesResponse.data.points,
      });
    } catch {
      if (isCurrent()) {
        setLoadState((current) => silent && current.status === 'success' ? current : { status: 'error' });
      }
    }
  }, [beginRead, windowDays]);
  useEffect(() => { void load(); }, [retryAttempt, load]);
  useCenterRefresh(() => load(true), ["metrics","llm"]);

  const providerOptions = useMemo(
    () => uniqueStrings((summary?.providers || []).map((item) => item.provider)),
    [summary]
  );

  const modelOptions = useMemo(() => {
    const candidates = (summary?.models || []).filter((item) =>
      providerFilter === 'all' ? true : item.provider === providerFilter
    );
    return uniqueStrings(candidates.map((item) => item.model));
  }, [providerFilter, summary]);

  useEffect(() => {
    if (modelFilter !== 'all' && !modelOptions.includes(modelFilter)) {
      setModelFilter('all');
    }
  }, [modelFilter, modelOptions]);

  const filteredModels = useMemo(
    () =>
      (summary?.models || []).filter((item) => {
        if (providerFilter !== 'all' && item.provider !== providerFilter) return false;
        if (modelFilter !== 'all' && item.model !== modelFilter) return false;
        return true;
      }),
    [modelFilter, providerFilter, summary]
  );

  const filteredProviders = useMemo(
    () => (providerFilter === 'all' ? summary?.providers || [] : (summary?.providers || []).filter((item) => item.provider === providerFilter)),
    [providerFilter, summary]
  );

  const requestKinds = useMemo(() => summary?.request_kinds || [], [summary]);

  const chartData = useMemo(() => timeseries.map((point) => ({
    ...point, display_cost: summary?.daily_display_costs?.[point.day]?.[currency] ?? null,
  })), [timeseries, summary, currency]);
  const totals = summary?.totals;
  const hasUsage = Boolean(totals && totals.total_calls > 0);
  const successRate = computeSuccessRate(summary);
  const unknownLabel = t('settings.statistics.shared.unknown');

  const activeRows = useMemo(() => {
    if (activeTab === 'models') {
      return filteredModels;
    }
    if (activeTab === 'providers') {
      return filteredProviders;
    }
    return requestKinds;
  }, [activeTab, filteredModels, filteredProviders, requestKinds]);

  const windowPicker = (
    <div className="flex gap-3">
      {WINDOW_OPTIONS.map((days) => (
        <button key={days} type="button" aria-pressed={windowDays === days}
          className={tabClass} onClick={() => setWindowDays(days)}>
          {t(`settings.usage.windows.${days}`)}
        </button>
      ))}
    </div>
  );

  if (loadState.status === 'loading') {
    return (
      <div data-testid="llm-statistics-section" className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2 text-muted-foreground">
          <LoadingSpinner />
          <span className="text-sm">{t('settings.usage.loading')}</span>
        </div>
      </div>
    );
  }

  if (loadState.status === 'error') {
    return (
      <div data-testid="llm-statistics-section" className="space-y-4 border-l-2 border-destructive/50 px-4 py-2">
        <div role="alert" className="space-y-2">
          <p className="font-medium">{t('settings.usage.loadErrorTitle')}</p>
          <p className="text-sm text-muted-foreground">{t('settings.usage.loadErrorDesc')}</p>
        </div>
        <Button type="button" variant="outline" onClick={() => setRetryAttempt((attempt) => attempt + 1)}>
          {t('settings.usage.retry')}
        </Button>
      </div>
    );
  }

  if (!hasUsage || !totals || !summary) {
    return (
      <div data-testid="llm-statistics-section" className="space-y-6">
        {windowPicker}
        <div className="max-w-xl space-y-2 border-t border-border py-6">
          <div className="text-lg font-semibold text-foreground">{t('settings.usage.emptyTitle')}</div>
          <div className="text-sm leading-6 text-muted-foreground">{t('settings.usage.emptyDesc')}</div>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="llm-statistics-section" className="@container h-full min-h-0">
      <StatisticsPageFrame
        signalColumns="grid-cols-2 @min-[32rem]:grid-cols-3 @min-[54rem]:grid-cols-6"
        toolbar={(
          <>
            {windowPicker}
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              {t('settings.statistics.llm.displayCurrency')}
              <select className={selectClass} value={currency} onChange={({ target }) => {
                if (target.value === 'CNY' || target.value === 'USD') {
                  setPreferredCurrency(target.value);
                  localStorage.setItem(CURRENCY_PREFERENCE, target.value);
                }
              }}>
                <option value="CNY">{t('settings.statistics.llm.cny')}</option>
                <option value="USD">{t('settings.statistics.llm.usd')}</option>
              </select>
            </label>
          </>
        )}
        signalRibbon={(
          <>
            <UsageCostSummary summary={summary} currency={currency} locale={locale} />
            <SignalItem label={t('settings.usage.cards.totalTokens')} value={formatCompactNumber(totals.total_tokens)} />
            <SignalItem label={t('settings.usage.cards.cacheHitRate')} value={formatPercent(totals.cache_hit_rate || 0)} />
            <SignalItem label={t('settings.statistics.llm.successRate')} value={new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(successRate / 100)} />
            <SignalItem label={t('settings.usage.cards.avgLatency')} value={formatLatency(totals.avg_latency_ms, locale)} />
            <SignalItem label={t('settings.statistics.llm.firstToken')} value={formatLatency(totals.avg_ttft_ms, locale)} />
          </>
        )}
        mainCanvas={(
          <section className="space-y-3">
            {summary?.background_budget?.exceeded ? (
              <div
                role="status"
                data-testid="background-budget-paused-notice"
                className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs leading-5 text-muted-foreground"
              >
                {t('settings.usage.backgroundBudgetPaused', {
                  used: formatInteger(summary.background_budget.used_tokens),
                  budget: formatInteger(summary.background_budget.budget_tokens),
                })}
              </div>
            ) : null}
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-base font-semibold">{t('settings.statistics.llm.dailyTrend')}</h3>
              <div className="flex gap-2">
                <button type="button" className={tabClass} aria-pressed={trend === 'tokens'} onClick={() => setTrend('tokens')}>
                  {t('settings.usage.cards.totalTokens')}
                </button>
                <button type="button" className={tabClass} aria-pressed={trend === 'cost'} onClick={() => setTrend('cost')}>
                  {t('settings.statistics.llm.estimatedCost')} ({currency})
                </button>
              </div>
            </div>
            <div className="h-48 @min-[40rem]:h-56">
              {trend === 'cost' && chartData.every((point) => point.display_cost == null) ? (
                <p className="grid h-full place-items-center text-sm text-muted-foreground">{t('settings.statistics.llm.noCostTrend')}</p>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis dataKey="day" tickFormatter={(day: string) => day.slice(-5)} minTickGap={22} tickLine={false} axisLine={false} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }} />
                    <YAxis tickFormatter={trend === 'cost' ? (value: number) => formatUsageCost(value, currency, locale) : formatCompactNumber}
                      width={60} tickLine={false} axisLine={false} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }} />
                    <Tooltip formatter={(value) => trend === 'cost' ? formatUsageCost(Number(value), currency, locale) : formatInteger(Number(value))} />
                    {trend === 'tokens'
                      ? <Bar dataKey="total_tokens" name={t('settings.usage.cards.totalTokens')} fill="hsl(var(--muted-foreground))" fillOpacity={0.56} maxBarSize={32} isAnimationActive={false} />
                      : <Line dataKey="display_cost" name={t('settings.statistics.llm.estimatedCost')} stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />}
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>
        )}
        secondary={(
          <section className="min-w-0 space-y-3 border-t border-border pt-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="text-base font-semibold">{t('settings.statistics.llm.table.title')}</div>
              <div role="tablist" aria-label={t('settings.statistics.llm.table.title')} className="inline-flex flex-wrap gap-2">
                {TABLE_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === tab}
                    onClick={() => setActiveTab(tab)}
                    className={tabClass}
                  >
                    {t(`settings.statistics.llm.tabs.${tab}`)}
                  </button>
                ))}
              </div>
            </div>

            {activeTab !== 'requestKinds' && (
              <div className="flex flex-wrap gap-2">
                <select
                  aria-label={t('settings.usage.providerFilter')}
                  value={providerFilter}
                  onChange={(event) => setProviderFilter(event.target.value)}
                  className={selectClass}
                >
                  <option value="all">{t('settings.statistics.shared.allProviders')}</option>
                  {providerOptions.map((provider) => (
                    <option key={provider} value={provider}>{provider}</option>
                  ))}
                </select>
                {activeTab === 'models' && (
                  <select
                    aria-label={t('settings.usage.modelFilter')}
                    value={modelFilter}
                    onChange={(event) => setModelFilter(event.target.value)}
                    className={selectClass}
                  >
                    <option value="all">{t('settings.statistics.shared.allModels')}</option>
                    {modelOptions.map((model) => (
                      <option key={model} value={model}>{model}</option>
                    ))}
                  </select>
                )}
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-right text-sm tabular-nums">
                <thead>
                  <tr className="border-b border-[hsl(var(--settings-subnav-border)/0.56)] text-right">
                    {activeTab === 'requestKinds' ? (
                      <>
                        <TableHeaderCell className="min-w-32">{t('settings.statistics.llm.table.columns.scenario')}</TableHeaderCell>
                        <TableHeaderCell className="min-w-44 text-left">{t('settings.statistics.llm.table.columns.stage')}</TableHeaderCell>
                      </>
                    ) : (
                      <TableHeaderCell>{t(activeTab === 'models' ? 'settings.fields.model' : 'settings.fields.provider')}</TableHeaderCell>
                    )}
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.calls')}</TableHeaderCell>
                    <TableHeaderCell><span>{t('settings.statistics.llm.table.columns.cost')}</span> ({currency})</TableHeaderCell>
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.totalTokens')}</TableHeaderCell>
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.promptTokens')}</TableHeaderCell>
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.completionTokens')}</TableHeaderCell>
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.cacheHitRate')}</TableHeaderCell>
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.cacheReadTokens')}</TableHeaderCell>
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.avgLatency')}</TableHeaderCell>
                    <TableHeaderCell>{t('settings.statistics.llm.table.columns.avgTTFT')}</TableHeaderCell>
                  </tr>
                </thead>
                <tbody>
                  {activeRows.map((item, index) => {
                    const labels = activeTab === 'requestKinds' ? getUsageScenarioLabels(item.request_kind) : undefined;
                    return (
                      <tr key={buildBreakdownRowKey(activeTab, item, index)} className="border-b border-[hsl(var(--settings-subnav-border)/0.3)] last:border-b-0">
                        <TableCell>
                          {labels ? t(labels.scenario) : (activeTab === 'models' ? item.model : item.provider) || unknownLabel}
                        </TableCell>
                        {labels && (
                          <td className="px-3 py-2.5 text-left">{t(labels.stage)}</td>
                        )}
                        <TableCell>{formatInteger(item.calls)}</TableCell>
                        <TableCell>{formatUsageCost(item.display_costs?.[currency], currency, locale)}</TableCell>
                        <TableCell>{formatInteger(item.total_tokens)}</TableCell>
                        <TableCell>{formatInteger(item.prompt_tokens)}</TableCell>
                        <TableCell>{formatInteger(item.completion_tokens)}</TableCell>
                        <TableCell>{formatPercent(item.cache_hit_rate || 0)}</TableCell>
                        <TableCell>{formatInteger(item.cache_read_tokens)}</TableCell>
                        <TableCell>{formatLatency(item.avg_latency_ms, locale)}</TableCell>
                        <TableCell>{formatLatency(item.avg_ttft_ms, locale)}</TableCell>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}
      />
    </div>
  );
};

const SignalItem = ({ label, value }: { label: string; value: string }) => (
  <div className="min-w-0">
    <div className="text-xs text-muted-foreground">{label}</div>
    <div className="mt-1 text-xl font-medium tracking-tight text-foreground tabular-nums">{value}</div>
  </div>
);

const TableHeaderCell = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <th className={cn('first:text-left whitespace-nowrap border-y border-border bg-muted/35 px-3 py-2 text-xs font-medium text-muted-foreground', className)}>{children}</th>
);

const TableCell = ({ children }: { children: React.ReactNode }) => (
  <td className="whitespace-nowrap px-3 py-2.5 text-sm text-foreground first:whitespace-normal first:text-left">{children}</td>
);

export default LLMStatisticsSection;
