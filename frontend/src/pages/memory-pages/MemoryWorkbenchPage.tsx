import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Clock3, FolderKanban, MessageSquareText, Target } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { getL0SessionPrimaryLabel, getL0SessionSecondaryLabel } from '@/api/modules/memory';
import { formatTimestamp, useMemory } from '@/hooks/useMemory';
import { cn } from '@/lib/utils';
import MemoryPageFrame, {
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_INFO_PANEL_CLASS,
  MEMORY_SECTION_CARD_CLASS,
  MemoryHeroStat,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';
import { MemoryPagination } from './MemoryPagination';

const PAGE_SIZE = 50;

const getEntityLabel = (entity: Record<string, unknown>) => {
  const snapshot = entity.snapshot as Record<string, unknown> | undefined;
  const snapshotName = snapshot?.name;
  const canonicalName = snapshot?.canonical_name;
  if (typeof snapshotName === 'string' && snapshotName.trim()) {
    return snapshotName;
  }
  if (typeof canonicalName === 'string' && canonicalName.trim()) {
    return canonicalName;
  }
  if (typeof entity.entity_id === 'string' && entity.entity_id.trim()) {
    return entity.entity_id;
  }
  return 'Entity';
};

const getTacticLabel = (tactic: Record<string, unknown>) => {
  const payload = tactic.tactic_payload as Record<string, unknown> | undefined;
  const payloadName = payload?.name;
  const payloadTitle = payload?.title;
  if (typeof payloadName === 'string' && payloadName.trim()) {
    return payloadName;
  }
  if (typeof payloadTitle === 'string' && payloadTitle.trim()) {
    return payloadTitle;
  }
  if (typeof tactic.tactic_type === 'string' && tactic.tactic_type.trim()) {
    return tactic.tactic_type;
  }
  if (typeof tactic.tactic_id === 'string' && tactic.tactic_id.trim()) {
    return tactic.tactic_id;
  }
  return 'Tactic';
};

const getGoalLabel = (goal: Record<string, unknown>, index: number) => {
  if (typeof goal.description === 'string' && goal.description.trim()) {
    return goal.description;
  }
  if (typeof goal.goal_id === 'string' && goal.goal_id.trim()) {
    return goal.goal_id;
  }
  return `Goal ${index + 1}`;
};

const getSessionWorkbenchState = (sessionId: string, workbench: ReturnType<typeof useMemory>['l0Workbench']) => {
  const workbenchSessionId = String((workbench?.session as Record<string, unknown> | null)?.session_id || '').trim();
  if (!workbench || workbenchSessionId !== sessionId) {
    return {
      goalStack: [] as Array<Record<string, unknown>>,
      activeEntities: [] as Array<Record<string, unknown>>,
      temporaryTactics: [] as Array<Record<string, unknown>>,
      isLoaded: false,
    };
  }
  return {
    goalStack: Array.isArray(workbench.goal_stack) ? workbench.goal_stack : [],
    activeEntities: Array.isArray(workbench.active_entities) ? workbench.active_entities : [],
    temporaryTactics: Array.isArray(workbench.temporary_tactics) ? workbench.temporary_tactics : [],
    isLoaded: true,
  };
};

const SessionInfoField = ({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) => (
  <div className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.72)] px-3 py-3">
    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
      {icon}
      <span>{label}</span>
    </div>
    <div className="mt-2 text-sm leading-6 text-[hsl(var(--memory-title))]">{value}</div>
  </div>
);

export const MemoryWorkbenchPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l0Sessions, l0Total, l0Workbench, selectedSessionId, selectSession, loadL0Sessions } = useMemory({
    initialLoadScope: 'l0',
  });
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [offset, setOffset] = useState(0);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);

  // Reload sessions when filters or page change.
  const reloadSessions = useCallback(() => {
    void loadL0Sessions({
      limit: PAGE_SIZE,
      offset,
      ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
      ...(query.trim() ? { query: query.trim() } : {}),
    });
  }, [loadL0Sessions, offset, statusFilter, query]);

  useEffect(() => {
    reloadSessions();
  }, [reloadSessions]);

  // Reset offset when filters change.
  useEffect(() => {
    setOffset(0);
  }, [query, statusFilter]);

  const handlePageChange = useCallback((newOffset: number) => {
    setOffset(newOffset);
  }, []);

  const statusOptions = useMemo(
    () => [
      { value: 'active', label: t('memory.filters.active') },
      { value: 'idle', label: t('memory.filters.idle') },
    ],
    [t]
  );

  useEffect(() => {
    if (expandedSessionId && l0Sessions.every((session) => session.session_id !== expandedSessionId)) {
      setExpandedSessionId(null);
    }
    if (selectedSessionId && l0Sessions.every((session) => session.session_id !== selectedSessionId)) {
      selectSession(null);
    }
  }, [expandedSessionId, l0Sessions, selectSession, selectedSessionId]);

  const handleToggleSession = useCallback((sessionId: string) => {
    setExpandedSessionId((current) => {
      if (current === sessionId) {
        return null;
      }
      return sessionId;
    });
    if (selectedSessionId !== sessionId) {
      selectSession(sessionId);
    }
  }, [selectSession, selectedSessionId]);

  return (
    <MemoryPageFrame
      title={t('memory.nav.workbench')}
      description={t('memory.pages.workbench.subtitle')}
      actions={
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          onClick={() => void reloadSessions()}
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
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MemoryHeroStat label={t('memory.l0.activeSessions')} value={stats.l0.active_sessions} tone="accent" />
            <MemoryHeroStat label={t('memory.l0.totalGoals')} value={stats.l0.total_goals} />
            <MemoryHeroStat label={t('memory.l0.totalEntities')} value={stats.l0.total_entities} />
            <MemoryHeroStat label={t('memory.l0.totalTactics')} value={stats.l0.total_tactics} />
          </div>

          <MemoryWorkspacePanel
            title={t('memory.l0.sessions')}
            description={t('memory.pages.workbench.sessionListBody')}
          >
            {l0Sessions.length === 0 ? (
              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                {t('memory.l0.noSessions')}
              </div>
            ) : (
              <div className="overflow-hidden rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)]">
                {l0Sessions.map((session, index) => {
                  const isExpanded = expandedSessionId === session.session_id;
                  const { goalStack, activeEntities, temporaryTactics, isLoaded } = getSessionWorkbenchState(session.session_id, l0Workbench);
                  const hasWorkbenchContent = goalStack.length > 0 || activeEntities.length > 0 || temporaryTactics.length > 0;
                  const lastUserPreview = String(session.last_user_message_preview || '').trim();
                  const lastMessagePreview = String(session.last_message_preview || '').trim();
                  const workspacePath = String(session.workspace_path || '').trim();
                  const secondaryLabel = getL0SessionSecondaryLabel(session);

                  return (
                    <Collapsible key={session.session_id} open={isExpanded} onOpenChange={() => handleToggleSession(session.session_id)}>
                      <div className={cn(index > 0 && 'border-t border-[hsl(var(--memory-divider)/0.52)]')}>
                        <CollapsibleTrigger
                          className={cn(
                            'w-full text-left transition-colors',
                            isExpanded ? 'bg-[hsl(var(--memory-panel-subtle)/0.76)]' : 'hover:bg-[hsl(var(--memory-panel-subtle)/0.44)]'
                          )}
                        >
                          <div className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_160px_112px_44px] md:items-center">
                            <div className="min-w-0">
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="truncate text-sm font-semibold text-[hsl(var(--memory-title))]">
                                  {getL0SessionPrimaryLabel(session)}
                                </span>
                                <span className="shrink-0 rounded-full border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.76)] px-2 py-0.5 text-[11px] text-[hsl(var(--memory-muted))]">
                                  {session.message_count ?? 0} {t('memory.pages.workbench.messagesUnit')}
                                </span>
                              </div>
                              {secondaryLabel ? (
                                <div className="mt-1 truncate text-xs text-[hsl(var(--memory-muted))]">
                                  {secondaryLabel}
                                </div>
                              ) : null}
                              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
                                <span>{t('memory.pages.workbench.goalSummary', { count: session.goal_count })}</span>
                                <span>{t('memory.pages.workbench.entitySummary', { count: session.entity_count })}</span>
                                <span>{t('memory.pages.workbench.tacticSummary', { count: session.tactic_count })}</span>
                              </div>
                            </div>

                            <div className="text-sm text-[hsl(var(--memory-body))] md:text-right">
                              {formatTimestamp(session.last_active_at)}
                            </div>

                            <div className="md:justify-self-end">
                              <span className="inline-flex items-center gap-1 rounded-full border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.76)] px-2.5 py-1 text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                                {session.status}
                              </span>
                            </div>

                            <div className="flex justify-end">
                              <span className="flex h-8 w-8 items-center justify-center rounded-md border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.82)] text-[hsl(var(--memory-muted))]">
                                {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                              </span>
                            </div>
                          </div>
                        </CollapsibleTrigger>

                        <CollapsibleContent>
                          <div className="border-t border-[hsl(var(--memory-divider)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.44)] px-4 py-4">
                            <div className="space-y-4">
                              <div className="grid gap-3 lg:grid-cols-3">
                                <SessionInfoField
                                  label={t('memory.pages.workbench.startedLabel')}
                                  value={formatTimestamp(session.started_at)}
                                  icon={<Clock3 className="h-3.5 w-3.5" />}
                                />
                                <SessionInfoField
                                  label={t('memory.pages.workbench.lastActiveShortLabel')}
                                  value={formatTimestamp(session.last_active_at)}
                                  icon={<Clock3 className="h-3.5 w-3.5" />}
                                />
                                <SessionInfoField
                                  label={t('memory.pages.workbench.workspaceLabel')}
                                  value={workspacePath || t('memory.pages.workbench.noWorkspace')}
                                  icon={<FolderKanban className="h-3.5 w-3.5" />}
                                />
                              </div>

                              {(lastUserPreview || lastMessagePreview) ? (
                                <div className="grid gap-3 lg:grid-cols-2">
                                  {lastUserPreview ? (
                                    <div className={MEMORY_INFO_PANEL_CLASS}>
                                      <div className="flex items-center gap-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
                                        <MessageSquareText className="h-3.5 w-3.5" />
                                        {t('memory.pages.workbench.lastUserMessageLabel')}
                                      </div>
                                      <div className="mt-2 text-sm leading-6 text-[hsl(var(--memory-title))]">{lastUserPreview}</div>
                                    </div>
                                  ) : null}
                                  {lastMessagePreview ? (
                                    <div className={MEMORY_INFO_PANEL_CLASS}>
                                      <div className="flex items-center gap-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
                                        <MessageSquareText className="h-3.5 w-3.5" />
                                        {t('memory.pages.workbench.lastMessageLabel')}
                                      </div>
                                      <div className="mt-2 text-sm leading-6 text-[hsl(var(--memory-title))]">{lastMessagePreview}</div>
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}

                              {!isLoaded || !hasWorkbenchContent ? (
                                <div className={MEMORY_EMPTY_PANEL_CLASS}>
                                  {t('memory.pages.workbench.shellEmpty')}
                                </div>
                              ) : null}

                              {goalStack.length > 0 ? (
                                <section className={MEMORY_SECTION_CARD_CLASS}>
                                  <div className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
                                    <Target className="h-4 w-4" />
                                    {t('memory.pages.workbench.currentGoalsTitle')}
                                  </div>
                                  <div className="mt-3 space-y-2">
                                    {goalStack.map((goal, goalIndex) => {
                                      const item = goal as Record<string, unknown>;
                                      return (
                                        <div
                                          key={String(item.goal_id ?? goalIndex)}
                                          className="rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.68)] px-3 py-2 text-sm leading-6 text-[hsl(var(--memory-body))]"
                                        >
                                          {getGoalLabel(item, goalIndex)}
                                        </div>
                                      );
                                    })}
                                  </div>
                                </section>
                              ) : null}

                              {activeEntities.length > 0 ? (
                                <section className={MEMORY_SECTION_CARD_CLASS}>
                                  <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                                    {t('memory.pages.workbench.activeEntitiesTitle')}
                                  </div>
                                  <div className="mt-3 flex flex-wrap gap-2">
                                    {activeEntities.map((entity, entityIndex) => {
                                      const item = entity as Record<string, unknown>;
                                      return (
                                        <div
                                          key={String(item.entity_id ?? entityIndex)}
                                          className="rounded-full border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.68)] px-3 py-1.5 text-xs text-[hsl(var(--memory-body))]"
                                        >
                                          {getEntityLabel(item)}
                                        </div>
                                      );
                                    })}
                                  </div>
                                </section>
                              ) : null}

                              {temporaryTactics.length > 0 ? (
                                <section className={MEMORY_SECTION_CARD_CLASS}>
                                  <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                                    {t('memory.pages.workbench.currentTacticsTitle')}
                                  </div>
                                  <div className="mt-3 space-y-2">
                                    {temporaryTactics.map((tactic, tacticIndex) => {
                                      const item = tactic as Record<string, unknown>;
                                      return (
                                        <div
                                          key={String(item.tactic_id ?? tacticIndex)}
                                          className="rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.68)] px-3 py-2 text-sm leading-6 text-[hsl(var(--memory-body))]"
                                        >
                                          {getTacticLabel(item)}
                                        </div>
                                      );
                                    })}
                                  </div>
                                </section>
                              ) : null}
                            </div>
                          </div>
                        </CollapsibleContent>
                      </div>
                    </Collapsible>
                  );
                })}
              </div>
            )}
          </MemoryWorkspacePanel>

          <MemoryPagination
            total={l0Total}
            offset={offset}
            limit={PAGE_SIZE}
            loading={loading}
            onPageChange={handlePageChange}
          />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryWorkbenchPage;
