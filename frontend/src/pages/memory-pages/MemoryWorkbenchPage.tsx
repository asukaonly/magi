import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L0Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, { MEMORY_FILTER_INPUT_CLASS, MEMORY_FILTER_SELECT_CLASS, MemoryHeroStat } from './MemoryPageFrame';

export const MemoryWorkbenchPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l0Sessions, l0Workbench, selectedSessionId, selectSession, refresh } = useMemory();
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const filteredSessions = useMemo(
    () =>
      l0Sessions.filter((session) => {
        const matchesQuery =
          query.trim().length === 0 ||
          session.session_id.toLowerCase().includes(query.toLowerCase()) ||
          session.status.toLowerCase().includes(query.toLowerCase());
        const matchesStatus = statusFilter === 'all' || session.status === statusFilter;
        return matchesQuery && matchesStatus;
      }),
    [l0Sessions, query, statusFilter]
  );

  return (
    <MemoryPageFrame
      title={t('memory.nav.workbench')}
      description={t('memory.pages.workbench.subtitle')}
      eyebrow={t('memory.pages.workbench.eyebrow')}
      heroStats={(
        <div className="grid gap-3 sm:grid-cols-3">
          <MemoryHeroStat label={t('memory.l0.activeSessions')} value={stats.l0.active_sessions} tone="accent" />
          <MemoryHeroStat label={t('memory.l0.totalGoals')} value={stats.l0.total_goals} />
          <MemoryHeroStat label={t('memory.l0.totalTactics')} value={stats.l0.total_tactics} />
        </div>
      )}
      heroAside={(
        <div className="space-y-3">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-[#8e705a]">
            {t('memory.pages.workbench.focusTitle')}
          </div>
          <div className="text-lg font-semibold text-[#35261c]">
            {selectedSessionId || t('memory.pages.workbench.focusEmpty')}
          </div>
          <p className="leading-6">{t('memory.pages.workbench.focusBody')}</p>
        </div>
      )}
      actions={
        <Button
          variant="outline"
          className="rounded-2xl border-[#dfc8b5] bg-white/80 hover:bg-white"
          onClick={() => void refresh('l0')}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-workbench-query">
              {t('memory.filters.searchLabel')}
            </label>
            <Input
              id="memory-workbench-query"
              className={MEMORY_FILTER_INPUT_CLASS}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('memory.pages.workbench.searchPlaceholder')}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-workbench-status">
              {t('memory.filters.statusLabel')}
            </label>
            <select
              id="memory-workbench-status"
              className={MEMORY_FILTER_SELECT_CLASS}
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="all">{t('memory.filters.all')}</option>
              <option value="active">{t('memory.filters.active')}</option>
              <option value="idle">{t('memory.filters.idle')}</option>
            </select>
          </div>
        </div>
      )}
    >
      {loading ? (
        <LoadingSpinner />
      ) : (
        <L0Tab
          stats={stats.l0}
          sessions={filteredSessions}
          workbench={l0Workbench}
          selectedSessionId={selectedSessionId}
          onSelectSession={selectSession}
        />
      )}
    </MemoryPageFrame>
  );
};

export default MemoryWorkbenchPage;
