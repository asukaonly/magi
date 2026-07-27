import React from 'react';
import { useTranslation } from 'react-i18next';

import {
  getL0SessionPrimaryLabel,
  getL0SessionSecondaryLabel,
  type L0AttentionItem,
  type L0Session,
  type L0Workbench,
  type MemoryStatistics,
} from '@/api/modules/memory';
import { cn } from '@/lib/utils';

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

const statusClassName = (status: L0AttentionItem['status']): string => {
  switch (status) {
    case 'active':
      return 'bg-primary/10 text-primary';
    case 'background':
      return 'bg-muted text-muted-foreground';
    case 'resolved':
      return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
    case 'superseded':
      return 'bg-amber-500/10 text-amber-700 dark:text-amber-300';
  }
};

const formatScore = (value: number): string =>
  `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;

const formatTimestamp = (value: number | null): string | null => {
  if (value === null || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return new Date(value * 1000).toLocaleString();
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
    sessions.find((session) => session.session_id === selectedSessionId)
    ?? (workbench?.session as L0Session | null)
    ?? null;
  const attentionItems = Array.isArray(workbench?.attention_items)
    ? workbench.attention_items
    : [];
  const contextUsage = workbench?.context_usage ?? null;

  return (
    <div className="space-y-4">
      <section className={PANEL_CLASS}>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-[hsl(var(--memory-body))]">
          <span>{stats.active_sessions} {t('memory.l0.activeSessions')}</span>
          <span>{stats.total_attention_items} {t('memory.l0.totalAttentionItems')}</span>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(260px,0.84fr)_minmax(0,1.16fr)]">
        <section className={PANEL_CLASS}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
              {t('memory.l0.sessions')}
            </h2>
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
                      <span className="truncate text-sm font-medium">
                        {getL0SessionPrimaryLabel(session)}
                      </span>
                      <span className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--memory-muted))]">
                        {session.status}
                      </span>
                    </div>
                    {getL0SessionSecondaryLabel(session) ? (
                      <div className="truncate text-xs text-[hsl(var(--memory-muted))]">
                        {getL0SessionSecondaryLabel(session)}
                      </div>
                    ) : null}
                    <div className="text-xs text-[hsl(var(--memory-muted))]">
                      {t('memory.l0.attentionCount', { count: session.attention_count })}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section className={PANEL_CLASS}>
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.l0.workbench')}
          </h2>

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
                    {selectedSession.status} · {t('memory.l0.workbenchItemCount', {
                      count: attentionItems.length,
                    })}
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

              <section className="space-y-2 border-t border-[hsl(var(--memory-divider)/0.56)] pt-4">
                <div className="text-sm font-medium text-[hsl(var(--memory-title))]">
                  {t('memory.l0.attentionItems')}
                </div>
                {attentionItems.length === 0 ? (
                  <div className={EMPTY_PANEL_CLASS}>
                    {t('memory.pages.workbench.shellEmpty')}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {attentionItems.map((item) => {
                      const reinforcedAt = formatTimestamp(item.last_reinforced_at);
                      const expiresAt = formatTimestamp(item.expires_at);
                      return (
                        <article
                          key={item.item_id}
                          className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] px-3 py-3"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs font-semibold text-[hsl(var(--memory-title))]">
                              {t(`memory.l0.kinds.${item.kind}`)}
                            </span>
                            <span className={cn(
                              'rounded-full px-2 py-0.5 text-[11px] font-medium',
                              statusClassName(item.status)
                            )}>
                              {t(`memory.l0.statuses.${item.status}`)}
                            </span>
                            <span className={cn(
                              'rounded-full px-2 py-0.5 text-[11px] font-medium',
                              item.evidence_mode === 'direct'
                                ? 'bg-sky-500/10 text-sky-700 dark:text-sky-300'
                                : 'bg-violet-500/10 text-violet-700 dark:text-violet-300'
                            )}>
                              {t(`memory.l0.evidenceModes.${item.evidence_mode}`)}
                            </span>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
                            {item.summary}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
                            <span>{t('memory.l0.salience')}: {formatScore(item.salience)}</span>
                            <span>{t('memory.l0.confidence')}: {formatScore(item.confidence)}</span>
                            {reinforcedAt ? (
                              <span>{t('memory.l0.lastReinforced')}: {reinforcedAt}</span>
                            ) : null}
                            {expiresAt ? (
                              <span>{t('memory.l0.expiresAt')}: {expiresAt}</span>
                            ) : null}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default L0Tab;
