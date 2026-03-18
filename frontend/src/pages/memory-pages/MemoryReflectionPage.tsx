import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L3Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
  MemoryHeroStat,
  MemoryTag,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';

export const MemoryReflectionPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l3Summaries, refresh } = useMemory();
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');

  const summaryTypes = useMemo(
    () => Array.from(new Set(l3Summaries.map((summary) => summary.summary_type).filter(Boolean))).sort(),
    [l3Summaries]
  );

  const filteredSummaries = useMemo(
    () =>
      l3Summaries.filter((summary) => {
        const normalizedQuery = query.trim().toLowerCase();
        const matchesQuery =
          normalizedQuery.length === 0 ||
          summary.content.toLowerCase().includes(normalizedQuery) ||
          summary.summary_category.toLowerCase().includes(normalizedQuery);
        const matchesType = typeFilter === 'all' || summary.summary_type === typeFilter;
        return matchesQuery && matchesType;
      }),
    [l3Summaries, query, typeFilter]
  );

  const summaryTypesCount = summaryTypes.length;
  const keyTopics = Array.from(
    filteredSummaries.reduce((set, summary) => {
      summary.key_topics.forEach((topic) => {
        if (topic) set.add(topic);
      });
      return set;
    }, new Set<string>())
  );

  return (
    <MemoryPageFrame
      title={t('memory.nav.reflection')}
      description={t('memory.pages.reflection.subtitle')}
      eyebrow={t('memory.pages.reflection.eyebrow')}
      heroStats={(
        <div className="grid gap-3 sm:grid-cols-3">
          <MemoryHeroStat label={t('memory.l3.summaryCount')} value={stats.l3.summary_count} tone="accent" />
          <MemoryHeroStat label={t('memory.filters.typeLabel')} value={summaryTypesCount} />
          <MemoryHeroStat label={t('memory.search')} value={filteredSummaries.length} />
        </div>
      )}
      heroAside={(
        <div className="space-y-3">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-[#8e705a]">
            {t('memory.pages.reflection.focusTitle')}
          </div>
          <div className="text-lg font-semibold text-[#35261c]">{t('memory.pages.reflection.focusHeadline')}</div>
          <p className="leading-6">{t('memory.pages.reflection.focusBody')}</p>
        </div>
      )}
      actions={
        <Button
          variant="outline"
          className="rounded-2xl border-[#dfc8b5] bg-white/80 hover:bg-white"
          onClick={() => void refresh('l3')}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
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
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-reflection-type">
              {t('memory.filters.typeLabel')}
            </label>
            <select
              id="memory-reflection-type"
              className={MEMORY_FILTER_SELECT_CLASS}
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
            >
              <option value="all">{t('memory.filters.all')}</option>
              {summaryTypes.map((summaryType) => (
                <option key={summaryType} value={summaryType}>
                  {summaryType}
                </option>
              ))}
            </select>
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
                {summaryTypes.map((summaryType) => (
                  <MemoryTag key={summaryType}>
                    {summaryType} · {filteredSummaries.filter((summary) => summary.summary_type === summaryType).length}
                  </MemoryTag>
                ))}
                {summaryTypes.length === 0 ? <MemoryTag>{t('memory.l3.noSummaries')}</MemoryTag> : null}
              </div>
            </MemoryWorkspacePanel>

            <MemoryWorkspacePanel
              title={t('memory.pages.reflection.topicsTitle')}
              description={t('memory.pages.reflection.topicsBody')}
            >
              <div className="flex flex-wrap gap-2">
                {keyTopics.slice(0, 8).map((topic) => (
                  <MemoryTag key={topic}>{topic}</MemoryTag>
                ))}
                {keyTopics.length === 0 ? <MemoryTag>{t('memory.pages.reflection.noTopics')}</MemoryTag> : null}
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
