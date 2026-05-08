import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Clock3, FileText, FolderKanban, Gauge, MessageSquareText, Target } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { getL0SessionPrimaryLabel, getL0SessionSecondaryLabel } from '@/api/modules/memory';
import { useMemory } from '@/hooks/useMemory';
import { cn } from '@/lib/utils';
import { useContextUsageStore, type ContextUsageSnapshot } from '@/stores/context-usage';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_INFO_PANEL_CLASS,
  MEMORY_SECTION_CARD_CLASS,
  MemoryHeroStat,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';
import { MemoryPagination } from './MemoryPagination';

const PAGE_SIZE = 50;
const GENERIC_SESSION_LABELS = new Set(['', 'new chat', 'new session', '新对话', '新会话']);

const formatWorkbenchTimestamp = (ts: number): string => {
  if (!ts) {
    return '-';
  }

  const date = new Date(ts * 1000);
  return formatWorkbenchDate(date);
};

const formatWorkbenchTimestampMs = (value: number | null | undefined): string => {
  const numericValue = Number(value || 0);
  if (!numericValue) {
    return '-';
  }

  const timestampMs = numericValue > 10_000_000_000 ? numericValue : numericValue * 1000;
  return formatWorkbenchDate(new Date(timestampMs));
};

const formatWorkbenchDate = (date: Date): string => {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

const formatTokenCount = (value: number | null | undefined): string => {
  const count = Number(value || 0);
  if (count <= 0) {
    return '-';
  }
  return Math.round(count).toLocaleString();
};

const formatUsagePercent = (usedTokens: number, windowSize: number): string => {
  if (windowSize <= 0) {
    return '-';
  }
  return `${Math.round(Math.min(usedTokens / windowSize, 1) * 100)}%`;
};

const getNumberField = (record: Record<string, unknown> | null | undefined, key: string): number => {
  const value = record?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
};

const isGenericSessionTitle = (value: string | null | undefined) =>
  GENERIC_SESSION_LABELS.has(String(value || '').trim().toLowerCase());

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

const resolveSessionTitle = (
  session: Parameters<typeof getL0SessionPrimaryLabel>[0],
  fallbackLabel: string,
) => {
  const title = getL0SessionPrimaryLabel(session);
  const normalizedTitle = String(title || '').trim();
  const shortSessionId = String(session.short_session_id || '').trim();
  const sessionId = String(session.session_id || '').trim();

  if (!normalizedTitle || isGenericSessionTitle(normalizedTitle)) {
    return fallbackLabel;
  }

  if (normalizedTitle === shortSessionId || normalizedTitle === sessionId) {
    return fallbackLabel;
  }

  return normalizedTitle;
};

const getSessionWorkbenchState = (sessionId: string, workbench: ReturnType<typeof useMemory>['l0Workbench']) => {
  const workbenchSessionId = String((workbench?.session as Record<string, unknown> | null)?.session_id || '').trim();
  if (!workbench || workbenchSessionId !== sessionId) {
    return {
      goalStack: [] as Array<Record<string, unknown>>,
      activeEntities: [] as Array<Record<string, unknown>>,
      temporaryTactics: [] as Array<Record<string, unknown>>,
      activeContextSummary: null,
      contextUsage: null,
      isLoaded: false,
    };
  }
  return {
    goalStack: Array.isArray(workbench.goal_stack) ? workbench.goal_stack : [],
    activeEntities: Array.isArray(workbench.active_entities) ? workbench.active_entities : [],
    temporaryTactics: Array.isArray(workbench.temporary_tactics) ? workbench.temporary_tactics : [],
    activeContextSummary: workbench.active_context_summary ?? null,
    contextUsage: workbench.context_usage ?? null,
    isLoaded: true,
  };
};

const normalizeContextUsage = (
  apiUsage: unknown,
  liveUsage?: ContextUsageSnapshot,
) => {
  if (liveUsage && liveUsage.windowSize > 0) {
    return {
      usedTokens: liveUsage.usedTokens,
      windowSize: liveUsage.windowSize,
      threshold: liveUsage.threshold,
      updatedAtMs: liveUsage.updatedAt,
    };
  }

  const usageRecord = apiUsage && typeof apiUsage === 'object' ? apiUsage as Record<string, unknown> : null;
  if (!usageRecord) {
    return null;
  }

  const usedTokens = getNumberField(usageRecord, 'used_tokens');
  const windowSize = getNumberField(usageRecord, 'window_size');
  if (windowSize <= 0) {
    return null;
  }

  const timestamp = getNumberField(usageRecord, 'timestamp');
  const createdAtMs = getNumberField(usageRecord, 'created_at_ms');
  return {
    usedTokens,
    windowSize,
    threshold: getNumberField(usageRecord, 'threshold'),
    updatedAtMs: createdAtMs || (timestamp ? timestamp * 1000 : 0),
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
  const liveContextUsage = useContextUsageStore((state) => (
    expandedSessionId ? state.usage[expandedSessionId] : undefined
  ));

  const reloadSessions = useCallback(() => {
    void loadL0Sessions({
      limit: PAGE_SIZE,
      offset,
      ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
      ...(query.trim() ? { query: query.trim() } : {}),
    });
  }, [loadL0Sessions, offset, query, statusFilter]);

  useEffect(() => {
    reloadSessions();
  }, [reloadSessions]);

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
    setExpandedSessionId((current) => (current === sessionId ? null : sessionId));
    if (selectedSessionId !== sessionId) {
      selectSession(sessionId);
    }
  }, [selectSession, selectedSessionId]);

  return (
    <MemoryPageFrame
      title={t('memory.nav.workbench')}
      description={t('memory.pages.workbench.subtitle')}
      actions={(
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          onClick={() => void reloadSessions()}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      )}
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
                  const {
                    goalStack,
                    activeEntities,
                    temporaryTactics,
                    activeContextSummary,
                    contextUsage,
                    isLoaded,
                  } = getSessionWorkbenchState(session.session_id, l0Workbench);
                  const normalizedContextUsage = normalizeContextUsage(contextUsage, isExpanded ? liveContextUsage : undefined);
                  const hasWorkbenchContent = goalStack.length > 0 || activeEntities.length > 0 || temporaryTactics.length > 0;
                  const showWorkbenchLoading = isExpanded && selectedSessionId === session.session_id && !isLoaded;
                  const lastUserPreview = String(session.last_user_message_preview || '').trim();
                  const lastMessagePreview = String(session.last_message_preview || '').trim();
                  const workspacePath = String(session.workspace_path || '').trim();
                  const secondaryLabel = getL0SessionSecondaryLabel(session);
                  const sessionTitle = resolveSessionTitle(session, t('memory.pages.workbench.untitledSession'));
                  const summaryText = String(activeContextSummary?.summary_text || '').trim();
                  const summaryModel = [
                    String(activeContextSummary?.model_provider || '').trim(),
                    String(activeContextSummary?.model_id || '').trim(),
                  ].filter(Boolean).join(' / ');
                  const summaryTokenBefore = Number(activeContextSummary?.token_count_before || 0);
                  const summaryTokenAfter = Number(activeContextSummary?.token_count_after || 0);
                  const summaryCoveredSequence = Number(activeContextSummary?.covered_to_sequence_no || 0);
                  const summaryUpdatedAt = Number(activeContextSummary?.updated_at_ms || activeContextSummary?.created_at_ms || 0);

                  return (
                    <div key={session.session_id} className={cn(index > 0 && 'border-t border-[hsl(var(--memory-divider)/0.52)]')}>
                      <button
                        type="button"
                        onClick={() => handleToggleSession(session.session_id)}
                        className={cn(
                          'w-full text-left transition-colors',
                          isExpanded ? 'bg-[hsl(var(--memory-panel-subtle)/0.76)]' : 'hover:bg-[hsl(var(--memory-panel-subtle)/0.44)]'
                        )}
                      >
                        <div className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_180px_152px] md:items-center">
                          <div className="min-w-0">
                            <div className="flex min-w-0 items-center gap-2">
                              <span className="truncate text-sm font-semibold text-[hsl(var(--memory-title))]">
                                {sessionTitle}
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
                            <div className="mt-1 truncate text-xs text-[hsl(var(--memory-muted))]">
                              {t('memory.pages.workbench.workbenchSummary', {
                                goals: session.goal_count,
                                entities: session.entity_count,
                                tactics: session.tactic_count,
                              })}
                            </div>
                          </div>

                          <div className="text-sm text-[hsl(var(--memory-body))] md:text-right">
                            {formatWorkbenchTimestamp(session.last_active_at)}
                          </div>

                          <div className="flex items-center justify-end gap-3">
                            <span className="inline-flex items-center gap-1 rounded-full border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.76)] px-2.5 py-1 text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                              {session.status}
                            </span>
                            <span className="flex h-8 w-8 items-center justify-center rounded-md border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.82)] text-[hsl(var(--memory-muted))]">
                              {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            </span>
                          </div>
                        </div>
                      </button>

                      {isExpanded ? (
                        <div className="border-t border-[hsl(var(--memory-divider)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.44)] px-4 py-4">
                          <div className="space-y-4">
                            <div className="grid gap-3 lg:grid-cols-3">
                              <SessionInfoField
                                label={t('memory.pages.workbench.startedLabel')}
                                value={formatWorkbenchTimestamp(session.started_at)}
                                icon={<Clock3 className="h-3.5 w-3.5" />}
                              />
                              <SessionInfoField
                                label={t('memory.pages.workbench.lastActiveShortLabel')}
                                value={formatWorkbenchTimestamp(session.last_active_at)}
                                icon={<Clock3 className="h-3.5 w-3.5" />}
                              />
                              <SessionInfoField
                                label={t('memory.pages.workbench.workspaceLabel')}
                                value={workspacePath || t('memory.pages.workbench.defaultWorkspaceLabel')}
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

                            {isLoaded ? (
                              <div className="grid gap-3 lg:grid-cols-2">
                                <section className={MEMORY_INFO_PANEL_CLASS}>
                                  <div className="flex items-center gap-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
                                    <Gauge className="h-3.5 w-3.5" />
                                    {t('memory.pages.workbench.contextUsageTitle')}
                                  </div>
                                  {normalizedContextUsage ? (
                                    <>
                                      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                                        <span className="text-lg font-semibold text-[hsl(var(--memory-title))]">
                                          {formatUsagePercent(normalizedContextUsage.usedTokens, normalizedContextUsage.windowSize)}
                                        </span>
                                        <span className="text-sm text-[hsl(var(--memory-body))]">
                                          {t('memory.pages.workbench.contextUsageValue', {
                                            used: formatTokenCount(normalizedContextUsage.usedTokens),
                                            window: formatTokenCount(normalizedContextUsage.windowSize),
                                          })}
                                        </span>
                                      </div>
                                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[hsl(var(--memory-muted))]">
                                        {normalizedContextUsage.threshold > 0 ? (
                                          <span>
                                            {t('memory.pages.workbench.contextUsageThreshold', {
                                              threshold: formatTokenCount(normalizedContextUsage.threshold),
                                            })}
                                          </span>
                                        ) : null}
                                        {normalizedContextUsage.updatedAtMs > 0 ? (
                                          <span>
                                            {t('memory.pages.workbench.contextUsageUpdated', {
                                              time: formatWorkbenchTimestampMs(normalizedContextUsage.updatedAtMs),
                                            })}
                                          </span>
                                        ) : null}
                                      </div>
                                    </>
                                  ) : (
                                    <div className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
                                      {t('memory.pages.workbench.contextUsageEmpty')}
                                    </div>
                                  )}
                                </section>

                                {summaryText ? (
                                  <section className={MEMORY_INFO_PANEL_CLASS}>
                                    <div className="flex items-center gap-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
                                      <FileText className="h-3.5 w-3.5" />
                                      {t('memory.pages.workbench.contextSummaryTitle')}
                                    </div>
                                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[hsl(var(--memory-muted))]">
                                      {summaryCoveredSequence > 0 ? (
                                        <span>
                                          {t('memory.pages.workbench.contextSummaryCoverage', {
                                            sequence: summaryCoveredSequence,
                                          })}
                                        </span>
                                      ) : null}
                                      {summaryTokenBefore > 0 && summaryTokenAfter > 0 ? (
                                        <span>
                                          {t('memory.pages.workbench.contextSummaryTokenDelta', {
                                            before: formatTokenCount(summaryTokenBefore),
                                            after: formatTokenCount(summaryTokenAfter),
                                          })}
                                        </span>
                                      ) : null}
                                      {summaryUpdatedAt > 0 ? (
                                        <span>
                                          {t('memory.pages.workbench.contextSummaryUpdated', {
                                            time: formatWorkbenchTimestampMs(summaryUpdatedAt),
                                          })}
                                        </span>
                                      ) : null}
                                      {summaryModel ? (
                                        <span>
                                          {t('memory.pages.workbench.contextSummaryModel', { model: summaryModel })}
                                        </span>
                                      ) : null}
                                    </div>
                                    <div className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-title))]">
                                      {summaryText}
                                    </div>
                                  </section>
                                ) : null}
                              </div>
                            ) : null}

                            {showWorkbenchLoading ? (
                              <div className={MEMORY_EMPTY_PANEL_CLASS}>
                                <div className="flex items-center gap-2">
                                  <LoadingSpinner className="h-4 w-4" />
                                  <span>{t('memory.pages.workbench.loadingWorkbench')}</span>
                                </div>
                              </div>
                            ) : null}

                            {!showWorkbenchLoading && !hasWorkbenchContent ? (
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
                      ) : null}
                    </div>
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
