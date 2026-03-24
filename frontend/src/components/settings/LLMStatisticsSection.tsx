import { useEffect, useMemo, useState, type FC } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { metricsApi, type LLMUsageSummary, type LLMUsageTimeseriesPoint } from '@/api/modules/metrics';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { StatisticsPageFrame } from './StatisticsPageFrame';

const WINDOW_OPTIONS = [7, 30] as const;
const TABLE_TABS = ['models', 'providers', 'requestKinds'] as const;

type TableTab = (typeof TABLE_TABS)[number];

const REQUEST_KIND_TRANSLATION_KEYS: Record<string, string> = {
  chat: 'settings.statistics.llm.requestKinds.chat',
  context_decider: 'settings.statistics.llm.requestKinds.contextDecider',
  'function_calling:tools': 'settings.statistics.llm.requestKinds.functionCallingTools',
  'function_calling:final_response': 'settings.statistics.llm.requestKinds.functionCallingFinalResponse',
  'skill_subagent:direct': 'settings.statistics.llm.requestKinds.skillSubagentDirect',
  'memory:l2_unified_extraction': 'settings.statistics.llm.requestKinds.memoryL2UnifiedExtraction',
  'memory:l2_entity_resolution': 'settings.statistics.llm.requestKinds.memoryL2EntityResolution',
  'memory:l2_contradiction_hint': 'settings.statistics.llm.requestKinds.memoryL2ContradictionHint',
  'memory:l2_conflict_arbitration': 'settings.statistics.llm.requestKinds.memoryL2ConflictArbitration',
  'memory:l2_entity_reconcile': 'settings.statistics.llm.requestKinds.memoryL2EntityReconcile',
  'memory:l3_temporal_summary': 'settings.statistics.llm.requestKinds.memoryL3TemporalSummary',
  'memory:l3_thematic_topic_summary': 'settings.statistics.llm.requestKinds.memoryL3ThematicTopicSummary',
};

const formatCompactNumber = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);

const uniqueStrings = (values: Array<string | undefined>) => [...new Set(values.filter((value): value is string => Boolean(value)))];

const formatInteger = (value?: number | null) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(Number(value || 0));

const formatLatency = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}ms` : null;

const formatPercent = (value: number) => `${Math.round(value)}%`;

const formatCurrency = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(value >= 10 ? 1 : 2)}` : null;

const computeSuccessRate = (summary: LLMUsageSummary | null) => {
  const totals = summary?.totals;
  if (!totals || totals.total_calls <= 0) return 0;
  return (totals.successful_calls / totals.total_calls) * 100;
};

const resolveRequestKindLabel = (requestKind: string | undefined, t: (key: string) => string, fallback: string) => {
  if (!requestKind) {
    return fallback;
  }
  const translationKey = REQUEST_KIND_TRANSLATION_KEYS[requestKind];
  return translationKey ? t(translationKey) : requestKind;
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
  const { t } = useTranslation('app');
  const [windowDays, setWindowDays] = useState<(typeof WINDOW_OPTIONS)[number]>(7);
  const [summary, setSummary] = useState<LLMUsageSummary | null>(null);
  const [timeseries, setTimeseries] = useState<LLMUsageTimeseriesPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [providerFilter, setProviderFilter] = useState('all');
  const [modelFilter, setModelFilter] = useState('all');
  const [activeTab, setActiveTab] = useState<TableTab>('models');

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const [summaryResponse, timeseriesResponse] = await Promise.all([
          metricsApi.getLLMUsageSummary(windowDays, 8),
          metricsApi.getLLMUsageTimeseries(windowDays),
        ]);
        if (cancelled) {
          return;
        }
        setSummary(summaryResponse.data || null);
        setTimeseries(timeseriesResponse.data?.points || []);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [windowDays]);

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

  const totals = summary?.totals;
  const hasUsage = Boolean(totals && totals.total_calls > 0);
  const successRate = computeSuccessRate(summary);
  const unavailableLabel = t('settings.statistics.shared.unavailable');
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

  if (loading) {
    return (
      <div data-testid="llm-statistics-section" className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2 text-muted-foreground">
          <LoadingSpinner />
          <span className="text-sm">{t('settings.usage.loading')}</span>
        </div>
      </div>
    );
  }

  if (!hasUsage || !totals) {
    return (
      <div data-testid="llm-statistics-section" className="rounded-[1.6rem] border border-dashed border-[hsl(var(--settings-subnav-border)/0.8)] bg-[hsl(var(--settings-shell-elevated)/0.28)] p-8">
        <div className="max-w-xl space-y-2">
          <div className="text-lg font-semibold text-foreground">{t('settings.usage.emptyTitle')}</div>
          <div className="text-sm leading-6 text-muted-foreground">{t('settings.usage.emptyDesc')}</div>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="llm-statistics-section" className="h-full min-h-0">
      <StatisticsPageFrame
        toolbar={(
          <>
            <div className="flex flex-wrap items-center gap-2">
              {WINDOW_OPTIONS.map((days) => (
                <Button
                  key={days}
                  type="button"
                  size="sm"
                  variant={windowDays === days ? 'default' : 'outline'}
                  onClick={() => setWindowDays(days)}
                  aria-label={t(`settings.usage.windows.${days}`)}
                  className={windowDays === days ? 'rounded-full' : 'rounded-full bg-transparent'}
                >
                  {t(`settings.usage.windows.${days}`)}
                </Button>
              ))}
              <select
                aria-label="provider-filter"
                value={providerFilter}
                onChange={(event) => setProviderFilter(event.target.value)}
                className="h-9 rounded-full border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent px-3 text-sm text-foreground outline-none"
              >
                <option value="all">{t('settings.statistics.shared.allProviders')}</option>
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>{provider}</option>
                ))}
              </select>
              <select
                aria-label="model-filter"
                value={modelFilter}
                onChange={(event) => setModelFilter(event.target.value)}
                className="h-9 rounded-full border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent px-3 text-sm text-foreground outline-none"
              >
                <option value="all">{t('settings.statistics.shared.allModels')}</option>
                {modelOptions.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
            <div className="text-sm text-muted-foreground">
              {t('settings.statistics.shared.updatedForDays', { days: windowDays })}
            </div>
          </>
        )}
        signalRibbon={(
          <>
            <SignalItem label={t('settings.usage.cards.totalTokens')} value={formatCompactNumber(totals.total_tokens)} />
            <SignalItem label={t('settings.statistics.shared.totalCost')} value={formatCurrency(totals.total_cost_usd) || unavailableLabel} />
            <SignalItem label={t('settings.usage.cards.avgLatency')} value={formatLatency(totals.avg_latency_ms) || unavailableLabel} />
            <SignalItem label={t('settings.statistics.shared.avgTTFT')} value={formatLatency(totals.avg_ttft_ms) || unavailableLabel} />
            <SignalItem label={t('settings.usage.cards.successRate', { value: Math.round(successRate) })} value={formatPercent(successRate)} />
          </>
        )}
        mainCanvas={(
          <div className="space-y-5">
            <div className="flex items-center justify-between border-b border-[hsl(var(--settings-subnav-border)/0.45)] pb-3">
              <div className="text-sm font-medium text-foreground">{t('settings.usage.trendTitle')}</div>
              <div className="text-xs text-muted-foreground">{t('settings.usage.trendDesc')}</div>
            </div>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={timeseries}>
                  <defs>
                    <linearGradient id="llm-statistics-tokens" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.26} />
                      <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <YAxis yAxisId="tokens" tickLine={false} axisLine={false} width={64} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <YAxis yAxisId="cost" orientation="right" tickLine={false} axisLine={false} width={48} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <Tooltip />
                  <Area yAxisId="tokens" type="monotone" dataKey="total_tokens" stroke="hsl(var(--primary))" fill="url(#llm-statistics-tokens)" strokeWidth={2} />
                  <Line yAxisId="cost" type="monotone" dataKey="cost_usd" stroke="hsl(var(--accent))" strokeWidth={2} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
        secondary={(
          <section className="space-y-4 border-t border-[hsl(var(--settings-subnav-border)/0.42)] pt-5">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="text-sm font-medium text-foreground">{t('settings.statistics.llm.table.title')}</div>
              <div role="tablist" aria-label={t('settings.statistics.llm.table.title')} className="inline-flex rounded-full border border-[hsl(var(--settings-subnav-border)/0.68)] p-1">
                {TABLE_TABS.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === tab}
                    onClick={() => setActiveTab(tab)}
                    className={
                      activeTab === tab
                        ? 'rounded-full bg-[hsl(var(--settings-shell-elevated)/0.82)] px-3 py-1.5 text-sm font-medium text-foreground'
                        : 'rounded-full px-3 py-1.5 text-sm text-muted-foreground transition hover:text-foreground'
                    }
                  >
                    {t(`settings.statistics.llm.tabs.${tab}`)}
                  </button>
                ))}
              </div>
            </div>

            <div className="overflow-hidden rounded-[1.3rem] border border-[hsl(var(--settings-subnav-border)/0.56)] bg-[hsl(var(--settings-shell-elevated)/0.22)]">
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-[hsl(var(--settings-subnav-border)/0.56)] text-left">
                      <TableHeaderCell>{t('settings.statistics.llm.table.columns.key')}</TableHeaderCell>
                      <TableHeaderCell>{t('settings.statistics.llm.table.columns.calls')}</TableHeaderCell>
                      <TableHeaderCell>{t('settings.statistics.llm.table.columns.totalTokens')}</TableHeaderCell>
                      <TableHeaderCell>{t('settings.statistics.llm.table.columns.promptTokens')}</TableHeaderCell>
                      <TableHeaderCell>{t('settings.statistics.llm.table.columns.completionTokens')}</TableHeaderCell>
                      <TableHeaderCell>{t('settings.statistics.llm.table.columns.cost')}</TableHeaderCell>
                    </tr>
                  </thead>
                  <tbody>
                    {activeRows.map((item, index) => (
                      <tr key={buildBreakdownRowKey(activeTab, item, index)} className="border-b border-[hsl(var(--settings-subnav-border)/0.3)] last:border-b-0">
                        <TableCell>
                          {activeTab === 'models'
                            ? (item.model || unknownLabel)
                            : activeTab === 'providers'
                              ? (item.provider || unknownLabel)
                              : resolveRequestKindLabel(item.request_kind, t, unknownLabel)}
                        </TableCell>
                        <TableCell>{formatInteger(item.calls)}</TableCell>
                        <TableCell>{formatInteger(item.total_tokens)}</TableCell>
                        <TableCell>{formatInteger(item.prompt_tokens)}</TableCell>
                        <TableCell>{formatInteger(item.completion_tokens)}</TableCell>
                        <TableCell>{formatCurrency(item.cost_usd) || unavailableLabel}</TableCell>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}
      />
    </div>
  );
};

const SignalItem = ({ label, value }: { label: string; value: string }) => (
  <div className="border-b border-[hsl(var(--settings-subnav-border)/0.42)] pb-3 md:border-b-0 md:pb-0">
    <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
    <div className="mt-2 text-2xl font-semibold text-foreground">{value}</div>
  </div>
);

const TableHeaderCell = ({ children }: { children: React.ReactNode }) => (
  <th className="px-4 py-3 text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">{children}</th>
);

const TableCell = ({ children }: { children: React.ReactNode }) => (
  <td className="px-4 py-3 text-sm text-foreground">{children}</td>
);

export default LLMStatisticsSection;
