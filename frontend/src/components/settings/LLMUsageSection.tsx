import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { metricsApi, type LLMUsageSummary, type LLMUsageTimeseries } from '@/api/modules/metrics';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

const WINDOW_OPTIONS = [7, 30] as const;

const formatCompactNumber = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);

export const LLMUsageSection: React.FC = () => {
  const { t } = useTranslation('app');
  const [windowDays, setWindowDays] = useState<(typeof WINDOW_OPTIONS)[number]>(7);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<LLMUsageSummary | null>(null);
  const [timeseries, setTimeseries] = useState<LLMUsageTimeseries['points']>([]);

  useEffect(() => {
    void fetchUsage(windowDays);
  }, [windowDays]);

  const fetchUsage = async (days: number) => {
    setLoading(true);
    try {
      const [summaryResponse, timeseriesResponse] = await Promise.all([
        metricsApi.getLLMUsageSummary(days),
        metricsApi.getLLMUsageTimeseries(days),
      ]);
      setSummary(summaryResponse.data || null);
      setTimeseries(timeseriesResponse.data?.points || []);
    } catch (error: any) {
      toast.error(t('settings.usage.loadFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoading(false);
    }
  };

  const totals = summary?.totals;
  const hasUsage = Boolean(totals && totals.total_calls > 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">{t('settings.tabs.usage')}</h2>
          <p className="text-sm text-muted-foreground">{t('settings.usageDesc')}</p>
        </div>
        <div className="flex items-center gap-2">
          {WINDOW_OPTIONS.map((days) => (
            <Button
              key={days}
              type="button"
              size="sm"
              variant={windowDays === days ? 'default' : 'outline'}
              onClick={() => setWindowDays(days)}
            >
              {t(`settings.usage.windows.${days}`)}
            </Button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <div className="flex items-center gap-2">
            <LoadingSpinner />
            <span className="text-sm">{t('settings.usage.loading')}</span>
          </div>
        </div>
      ) : !hasUsage || !totals ? (
        <Card className="border-dashed">
          <CardHeader>
            <CardTitle>{t('settings.usage.emptyTitle')}</CardTitle>
            <CardDescription>{t('settings.usage.emptyDesc')}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>{t('settings.usage.cards.totalTokens')}</CardDescription>
                <CardTitle className="text-3xl">{formatCompactNumber(totals.total_tokens)}</CardTitle>
              </CardHeader>
              <CardContent className="flex gap-2 text-xs text-muted-foreground">
                <Badge variant="secondary">{t('settings.usage.cards.prompt')}: {formatCompactNumber(totals.prompt_tokens)}</Badge>
                <Badge variant="outline">{t('settings.usage.cards.completion')}: {formatCompactNumber(totals.completion_tokens)}</Badge>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>{t('settings.usage.cards.totalCalls')}</CardDescription>
                <CardTitle className="text-3xl">{formatCompactNumber(totals.total_calls)}</CardTitle>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">
                {t('settings.usage.cards.successRate', {
                  value: totals.total_calls > 0
                    ? Math.round((totals.successful_calls / totals.total_calls) * 100)
                    : 0,
                })}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>{t('settings.usage.cards.avgLatency')}</CardDescription>
                <CardTitle className="text-3xl">{Math.round(totals.avg_latency_ms)}ms</CardTitle>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">
                {t('settings.usage.cards.withUsage', { count: totals.calls_with_usage })}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>{t('settings.usage.cards.outputShare')}</CardDescription>
                <CardTitle className="text-3xl">
                  {totals.total_tokens > 0
                    ? `${Math.round((totals.completion_tokens / totals.total_tokens) * 100)}%`
                    : '0%'}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">
                {t('settings.usage.cards.failedCalls', { count: totals.failed_calls })}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
            <Card>
              <CardHeader>
                <CardTitle>{t('settings.usage.trendTitle')}</CardTitle>
                <CardDescription>{t('settings.usage.trendDesc')}</CardDescription>
              </CardHeader>
              <CardContent className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={timeseries}>
                    <defs>
                      <linearGradient id="usage-total" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#0f766e" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#0f766e" stopOpacity={0.03} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" />
                    <XAxis dataKey="day" tickLine={false} axisLine={false} />
                    <YAxis tickLine={false} axisLine={false} width={64} />
                    <Tooltip />
                    <Area
                      type="monotone"
                      dataKey="total_tokens"
                      stroke="#0f766e"
                      fill="url(#usage-total)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t('settings.usage.splitTitle')}</CardTitle>
                <CardDescription>{t('settings.usage.splitDesc')}</CardDescription>
              </CardHeader>
              <CardContent className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={timeseries}>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" />
                    <XAxis dataKey="day" tickLine={false} axisLine={false} />
                    <YAxis tickLine={false} axisLine={false} width={64} />
                    <Tooltip />
                    <Bar dataKey="prompt_tokens" stackId="usage" fill="#0f766e" radius={[6, 6, 0, 0]} />
                    <Bar dataKey="completion_tokens" stackId="usage" fill="#f59e0b" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>{t('settings.usage.providerTitle')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {summary?.providers.map((item) => (
                  <div key={item.provider} className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-medium">{item.provider}</p>
                      <p className="text-xs text-muted-foreground">{t('settings.usage.callsLabel', { count: item.calls })}</p>
                    </div>
                    <Badge variant="secondary">{formatCompactNumber(item.total_tokens)}</Badge>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t('settings.usage.modelTitle')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {summary?.models.map((item) => (
                  <div key={`${item.provider}-${item.model}`} className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{item.model}</p>
                      <p className="text-xs text-muted-foreground">{item.provider}</p>
                    </div>
                    <Badge variant="outline">{formatCompactNumber(item.total_tokens)}</Badge>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t('settings.usage.requestKindsTitle')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {summary?.request_kinds.map((item) => (
                  <div key={item.request_kind} className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{item.request_kind}</p>
                      <p className="text-xs text-muted-foreground">{t('settings.usage.callsLabel', { count: item.calls })}</p>
                    </div>
                    <Badge variant="outline">{formatCompactNumber(item.total_tokens)}</Badge>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
};

export default LLMUsageSection;
