import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L4Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame from './MemoryPageFrame';

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

  return (
    <MemoryPageFrame
      title={t('memory.nav.skills')}
      description={t('memory.pages.skills.subtitle')}
      actions={
        <Button variant="outline" onClick={() => void refresh('l4')} disabled={loading}>
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
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
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
