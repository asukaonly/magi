/**
 * L3Tab - L3 Reflection/Summaries tab component
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, FileText, GitBranch, Lightbulb, Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { L3Summary, MemoryStatistics } from '@/api/modules/memory';
import { formatTimestamp } from '@/hooks/useMemory';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

interface L3TabProps {
  stats: MemoryStatistics['l3'];
  summaries: L3Summary[];
}

const SUMMARY_TYPES = ['temporal', 'thematic', 'insight'] as const;
type SummaryType = (typeof SUMMARY_TYPES)[number];

export const L3Tab: React.FC<L3TabProps> = ({ stats, summaries }) => {
  const { t } = useTranslation('app');
  const availableTypes = useMemo(
    () =>
      SUMMARY_TYPES.filter((summaryType) =>
        summaries.some((summary) => summary.summary_type === summaryType)
      ),
    [summaries]
  );
  const [activeType, setActiveType] = useState<SummaryType>(availableTypes[0] ?? 'temporal');
  const [activeInsightCategory, setActiveInsightCategory] = useState<string>('all');

  useEffect(() => {
    if (!availableTypes.includes(activeType)) {
      setActiveType(availableTypes[0] ?? 'temporal');
    }
  }, [activeType, availableTypes]);

  const summariesByType = useMemo(
    () => ({
      temporal: summaries.filter((summary) => summary.summary_type === 'temporal'),
      thematic: summaries.filter((summary) => summary.summary_type === 'thematic'),
      insight: summaries.filter((summary) => summary.summary_type === 'insight'),
    }),
    [summaries]
  );

  const insightCategories = useMemo(
    () =>
      Array.from(
        summariesByType.insight.reduce((set, summary) => {
          if (summary.summary_category) {
            set.add(summary.summary_category);
          }
          return set;
        }, new Set<string>())
      ).sort(),
    [summariesByType.insight]
  );

  useEffect(() => {
    if (activeInsightCategory !== 'all' && !insightCategories.includes(activeInsightCategory)) {
      setActiveInsightCategory('all');
    }
  }, [activeInsightCategory, insightCategories]);

  const visibleInsightSummaries = useMemo(
    () =>
      activeInsightCategory === 'all'
        ? summariesByType.insight
        : summariesByType.insight.filter((summary) => summary.summary_category === activeInsightCategory),
    [activeInsightCategory, summariesByType.insight]
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4">
          <div className="text-2xl font-bold">{stats.summary_count}</div>
          <div className="text-sm text-muted-foreground">{t('memory.l3.summaryCount')}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {t('memory.l3.summaries')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {summaries.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground">{t('memory.l3.noSummaries')}</div>
          ) : (
            <Tabs value={activeType} onValueChange={(value) => setActiveType(value as SummaryType)} className="space-y-4">
              <div className="overflow-x-auto pb-1">
                <TabsList className="inline-flex h-auto min-w-full justify-start gap-2 rounded-[1.25rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.96)] p-2 shadow-[0_10px_24px_-24px_hsl(var(--memory-shadow)/0.28)]">
                  {SUMMARY_TYPES.map((summaryType) => (
                    <TabsTrigger
                      key={summaryType}
                      value={summaryType}
                      className="rounded-[0.95rem] border border-transparent px-4 py-2.5 text-sm text-[hsl(var(--memory-body))] data-[state=active]:border-[hsl(var(--memory-border))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))] data-[state=active]:shadow-[0_8px_16px_-18px_hsl(var(--memory-shadow)/0.35)]"
                    >
                      {t(`memory.pages.reflection.types.${summaryType}`)}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </div>

              <TabsContent value="temporal">
                <div className="space-y-4 max-h-[32rem] overflow-y-auto">
                  {summariesByType.temporal.length === 0 ? (
                    <EmptyTypeState label={t('memory.pages.reflection.types.temporal')} />
                  ) : (
                    summariesByType.temporal.map((summary) => <TemporalSummaryCard key={summary.summary_id} summary={summary} />)
                  )}
                </div>
              </TabsContent>

              <TabsContent value="thematic">
                <div className="space-y-4 max-h-[32rem] overflow-y-auto">
                  {summariesByType.thematic.length === 0 ? (
                    <EmptyTypeState label={t('memory.pages.reflection.types.thematic')} />
                  ) : (
                    summariesByType.thematic.map((summary) => <ThematicSummaryCard key={summary.summary_id} summary={summary} />)
                  )}
                </div>
              </TabsContent>

              <TabsContent value="insight" className="space-y-4">
                <Tabs value={activeInsightCategory} onValueChange={setActiveInsightCategory} className="space-y-4">
                  <div className="overflow-x-auto pb-1">
                    <TabsList className="inline-flex h-auto min-w-full justify-start gap-2 rounded-[1.15rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-subtle)/0.94)] p-2">
                      <TabsTrigger
                        value="all"
                        className="rounded-full border border-transparent px-4 py-2 text-sm text-[hsl(var(--memory-body))] data-[state=active]:border-[hsl(var(--memory-border))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))]"
                      >
                        {t('memory.filters.all')}
                      </TabsTrigger>
                      {insightCategories.map((category) => (
                        <TabsTrigger
                          key={category}
                          value={category}
                          className="rounded-full border border-transparent px-4 py-2 text-sm text-[hsl(var(--memory-body))] data-[state=active]:border-[hsl(var(--memory-border))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))]"
                        >
                          {formatCategoryLabel(category, t)}
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </div>

                  <TabsContent value={activeInsightCategory} className="mt-0">
                    <div className="space-y-4 max-h-[32rem] overflow-y-auto">
                      {visibleInsightSummaries.length === 0 ? (
                        <EmptyTypeState label={t('memory.pages.reflection.types.insight')} />
                      ) : (
                        visibleInsightSummaries.map((summary) => (
                          <InsightSummaryCard key={summary.summary_id} summary={summary} />
                        ))
                      )}
                    </div>
                  </TabsContent>
                </Tabs>
              </TabsContent>
            </Tabs>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

const cardClass =
  'rounded-[1.35rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.96)] p-4 shadow-[0_12px_24px_-24px_hsl(var(--memory-shadow)/0.28)]';

const EmptyTypeState: React.FC<{ label: string }> = ({ label }) => (
  <div className="rounded-[1.25rem] border border-dashed border-[hsl(var(--memory-empty-border))] bg-[hsl(var(--memory-empty-bg)/0.82)] p-5 text-sm leading-6 text-[hsl(var(--memory-body))]">
    {label}
  </div>
);

const TemporalSummaryCard: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');
  return (
    <div className={cardClass}>
      <SummaryHeader icon={<Activity className="h-4 w-4" />} summary={summary} />
      <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-title))]">{summary.content}</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <MetaRow
          label={t('memory.pages.reflection.cards.window')}
          value={`${formatTimestamp(summary.period_start)} - ${formatTimestamp(summary.period_end)}`}
        />
        <MetaRow label={t('memory.pages.reflection.cards.sources')} value={String(summary.source_event_count)} />
      </div>
      <PatternStrip summary={summary} />
    </div>
  );
};

const ThematicSummaryCard: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');
  const entityLabels = (summary.key_entities || [])
    .map((entity) => entity.entity_id || entity.entity_type)
    .filter((value): value is string => Boolean(value));
  return (
    <div className={cardClass}>
      <SummaryHeader icon={<GitBranch className="h-4 w-4" />} summary={summary} />
      <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-title))]">{summary.content}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {summary.key_topics.map((topic) => (
          <Badge key={topic} variant="secondary" className="text-xs">
            {topic}
          </Badge>
        ))}
        {entityLabels.map((entity) => (
          <Badge key={entity} variant="outline" className="text-xs">
            {entity}
          </Badge>
        ))}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <MetaRow label={t('memory.pages.reflection.cards.sources')} value={String(summary.source_event_count)} />
        <MetaRow label={t('memory.pages.reflection.cards.entities')} value={String(entityLabels.length)} />
      </div>
    </div>
  );
};

const InsightSummaryCard: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');
  const sentimentTone =
    summary.sentiment_summary && typeof summary.sentiment_summary.tone === 'string'
      ? summary.sentiment_summary.tone
      : null;
  return (
    <div className={cardClass}>
      <SummaryHeader icon={<Lightbulb className="h-4 w-4" />} summary={summary} />
      <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-title))]">{summary.content}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {summary.key_topics.map((topic) => (
          <Badge key={topic} variant="secondary" className="text-xs">
            {topic}
          </Badge>
        ))}
        {sentimentTone ? (
          <Badge variant="outline" className="text-xs">
            {t('memory.pages.reflection.cards.sentiment')}: {sentimentTone}
          </Badge>
        ) : null}
        {typeof summary.importance_aggregate === 'number' ? (
          <Badge variant="outline" className="text-xs">
            {t('memory.pages.reflection.cards.importance')}: {summary.importance_aggregate.toFixed(2)}
          </Badge>
        ) : null}
      </div>
      <PatternStrip summary={summary} />
      {summary.generated_by_model ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          <Sparkles className="h-3.5 w-3.5" />
          <span>
            {t('memory.pages.reflection.cards.generatedBy')}: {summary.generated_by_model}
          </span>
        </div>
      ) : null}
    </div>
  );
};

const SummaryHeader: React.FC<{ icon: React.ReactNode; summary: L3Summary }> = ({ icon, summary }) => (
  <SummaryHeaderInner icon={icon} summary={summary} />
);

const SummaryHeaderInner: React.FC<{ icon: React.ReactNode; summary: L3Summary }> = ({ icon, summary }) => {
  const { t } = useTranslation('app');
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-[hsl(var(--memory-body))]">
          {icon}
          <Badge>{t(`memory.pages.reflection.types.${summary.summary_type}`)}</Badge>
          <Badge variant="outline">
            {formatCategoryLabel(summary.summary_category, t)}
          </Badge>
        </div>
      </div>
      <span className="text-xs text-muted-foreground">{formatTimestamp(summary.created_at)}</span>
    </div>
  );
};

const MetaRow: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-[1rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel)/0.85)] px-3 py-2">
    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--memory-muted))]">{label}</div>
    <div className="mt-1 text-sm font-medium text-[hsl(var(--memory-title))]">{value}</div>
  </div>
);

const PatternStrip: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');
  const changes = summary.change_and_pattern?.changes || [];
  const patterns = summary.change_and_pattern?.patterns || [];
  if (changes.length === 0 && patterns.length === 0) {
    return null;
  }
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      {changes.length > 0 ? (
        <div className="rounded-[1rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel)/0.85)] px-3 py-3">
          <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--memory-muted))]">
            {t('memory.pages.reflection.cards.changes')}
          </div>
          <ul className="mt-2 space-y-1 text-sm text-[hsl(var(--memory-title))]">
            {changes.slice(0, 3).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {patterns.length > 0 ? (
        <div className="rounded-[1rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel)/0.85)] px-3 py-3">
          <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--memory-muted))]">
            {t('memory.pages.reflection.cards.patterns')}
          </div>
          <ul className="mt-2 space-y-1 text-sm text-[hsl(var(--memory-title))]">
            {patterns.slice(0, 3).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
};

const formatCategoryLabel = (
  category: string,
  t: (key: string, options?: Record<string, unknown>) => string
) => t(`memory.pages.reflection.categories.${category}`, { defaultValue: category });

export default L3Tab;
