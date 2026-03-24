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
import { metricsApi, type LLMUsageBreakdownItem, type LLMUsageSummary, type LLMUsageTimeseriesPoint } from '@/api/modules/metrics';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { StatisticsPageFrame } from './StatisticsPageFrame';

const WINDOW_OPTIONS = [7, 30] as const;

const formatCompactNumber = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);

const formatLatency = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}ms` : 'N/A';

const formatPercent = (value: number) => `${Math.round(value)}%`;

const formatCurrency = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(value >= 10 ? 1 : 2)}` : 'N/A';

const computeSuccessRate = (summary: LLMUsageSummary | null) => {
  const totals = summary?.totals;
  if (!totals || totals.total_calls <= 0) return 0;
  return (totals.successful_calls / totals.total_calls) * 100;
};

const pickTopItem = (items: LLMUsageBreakdownItem[], key: 'total_tokens' | 'cost_usd' | 'failed_calls') =>
  [...items]
    .sort((left, right) => Number(right[key] || 0) - Number(left[key] || 0))
    .find((item) => Number(item[key] || 0) > 0) || null;

export const LLMStatisticsSection: FC = () => (
  <LLMStatisticsSectionInner />
);

const LLMStatisticsSectionInner: FC = () => {
  const { t } = useTranslation('app');
  const [windowDays, setWindowDays] = useState<(typeof WINDOW_OPTIONS)[number]>(7);
  const [summary, setSummary] = useState<LLMUsageSummary | null>(null);
  const [timeseries, setTimeseries] = useState<LLMUsageTimeseriesPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [providerFilter, setProviderFilter] = useState('all');
  const [modelFilter, setModelFilter] = useState('all');

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
    () => (summary?.providers || []).map((item) => item.provider).filter((value): value is string => Boolean(value)),
    [summary]
  );

  const modelOptions = useMemo(() => {
    const candidates = (summary?.models || []).filter((item) =>
      providerFilter === 'all' ? true : item.provider === providerFilter
    );
    return candidates.map((item) => item.model).filter((value): value is string => Boolean(value));
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

  const filteredRequestKinds = useMemo(() => summary?.request_kinds || [], [summary]);

  const totals = summary?.totals;
  const hasUsage = Boolean(totals && totals.total_calls > 0);
  const successRate = computeSuccessRate(summary);
  const topModel = pickTopItem(filteredModels, 'total_tokens');
  const topFailureKind = pickTopItem(filteredRequestKinds, 'failed_calls');
  const topProviderCost = pickTopItem(filteredProviders, 'cost_usd');

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
                  aria-label={`${days}D`}
                  className={windowDays === days ? 'rounded-full' : 'rounded-full bg-transparent'}
                >
                  {days}D
                </Button>
              ))}
              <select
                aria-label="provider-filter"
                value={providerFilter}
                onChange={(event) => setProviderFilter(event.target.value)}
                className="h-9 rounded-full border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent px-3 text-sm text-foreground outline-none"
              >
                <option value="all">All providers</option>
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
                <option value="all">All models</option>
                {modelOptions.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
            <div className="text-sm text-muted-foreground">Updated for the last {windowDays} days</div>
          </>
        )}
        signalRibbon={(
          <>
            <SignalItem label="Total Tokens" value={formatCompactNumber(totals.total_tokens)} />
            <SignalItem label="Total Cost" value={formatCurrency(totals.total_cost_usd)} />
            <SignalItem label="Avg Latency" value={formatLatency(totals.avg_latency_ms)} />
            <SignalItem label="Avg TTFT" value={formatLatency(totals.avg_ttft_ms)} />
            <SignalItem label="Success Rate" value={formatPercent(successRate)} />
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
          <div className="space-y-6">
            <AnalysisSection
              title={t('settings.usage.splitTitle')}
              items={[
                { label: t('settings.usage.cards.prompt'), value: formatCompactNumber(totals.prompt_tokens) },
                { label: t('settings.usage.cards.completion'), value: formatCompactNumber(totals.completion_tokens) },
              ]}
            />
            <div className="grid gap-6 md:grid-cols-3">
              <AnalysisSection
                title={t('settings.usage.modelTitle')}
                items={filteredModels.slice(0, 3).map((item) => ({
                  label: item.model || 'Unknown',
                  value: formatCompactNumber(item.total_tokens),
                  meta: item.provider,
                }))}
              />
              <AnalysisSection
                title={t('settings.usage.providerTitle')}
                items={filteredProviders.slice(0, 3).map((item) => ({
                  label: item.provider || 'Unknown',
                  value: formatCompactNumber(item.total_tokens),
                }))}
              />
              <AnalysisSection
                title={t('settings.usage.requestKindsTitle')}
                items={filteredRequestKinds.slice(0, 3).map((item) => ({
                  label: item.request_kind || 'Unknown',
                  value: formatCompactNumber(item.total_tokens),
                  meta: `${item.calls} calls`,
                }))}
              />
            </div>
          </div>
        )}
        summaryRail={(
          <>
            <SummaryItem label="Most active model" value={topModel?.model || 'Unavailable'} detail={topModel?.provider || undefined} />
            <SummaryItem label="Highest failure request kind" value={topFailureKind?.request_kind || 'Unavailable'} detail={typeof topFailureKind?.failed_calls === 'number' ? `${topFailureKind.failed_calls} failed calls` : 'No failure data'} />
            <SummaryItem label="Highest cost provider" value={topProviderCost?.provider || 'Unavailable'} detail={formatCurrency(topProviderCost?.cost_usd)} />
            <div className="rounded-[1.25rem] border border-[hsl(var(--settings-subnav-border)/0.48)] bg-[hsl(var(--settings-shell-elevated)/0.24)] p-4 text-sm leading-6 text-muted-foreground">
              {successRate >= 95
                ? 'Usage quality looks stable, with failures contained and latency in a healthy range.'
                : 'Usage is active, but recent failures or latency spikes deserve a closer look.'}
            </div>
          </>
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

const AnalysisSection = ({
  title,
  items,
}: {
  title: string;
  items: Array<{ label: string; value: string; meta?: string }>;
}) => (
  <section className="space-y-3 border-t border-[hsl(var(--settings-subnav-border)/0.42)] pt-4">
    <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{title}</div>
    <div className="space-y-3">
      {items.map((item) => (
        <div key={`${title}-${item.label}`} className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground">{item.label}</div>
            {item.meta ? <div className="text-xs text-muted-foreground">{item.meta}</div> : null}
          </div>
          <div className="text-sm text-foreground">{item.value}</div>
        </div>
      ))}
    </div>
  </section>
);

const SummaryItem = ({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) => (
  <div className="border-b border-[hsl(var(--settings-subnav-border)/0.38)] pb-4">
    <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
    <div className="mt-2 text-lg font-semibold text-foreground">{value}</div>
    {detail ? <div className="mt-1 text-sm text-muted-foreground">{detail}</div> : null}
  </div>
);

export default LLMStatisticsSection;
