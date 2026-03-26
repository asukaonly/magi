import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L3Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';

const SUMMARY_TYPES = ['temporal', 'thematic', 'insight'] as const;

export const MemoryReflectionPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l3Summaries, refresh } = useMemory({ initialLoadScope: 'l3' });
  const [query, setQuery] = useState('');

  const filteredSummaries = useMemo(
    () =>
      l3Summaries.filter((summary) => {
        const normalizedQuery = query.trim().toLowerCase();
        const topicMatches = summary.key_topics.some((topic) => topic.toLowerCase().includes(normalizedQuery));
        const entityMatches = (summary.key_entities || []).some((entity) =>
          [entity.entity_id, entity.entity_type].some((value) =>
            typeof value === 'string' && value.toLowerCase().includes(normalizedQuery)
          )
        );
        const matchesQuery =
          normalizedQuery.length === 0 ||
          summary.content.toLowerCase().includes(normalizedQuery) ||
          summary.summary_category.toLowerCase().includes(normalizedQuery) ||
          summary.summary_type.toLowerCase().includes(normalizedQuery) ||
          topicMatches ||
          entityMatches;
        return matchesQuery;
      }),
    [l3Summaries, query]
  );

  const keyTopics = Array.from(
    filteredSummaries.reduce((set, summary) => {
      summary.key_topics.forEach((topic) => {
        if (topic) set.add(topic);
      });
      return set;
    }, new Set<string>())
  );

  const insightCategories = Array.from(
    filteredSummaries.reduce((set, summary) => {
      if (summary.summary_type === 'insight' && summary.summary_category) {
        set.add(summary.summary_category);
      }
      return set;
    }, new Set<string>())
  ).sort();

  const typeSummaryText = SUMMARY_TYPES.map((summaryType) => (
    `${t(`memory.pages.reflection.types.${summaryType}`)} · ${
      filteredSummaries.filter((summary) => summary.summary_type === summaryType).length
    }`
  )).join(' / ');

  const insightLabels = insightCategories
    .slice(0, 4)
    .map((category) => t(`memory.pages.reflection.categories.${category}`, { defaultValue: category }));
  const topicSummaryText = [...insightLabels, ...keyTopics]
    .filter((value, index, values) => Boolean(value) && values.indexOf(value) === index)
    .slice(0, 6)
    .join(' / ');

  return (
    <MemoryPageFrame
      title={t('memory.nav.reflection')}
      description={t('memory.pages.reflection.subtitle')}
      actions={
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          onClick={() => void refresh('l3')}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <div className="grid gap-3">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-reflection-query">
              {t('memory.filters.searchLabel')}
            </label>
            <Input
              id="memory-reflection-query"
              className={MEMORY_FILTER_INPUT_CLASS}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('memory.pages.reflection.searchPlaceholder')}
            />
          </div>
        </div>
      )}
    >
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[0.96fr_1.04fr]">
            <MemoryWorkspacePanel
              title={t('memory.pages.reflection.cadenceTitle')}
            >
              <p className="min-h-[3.5rem] text-sm leading-7 text-[hsl(var(--memory-body))]">
                {filteredSummaries.length === 0 ? t('memory.l3.noSummaries') : typeSummaryText}
              </p>
            </MemoryWorkspacePanel>

            <MemoryWorkspacePanel
              title={t('memory.pages.reflection.topicsTitle')}
            >
              <p className="min-h-[3.5rem] text-sm leading-7 text-[hsl(var(--memory-body))]">
                {topicSummaryText || t('memory.pages.reflection.noTopics')}
              </p>
            </MemoryWorkspacePanel>
          </div>

          <L3Tab stats={stats.l3} summaries={filteredSummaries} />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryReflectionPage;
