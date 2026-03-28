/**
 * L1Tab - L1 Event Memory tab component
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { L1Event, MemoryStatistics } from '@/api/modules/memory';
import { formatTimestamp } from '@/hooks/useMemory';

interface L1TabProps {
  stats: MemoryStatistics['l1'];
  events: L1Event[];
  showStats?: boolean;
  formatSourceLabel?: (source: string) => string;
}

export const L1Tab: React.FC<L1TabProps> = ({ stats, events, showStats = true, formatSourceLabel }) => {
  const { t } = useTranslation('app');

  const userAuthoredCount = events.filter((event) => event.author_type === 'user').length;
  const interactionCount = events.length - userAuthoredCount;

  return (
    <div className="space-y-4">
      {showStats ? (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
            <div className="text-2xl font-bold">{stats.event_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.totalEvents')}</div>
          </div>
          <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
            <div className="text-2xl font-bold">{userAuthoredCount}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.userAuthored')}</div>
          </div>
          <div className="rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
            <div className="text-2xl font-bold">{interactionCount}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.interaction')}</div>
          </div>
        </div>
      ) : null}

      <section className="border-t border-[hsl(var(--memory-divider)/0.72)] pt-4">
        <div className="mb-4 flex items-center gap-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-[hsl(var(--memory-title))]">
            <FileText className="h-5 w-5" />
            {t('memory.l1.events')}
          </h2>
        </div>
        <div>
          {events.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l1.noEvents')}
            </div>
          ) : (
            <div className="max-h-96 divide-y divide-[hsl(var(--memory-divider)/0.72)] overflow-y-auto">
              {events.map((event) => (
                <article key={event.event_id} className="py-4 first:pt-0 last:pb-0">
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <Badge variant="outline">{event.event_type}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatTimestamp(event.timestamp)}
                    </span>
                  </div>
                  <div className="text-sm leading-6 text-[hsl(var(--memory-title))]">{event.content}</div>
                  {event.user_id ? (
                    <div className="mt-2 font-mono text-xs text-muted-foreground">{event.user_id}</div>
                  ) : null}
                  {(event.id || event.source_item_id || event.idempotency_key) ? (
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted-foreground">
                      {event.id ? (
                        <span>{t('memory.l1.internalId')} #{event.id}</span>
                      ) : null}
                      {event.source_item_id ? (
                        <span className="break-all">{t('memory.l1.sourceItemId')} {event.source_item_id}</span>
                      ) : null}
                      {event.idempotency_key ? (
                        <span className="break-all">{t('memory.l1.idempotencyKey')} {event.idempotency_key}</span>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="mt-2 text-xs text-muted-foreground">
                    {[
                      event.source ? (formatSourceLabel ? formatSourceLabel(event.source) : event.source) : null,
                      event.memory_domain,
                      event.author_type,
                      event.content_type,
                    ].filter(Boolean).join(' · ')}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default L1Tab;
