import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L0Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame from './MemoryPageFrame';

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
      actions={
        <Button variant="outline" onClick={() => void refresh('l0')} disabled={loading}>
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
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
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
