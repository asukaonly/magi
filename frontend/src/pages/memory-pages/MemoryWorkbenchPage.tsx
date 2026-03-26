import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { L0Tab } from '@/components/memory';
import { formatTimestamp, useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_INFO_PANEL_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
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
  const statusOptions = useMemo(
    () => [
      { value: 'active', label: t('memory.filters.active') },
      { value: 'idle', label: t('memory.filters.idle') },
    ],
    [t]
  );

  useEffect(() => {
    if (!selectedSessionId && filteredSessions.length > 0) {
      selectSession(filteredSessions[0].session_id);
      return;
    }
    if (selectedSessionId && filteredSessions.every((session) => session.session_id !== selectedSessionId)) {
      selectSession(filteredSessions[0]?.session_id ?? null);
    }
  }, [filteredSessions, selectSession, selectedSessionId]);

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
        <div className="grid gap-x-3 gap-y-2.5 text-sm md:grid-cols-[minmax(0,1fr)_180px]">
          <div className="space-y-1">
            <label className="text-[13px] font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-workbench-query">
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
          <div className="space-y-1">
            <label className="text-[13px] font-medium text-[hsl(var(--memory-title))]">
              {t('memory.filters.statusLabel')}
            </label>
            <SelectField
              ariaLabel={t('memory.filters.statusLabel')}
              value={statusFilter}
              onChange={(value) => setStatusFilter(value || 'all')}
              options={statusOptions}
              placeholder={t('memory.filters.all')}
              allowEmpty={true}
              triggerClassName="h-9 rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] shadow-none focus-visible:ring-[hsl(var(--memory-accent-soft)/0.24)]"
              menuClassName="rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] shadow-[0_10px_20px_rgba(15,23,42,0.06)]"
            />
          </div>
        </div>
      )}
    >
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <MemoryWorkspacePanel
              title={t('memory.pages.workbench.sessionTitle')}
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
            >
              <div className="space-y-2 text-sm text-[hsl(var(--memory-body))]">
                {filteredSessions.slice(0, 6).map((session) => (
                  <div key={session.session_id} className="flex items-center justify-between gap-3">
                    <span className="truncate">{session.session_id}</span>
                    <span className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                      {session.status}
                    </span>
                  </div>
                ))}
                {filteredSessions.length === 0 ? <div className="text-[hsl(var(--memory-muted))]">{t('memory.l0.noSessions')}</div> : null}
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
