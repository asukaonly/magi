import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L4Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_INFO_PANEL_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
  MemoryTag,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';
import { MemoryPagination, PAGE_SIZE } from './MemoryPagination';

export const MemorySkillsPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l4Skills, l4Total, loadL4Skills, refresh } = useMemory({ initialLoadScope: 'l4' });
  const [query, setQuery] = useState('');
  const [breakerFilter, setBreakerFilter] = useState('all');
  const [offset, setOffset] = useState(0);

  const handlePageChange = async (newOffset: number) => {
    setOffset(newOffset);
    await loadL4Skills({ offset: newOffset });
  };

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
  const categories = Array.from(new Set(filteredSkills.map((skill) => skill.skill_category).filter(Boolean))).sort();
  const recentlyUsedSkill = filteredSkills.find((skill) => skill.last_used_at !== null) ?? null;

  return (
    <MemoryPageFrame
      title={t('memory.nav.dev.skills')}
      description={t('memory.pages.skills.subtitle')}
      actions={
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
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
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[1.02fr_0.98fr]">
            <MemoryWorkspacePanel
              title={t('memory.pages.skills.categoryTitle')}
              description={t('memory.pages.skills.categoryBody')}
            >
              <div className="flex flex-wrap gap-2">
                {categories.map((category) => (
                  <MemoryTag key={category}>
                    {category} · {filteredSkills.filter((skill) => skill.skill_category === category).length}
                  </MemoryTag>
                ))}
                {categories.length === 0 ? <MemoryTag>{t('memory.l4.noSkills')}</MemoryTag> : null}
              </div>
            </MemoryWorkspacePanel>

            <MemoryWorkspacePanel
              title={t('memory.pages.skills.attentionTitle')}
              description={t('memory.pages.skills.attentionBody')}
            >
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <MemoryTag>{t('memory.l4.highSuccess')}: {highSuccessCount}</MemoryTag>
                  <MemoryTag>{t('memory.l4.openBreakers')}: {stats.l4.open_circuit_breakers}</MemoryTag>
                </div>
                {recentlyUsedSkill ? (
                  <div className={MEMORY_INFO_PANEL_CLASS}>
                    {t('memory.pages.skills.recentSkillLabel', { name: recentlyUsedSkill.skill_name })}
                  </div>
                ) : (
                  <div className={MEMORY_EMPTY_PANEL_CLASS}>
                    {t('memory.pages.skills.noRecentSkill')}
                  </div>
                )}
              </div>
            </MemoryWorkspacePanel>
          </div>

          <L4Tab stats={stats.l4} skills={filteredSkills} />

          <MemoryPagination
            total={l4Total}
            offset={offset}
            limit={PAGE_SIZE}
            loading={loading}
            onPageChange={(newOffset) => void handlePageChange(newOffset)}
          />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemorySkillsPage;
