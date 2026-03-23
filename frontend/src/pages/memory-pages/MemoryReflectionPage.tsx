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
  MemoryTag,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';

export const MemoryReflectionPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l3Summaries, refresh } = useMemory();
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
          <div className="flex flex-wrap gap-2">
            {['temporal', 'thematic', 'insight'].map((summaryType) => (
              <MemoryTag key={summaryType}>
                {t(`memory.pages.reflection.types.${summaryType}`)} ·{' '}
                {filteredSummaries.filter((summary) => summary.summary_type === summaryType).length}
              </MemoryTag>
            ))}
            {insightCategories.slice(0, 4).map((category) => (
              <MemoryTag key={category}>
                {t(`memory.pages.reflection.categories.${category}`, { defaultValue: category })}
              </MemoryTag>
            ))}
          </div>
        </div>
      )}
    >
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[0.96fr_1.04fr]">
            <MemoryWorkspacePanel
              title={t('memory.pages.reflection.cadenceTitle')}
              description={t('memory.pages.reflection.cadenceBody')}
            >
              <div className="flex flex-wrap gap-2">
                {['temporal', 'thematic', 'insight'].map((summaryType) => (
                  <MemoryTag key={summaryType}>
                    {t(`memory.pages.reflection.types.${summaryType}`)} ·{' '}
                    {filteredSummaries.filter((summary) => summary.summary_type === summaryType).length}
                  </MemoryTag>
                ))}
                {filteredSummaries.length === 0 ? <MemoryTag>{t('memory.l3.noSummaries')}</MemoryTag> : null}
              </div>
            </MemoryWorkspacePanel>

            <MemoryWorkspacePanel
              title={t('memory.pages.reflection.insightTitle')}
              description={t('memory.pages.reflection.insightBody')}
            >
              <div className="flex flex-wrap gap-2">
                {insightCategories.slice(0, 8).map((category) => (
                  <MemoryTag key={category}>
                    {t(`memory.pages.reflection.categories.${category}`, { defaultValue: category })}
                  </MemoryTag>
                ))}
                {insightCategories.length === 0 ? (
                  keyTopics.slice(0, 8).map((topic) => (
                    <MemoryTag key={topic}>{topic}</MemoryTag>
                  ))
                ) : null}
                {keyTopics.length === 0 && insightCategories.length === 0 ? (
                  <MemoryTag>{t('memory.pages.reflection.noTopics')}</MemoryTag>
                ) : null}
              </div>
            </MemoryWorkspacePanel>
          </div>

          <L3Tab stats={stats.l3} summaries={filteredSummaries} />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryReflectionPage;
