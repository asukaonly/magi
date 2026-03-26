/**
 * L3Tab - L3 Reflection/Summaries tab component
 */

import React, { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';
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

const summaryStreamClass = 'max-h-[34rem] divide-y divide-[hsl(var(--memory-divider)/0.72)] overflow-y-auto';
const summaryArticleClass = 'py-4 first:pt-0 last:pb-0';

export const L3Tab: React.FC<L3TabProps> = ({ stats, summaries }) => {
  const { t } = useTranslation('app');
  const availableTypes = useMemo(
    () => SUMMARY_TYPES.filter((summaryType) => summaries.some((summary) => summary.summary_type === summaryType)),
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

  const countLabel = summaries.length === stats.summary_count
    ? String(summaries.length)
    : `${summaries.length}/${stats.summary_count}`;
  const activeTypeCount = summariesByType[activeType].length;

  return (
    <section className="border-t border-[hsl(var(--memory-divider)/0.72)] pt-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-[hsl(var(--memory-title))]">
          <FileText className="h-5 w-5" />
          {t('memory.l3.summaries')}
        </h2>
        <span className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.72)] px-2.5 py-1 text-xs text-[hsl(var(--memory-body))]">
          {countLabel}
        </span>
      </div>

      {summaries.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">{t('memory.l3.noSummaries')}</div>
      ) : (
        <Tabs value={activeType} onValueChange={(value) => setActiveType(value as SummaryType)} className="space-y-4">
          <div className="overflow-x-auto pb-1">
            <TabsList className="inline-flex h-auto min-w-full justify-start gap-1 rounded-xl border border-[hsl(var(--memory-border)/0.6)] bg-[hsl(var(--memory-panel-elevated)/0.72)] p-1.5">
              {SUMMARY_TYPES.map((summaryType) => (
                <TabsTrigger
                  key={summaryType}
                  value={summaryType}
                  aria-label={t(`memory.pages.reflection.types.${summaryType}`)}
                  onClick={() => setActiveType(summaryType)}
                  className="rounded-lg border border-transparent px-3.5 py-2 text-sm font-medium text-[hsl(var(--memory-muted))] transition-all duration-200 hover:text-[hsl(var(--memory-title))] data-[state=active]:border-[hsl(var(--memory-accent)/0.42)] data-[state=active]:bg-[hsl(var(--memory-accent))] data-[state=active]:text-white data-[state=active]:shadow-[0_10px_24px_-18px_hsl(var(--memory-shadow)/0.45)]"
                >
                  <span>{t(`memory.pages.reflection.types.${summaryType}`)}</span>
                  <span
                    aria-hidden="true"
                    className="ml-2 rounded-full bg-black/8 px-1.5 py-0.5 text-[11px] leading-none text-current data-[state=active]:bg-white/18"
                  >
                    {summariesByType[summaryType].length}
                  </span>
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-sm border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.54)] px-3 py-2 text-sm">
            <span className="font-medium text-[hsl(var(--memory-title))]">
              {t(`memory.pages.reflection.types.${activeType}`)}
            </span>
            <span className="text-[hsl(var(--memory-body))]">
              {activeTypeCount}
            </span>
          </div>

          <TabsContent value="temporal" className="mt-0">
            <div key="temporal" className={summaryStreamClass}>
              {summariesByType.temporal.length === 0 ? (
                <EmptyTypeState />
              ) : (
                summariesByType.temporal.map((summary) => <TemporalSummaryArticle key={summary.summary_id} summary={summary} />)
              )}
            </div>
          </TabsContent>

          <TabsContent value="thematic" className="mt-0">
            <div key="thematic" className={summaryStreamClass}>
              {summariesByType.thematic.length === 0 ? (
                <EmptyTypeState />
              ) : (
                summariesByType.thematic.map((summary) => <ThematicSummaryArticle key={summary.summary_id} summary={summary} />)
              )}
            </div>
          </TabsContent>

          <TabsContent value="insight" className="mt-0 space-y-3">
            <Tabs value={activeInsightCategory} onValueChange={setActiveInsightCategory} className="space-y-3">
              <div className="overflow-x-auto pb-1">
                <TabsList className="inline-flex h-auto min-w-full justify-start gap-1 rounded-sm border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.74)] p-1">
                  <TabsTrigger
                    value="all"
                    onClick={() => setActiveInsightCategory('all')}
                    className="rounded-sm px-3 py-1.5 text-sm text-[hsl(var(--memory-body))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))]"
                  >
                    {t('memory.filters.all')}
                  </TabsTrigger>
                  {insightCategories.map((category) => (
                    <TabsTrigger
                      key={category}
                      value={category}
                      onClick={() => setActiveInsightCategory(category)}
                      className="rounded-sm px-3 py-1.5 text-sm text-[hsl(var(--memory-body))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))]"
                    >
                      {formatCategoryLabel(category, t)}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </div>

              <TabsContent value={activeInsightCategory} className="mt-0">
                <div key={activeInsightCategory} className={summaryStreamClass}>
                  {visibleInsightSummaries.length === 0 ? (
                    <EmptyTypeState />
                  ) : (
                    visibleInsightSummaries.map((summary) => (
                      <InsightSummaryArticle key={summary.summary_id} summary={summary} />
                    ))
                  )}
                </div>
              </TabsContent>
            </Tabs>
          </TabsContent>
        </Tabs>
      )}
    </section>
  );
};

const EmptyTypeState: React.FC = () => {
  const { t } = useTranslation('app');
  return <div className="py-8 text-center text-sm text-muted-foreground">{t('memory.l3.noSummaries')}</div>;
};

const SummaryShell: React.FC<{ summary: L3Summary; children: ReactNode }> = ({ summary, children }) => {
  const { t } = useTranslation('app');

  return (
    <article className={summaryArticleClass}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{t(`memory.pages.reflection.types.${summary.summary_type}`)}</Badge>
          <Badge variant="outline">{formatCategoryLabel(summary.summary_category, t)}</Badge>
        </div>
        <span className="text-xs text-muted-foreground">{formatTimestamp(summary.created_at)}</span>
      </div>
      {children}
    </article>
  );
};

const TemporalSummaryArticle: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');

  return (
    <SummaryShell summary={summary}>
      <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-title))]">{summary.content}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <MetaBlock
          label={t('memory.pages.reflection.cards.window')}
          value={`${formatTimestamp(summary.period_start)} - ${formatTimestamp(summary.period_end)}`}
        />
        <MetaBlock label={t('memory.pages.reflection.cards.sources')} value={String(summary.source_event_count)} />
      </div>
      <PatternDetails summary={summary} />
    </SummaryShell>
  );
};

const ThematicSummaryArticle: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');
  const entityLabels = (summary.key_entities || [])
    .map((entity) => entity.entity_id || entity.entity_type)
    .filter((value): value is string => Boolean(value));

  return (
    <SummaryShell summary={summary}>
      <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-title))]">{summary.content}</p>
      <TopicStrip
        labels={[
          ...summary.key_topics,
          ...entityLabels,
        ]}
      />
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <MetaBlock label={t('memory.pages.reflection.cards.sources')} value={String(summary.source_event_count)} />
        <MetaBlock label={t('memory.pages.reflection.cards.entities')} value={String(entityLabels.length)} />
      </div>
    </SummaryShell>
  );
};

const InsightSummaryArticle: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');
  const sentimentTone =
    summary.sentiment_summary && typeof summary.sentiment_summary.tone === 'string'
      ? summary.sentiment_summary.tone
      : null;

  const detailLabels = [
    ...summary.key_topics,
    sentimentTone ? `${t('memory.pages.reflection.cards.sentiment')}: ${sentimentTone}` : null,
    typeof summary.importance_aggregate === 'number'
      ? `${t('memory.pages.reflection.cards.importance')}: ${summary.importance_aggregate.toFixed(2)}`
      : null,
  ].filter((value): value is string => Boolean(value));

  return (
    <SummaryShell summary={summary}>
      <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-title))]">{summary.content}</p>
      <TopicStrip labels={detailLabels} />
      <PatternDetails summary={summary} />
    </SummaryShell>
  );
};

const TopicStrip: React.FC<{ labels: string[] }> = ({ labels }) => {
  const visibleLabels = labels.filter(Boolean);
  if (visibleLabels.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {visibleLabels.map((label) => (
        <Badge key={label} variant="secondary" className="text-xs font-normal">
          {label}
        </Badge>
      ))}
    </div>
  );
};

const MetaBlock: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-sm border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.58)] px-3 py-2">
    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--memory-muted))]">{label}</div>
    <div className="mt-1 text-sm text-[hsl(var(--memory-title))]">{value}</div>
  </div>
);

const PatternDetails: React.FC<{ summary: L3Summary }> = ({ summary }) => {
  const { t } = useTranslation('app');
  const changes = summary.change_and_pattern?.changes || [];
  const patterns = summary.change_and_pattern?.patterns || [];

  if (changes.length === 0 && patterns.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      {changes.length > 0 ? (
        <DetailList label={t('memory.pages.reflection.cards.changes')} items={changes} />
      ) : null}
      {patterns.length > 0 ? (
        <DetailList label={t('memory.pages.reflection.cards.patterns')} items={patterns} />
      ) : null}
    </div>
  );
};

const DetailList: React.FC<{ label: string; items: string[] }> = ({ label, items }) => (
  <div className="rounded-sm border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.58)] px-3 py-3">
    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--memory-muted))]">{label}</div>
    <ul className="mt-2 space-y-1 text-sm leading-6 text-[hsl(var(--memory-title))]">
      {items.slice(0, 3).map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  </div>
);

const formatCategoryLabel = (
  category: string,
  t: (key: string, options?: Record<string, unknown>) => string
) => t(`memory.pages.reflection.categories.${category}`, { defaultValue: category });

export default L3Tab;
