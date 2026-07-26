import React from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import {
  getL0SessionPrimaryLabel,
  getL0SessionSecondaryLabel,
  type L0Session,
  type L0Workbench,
  type MemoryStatistics,
} from '@/api/modules/memory';

interface L0TabProps {
  stats: MemoryStatistics['l0'];
  sessions: L0Session[];
  workbench: L0Workbench | null;
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string | null) => void;
}

const PANEL_CLASS =
  'rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-4 py-4';

const EMPTY_PANEL_CLASS =
  'rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.32)] px-3 py-4 text-sm leading-6 text-[hsl(var(--memory-muted))] shadow-[inset_0_0_0_1px_hsl(var(--memory-divider)/0.2)]';

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

export const L0Tab: React.FC<L0TabProps> = ({
  stats,
  sessions,
  workbench,
  selectedSessionId,
  onSelectSession,
}) => {
  const { t } = useTranslation('app');

  const selectedSession =
    sessions.find((session) => session.session_id === selectedSessionId) ??
    (workbench?.session as L0Session | null) ??
    null;
  const goalStack = Array.isArray(workbench?.goal_stack) ? workbench.goal_stack : [];
  const activeEntities = Array.isArray(workbench?.active_entities) ? workbench.active_entities : [];
  const temporaryTactics = Array.isArray(workbench?.temporary_tactics) ? workbench.temporary_tactics : [];
  const contextUsage = workbench?.context_usage ?? null;
  const hasWorkbenchContent =
    goalStack.length > 0 || activeEntities.length > 0 || temporaryTactics.length > 0;

  return (
    <div className="space-y-4">
      <section className={PANEL_CLASS}>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-[hsl(var(--memory-body))]">
          <span>{stats.active_sessions} {t('memory.l0.activeSessions')}</span>
          <span>{stats.total_goals} {t('memory.l0.totalGoals')}</span>
          <span>{stats.total_entities} {t('memory.l0.totalEntities')}</span>
          <span>{stats.total_tactics} {t('memory.l0.totalTactics')}</span>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(260px,0.84fr)_minmax(0,1.16fr)]">
        <section className={PANEL_CLASS}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{t('memory.l0.sessions')}</h2>
            <span className="text-xs text-[hsl(var(--memory-muted))]">{sessions.length}</span>
          </div>

          {sessions.length === 0 ? (
            <div className={`mt-3 ${EMPTY_PANEL_CLASS}`}>
              {t('memory.l0.noSessions')}
            </div>
          ) : (
            <div className="mt-3 divide-y divide-[hsl(var(--memory-divider)/0.56)]">
              {sessions.map((session) => {
                const isSelected = selectedSessionId === session.session_id;
                return (
                  <button
                    key={session.session_id}
                    type="button"
                    className={cn(
                      'flex w-full flex-col items-start gap-1 px-0 py-3 text-left transition-colors',
                      isSelected
                        ? 'text-[hsl(var(--memory-title))]'
                        : 'text-[hsl(var(--memory-body))] hover:text-[hsl(var(--memory-title))]'
                    )}
                    onClick={() => onSelectSession(session.session_id)}
                  >
                    <div className="flex w-full items-center justify-between gap-3">
                      <span className="truncate text-sm font-medium">{getL0SessionPrimaryLabel(session)}</span>
                      <span className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                        {session.status}
                      </span>
                    </div>
                    {getL0SessionSecondaryLabel(session) ? (
                      <div className="truncate text-xs text-[hsl(var(--memory-muted))]">
                        {getL0SessionSecondaryLabel(session)}
                      </div>
                    ) : null}
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
                      <span>{t('memory.l0.totalGoals')}: {session.goal_count}</span>
                      <span>{t('memory.l0.totalEntities')}: {session.entity_count}</span>
                      <span>{t('memory.l0.totalTactics')}: {session.tactic_count}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section className={PANEL_CLASS}>
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{t('memory.l0.workbench')}</h2>

          {!selectedSessionId ? (
            <div className={`mt-3 ${EMPTY_PANEL_CLASS}`}>
              {t('memory.pages.workbench.focusEmpty')}
            </div>
          ) : (
            <div className="mt-3 space-y-4">
              {selectedSession ? (
                <div className="rounded-lg border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.74)] px-3 py-3">
                  <div className="text-sm font-medium text-[hsl(var(--memory-title))]">
                    {getL0SessionPrimaryLabel(selectedSession)}
                  </div>
                  {getL0SessionSecondaryLabel(selectedSession) ? (
                    <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                      {getL0SessionSecondaryLabel(selectedSession)}
                    </div>
                  ) : null}
                  <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                    {selectedSession.status} · {t('memory.l0.totalGoals')}: {selectedSession.goal_count} · {t('memory.l0.totalEntities')}: {selectedSession.entity_count} · {t('memory.l0.totalTactics')}: {selectedSession.tactic_count}
                  </div>
                </div>
              ) : null}

              <section className="space-y-2 border-t border-[hsl(var(--memory-divider)/0.56)] pt-4">
                <div className="text-sm font-medium text-[hsl(var(--memory-title))]">
                  {t('memory.pages.workbench.contextUsageTitle')}
                </div>
                {contextUsage ? (
                  <div className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] px-3 py-3 text-sm text-[hsl(var(--memory-body))]">
                    <div className="font-medium tabular-nums">
                      {t('memory.pages.workbench.contextUsageValue', {
                        used: contextUsage.used_tokens.toLocaleString(),
                        window: contextUsage.window_size.toLocaleString(),
                      })}
                    </div>
                    <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                      {t('memory.pages.workbench.contextUsageThreshold', {
                        threshold: contextUsage.threshold.toLocaleString(),
                      })}
                    </div>
                    {contextUsage.updated_at_ms > 0 ? (
                      <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                        {t('memory.pages.workbench.contextUsageUpdated', {
                          time: new Date(contextUsage.updated_at_ms).toLocaleString(),
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="text-sm text-[hsl(var(--memory-muted))]">
                    {t('memory.pages.workbench.contextUsageEmpty')}
                  </div>
                )}
              </section>

              {!hasWorkbenchContent ? (
                <div className={EMPTY_PANEL_CLASS}>
                  {t('memory.pages.workbench.shellEmpty')}
                </div>
              ) : null}

              <div className="space-y-4">
                <section className="space-y-2 border-t border-[hsl(var(--memory-divider)/0.56)] pt-4">
                  <div className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.l0.goalStack')}</div>
                  {goalStack.length > 0 ? (
                    <div className="space-y-2">
                      {goalStack.map((goal, index) => {
                        const item = goal as Record<string, unknown>;
                        const label =
                          (typeof item.description === 'string' && item.description) ||
                          (typeof item.goal_id === 'string' && item.goal_id) ||
                          `Goal ${index + 1}`;
                        return (
                          <div
                            key={String(item.goal_id ?? index)}
                            className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] px-3 py-2 text-sm text-[hsl(var(--memory-body))]"
                          >
                            {label}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l0.noGoals')}</div>
                  )}
                </section>

                <section className="space-y-2 border-t border-[hsl(var(--memory-divider)/0.56)] pt-4">
                  <div className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.l0.activeEntities')}</div>
                  {activeEntities.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {activeEntities.map((entity, index) => {
                        const item = entity as Record<string, unknown>;
                        return (
                          <div
                            key={String(item.entity_id ?? index)}
                            className="rounded-sm border border-[hsl(var(--memory-border)/0.48)] px-2.5 py-1 text-xs text-[hsl(var(--memory-body))]"
                          >
                            {getEntityLabel(item)}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l0.noEntities')}</div>
                  )}
                </section>

                <section className="space-y-2 border-t border-[hsl(var(--memory-divider)/0.56)] pt-4">
                  <div className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.l0.tactics')}</div>
                  {temporaryTactics.length > 0 ? (
                    <div className="space-y-2">
                      {temporaryTactics.map((tactic, index) => {
                        const item = tactic as Record<string, unknown>;
                        return (
                          <div
                            key={String(item.tactic_id ?? index)}
                            className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] px-3 py-2 text-sm text-[hsl(var(--memory-body))]"
                          >
                            {getTacticLabel(item)}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l0.noTactics')}</div>
                  )}
                </section>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default L0Tab;
