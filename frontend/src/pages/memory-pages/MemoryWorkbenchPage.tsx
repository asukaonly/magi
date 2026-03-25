import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L0Tab } from '@/components/memory';
import { formatTimestamp, useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_INFO_PANEL_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
  MemoryTag,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';

export const MemoryWorkbenchPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l0Sessions, l0Workbench, selectedSessionId, selectSession, refresh } = useMemory({
    initialLoadScope: 'l0',
  });
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
  const selectedSession = filteredSessions.find((session) => session.session_id === selectedSessionId) ?? null;

  return (
    <MemoryPageFrame
      title={t('memory.nav.workbench')}
      description={t('memory.pages.workbench.subtitle')}
      actions={
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
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
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <MemoryWorkspacePanel
              title={t('memory.pages.workbench.sessionTitle')}
              description={t('memory.pages.workbench.sessionBody')}
            >
              {selectedSession ? (
                <div className="space-y-3">
                  <div className={MEMORY_INFO_PANEL_CLASS}>
                    <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{selectedSession.session_id}</div>
                    <div className="mt-2 text-sm text-[hsl(var(--memory-body))]">
                      {t('memory.pages.workbench.lastActiveLabel', {
                        time: formatTimestamp(selectedSession.last_active_at),
                      })}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <MemoryTag>{t('memory.l0.totalGoals')}: {selectedSession.goal_count}</MemoryTag>
                    <MemoryTag>{t('memory.l0.totalEntities')}: {selectedSession.entity_count}</MemoryTag>
                    <MemoryTag>{t('memory.l0.totalTactics')}: {selectedSession.tactic_count}</MemoryTag>
                  </div>
                </div>
              ) : (
                <div className={MEMORY_EMPTY_PANEL_CLASS}>
                  {t('memory.pages.workbench.focusEmpty')}
                </div>
              )}
            </MemoryWorkspacePanel>

            <MemoryWorkspacePanel
              title={t('memory.pages.workbench.queueTitle')}
              description={t('memory.pages.workbench.queueBody')}
            >
              <div className="flex flex-wrap gap-2">
                {filteredSessions.slice(0, 6).map((session) => (
                  <MemoryTag key={session.session_id}>
                    {session.session_id.slice(0, 8)} · {session.status}
                  </MemoryTag>
                ))}
                {filteredSessions.length === 0 ? <MemoryTag>{t('memory.l0.noSessions')}</MemoryTag> : null}
              </div>
            </MemoryWorkspacePanel>
          </div>

          <L0Tab
            stats={stats.l0}
            sessions={filteredSessions}
            workbench={l0Workbench}
            selectedSessionId={selectedSessionId}
            onSelectSession={selectSession}
          />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryWorkbenchPage;
