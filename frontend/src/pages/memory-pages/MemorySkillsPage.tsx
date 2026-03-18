import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L4Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, { MEMORY_FILTER_INPUT_CLASS, MEMORY_FILTER_SELECT_CLASS, MemoryHeroStat } from './MemoryPageFrame';

export const MemorySkillsPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l4Skills, refresh } = useMemory();
  const [query, setQuery] = useState('');
  const [breakerFilter, setBreakerFilter] = useState('all');

  const filteredSkills = useMemo(
    () =>
      l4Skills.filter((skill) => {
        const normalizedQuery = query.trim().toLowerCase();
        const matchesQuery =
          normalizedQuery.length === 0 ||
          skill.skill_name.toLowerCase().includes(normalizedQuery) ||
          skill.skill_category.toLowerCase().includes(normalizedQuery);
        const matchesBreaker =
          breakerFilter === 'all' || skill.circuit_breaker_state === breakerFilter;
        return matchesQuery && matchesBreaker;
      }),
    [breakerFilter, l4Skills, query]
  );

  const highSuccessCount = filteredSkills.filter((skill) => skill.success_rate > 0.8).length;

  return (
    <MemoryPageFrame
      title={t('memory.nav.skills')}
      description={t('memory.pages.skills.subtitle')}
      eyebrow={t('memory.pages.skills.eyebrow')}
      heroStats={(
        <div className="grid gap-3 sm:grid-cols-3">
          <MemoryHeroStat label={t('memory.l4.skillCount')} value={stats.l4.skill_count} tone="accent" />
          <MemoryHeroStat label={t('memory.l4.openBreakers')} value={stats.l4.open_circuit_breakers} />
          <MemoryHeroStat label={t('memory.l4.highSuccess')} value={highSuccessCount} />
        </div>
      )}
      heroAside={(
        <div className="space-y-3">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-[#8e705a]">
            {t('memory.pages.skills.focusTitle')}
          </div>
          <div className="text-lg font-semibold text-[#35261c]">{t('memory.pages.skills.focusHeadline')}</div>
          <p className="leading-6">{t('memory.pages.skills.focusBody')}</p>
        </div>
      )}
      actions={
        <Button
          variant="outline"
          className="rounded-2xl border-[#dfc8b5] bg-white/80 hover:bg-white"
          onClick={() => void refresh('l4')}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-skills-query">
              {t('memory.filters.searchLabel')}
            </label>
            <Input
              id="memory-skills-query"
              className={MEMORY_FILTER_INPUT_CLASS}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('memory.pages.skills.searchPlaceholder')}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-skills-breaker">
              {t('memory.filters.breakerLabel')}
            </label>
            <select
              id="memory-skills-breaker"
              className={MEMORY_FILTER_SELECT_CLASS}
              value={breakerFilter}
              onChange={(event) => setBreakerFilter(event.target.value)}
            >
              <option value="all">{t('memory.filters.all')}</option>
              <option value="closed">{t('memory.filters.closed')}</option>
              <option value="open">{t('memory.filters.open')}</option>
            </select>
          </div>
        </div>
      )}
    >
      {loading ? <LoadingSpinner /> : <L4Tab stats={stats.l4} skills={filteredSkills} />}
    </MemoryPageFrame>
  );
};

export default MemorySkillsPage;
