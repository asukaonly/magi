import React, { useState } from 'react';
import { Check, Pencil, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { L1Event } from '@/api/modules/memory';
import {
  coerceKnowledgeEventIds,
  formatConfidence,
  formatEventTime,
  translateWithFallback,
  type KnowledgeCorrectionAction,
  type KnowledgeDetailRow,
  type KnowledgeItem,
  type MemoryTranslateFn,
} from '../l2KnowledgeModel';

export const KnowledgeItemRow: React.FC<{
  item: KnowledgeItem;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}> = ({ item, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onRequestAssertionCorrection, t }) => {
  const [isOpen, setIsOpen] = useState(false);
  const confidence = formatConfidence(item.confidence);
  const metaItems = [
    item.kindLabel,
    item.statusGroup === 'active' ? null : item.statusLabel,
    confidence ? translateWithFallback(
      t,
      'memory.pages.knowledge.readable.confidenceSummary',
      '{{confidence}} confidence',
      { confidence }
    ) : null,
    typeof item.evidenceCount === 'number' ? translateWithFallback(
      t,
      'memory.pages.knowledge.readable.evidenceSummary',
      '{{count}} evidence item(s)',
      { count: item.evidenceCount }
    ) : null,
  ].filter(Boolean).join(' · ');
  const evidenceIds = coerceKnowledgeEventIds(item.evidenceIds).slice(0, 8);
  const isReviewableAssertion = Boolean(
    item.assertionId &&
    (item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted')
  );
  const canConfirm = Boolean(isReviewableAssertion && onSubmitAssertionFeedback);
  const canCorrect = Boolean(
    isReviewableAssertion &&
    onRequestAssertionCorrection &&
    item.correctionValue !== undefined
  );
  const technicalRows = [
    ...(item.technicalRows ?? []),
    item.updatedAt ? { label: t('memory.pages.knowledge.fields.updatedAt'), value: formatEventTime(item.updatedAt) } : null,
  ].filter((row): row is KnowledgeDetailRow => Boolean(row));
  const handleFeedback = (
    event: React.MouseEvent<HTMLButtonElement>,
    feedback: 'confirmed'
  ) => {
    event.preventDefault();
    event.stopPropagation();
    if (item.assertionId && onSubmitAssertionFeedback) {
      void onSubmitAssertionFeedback(item.assertionId, feedback);
    }
  };
  const handleRequestCorrection = (
    event: React.MouseEvent<HTMLButtonElement>,
    action: KnowledgeCorrectionAction
  ) => {
    event.preventDefault();
    event.stopPropagation();
    onRequestAssertionCorrection?.(item, action);
  };

  return (
    <details
      className="group"
      open={isOpen}
      onToggle={(event) => {
        const nextOpen = event.currentTarget.open;
        setIsOpen(nextOpen);
        if (nextOpen && evidenceIds.length > 0) {
          void onLoadEvidenceEvents(evidenceIds);
        }
      }}
    >
      <summary className="cursor-pointer list-none px-4 py-3 transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.38)] [&::-webkit-details-marker]:hidden">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
          <div className="min-w-0">
            <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">{metaItems}</div>
            <div className="mt-1 break-words text-sm font-medium leading-6 text-[hsl(var(--memory-title))]">{item.title}</div>
            {item.body ? <div className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{item.body}</div> : null}
          </div>
          {canConfirm || canCorrect ? (
            <div className="flex shrink-0 justify-end gap-2">
              {canConfirm ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-sm"
                  disabled={actionLoading || item.userFeedback === 'confirmed'}
                  onClick={(event) => handleFeedback(event, 'confirmed')}
                >
                  <Check className="mr-2 h-4 w-4" />
                  {t('memory.l2.confirmAssertion')}
                </Button>
              ) : null}
              {canCorrect ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-sm"
                    disabled={actionLoading}
                    onClick={(event) => handleRequestCorrection(event, 'remove')}
                  >
                    <X className="mr-2 h-4 w-4" />
                    {t('memory.l2.rejectAssertion')}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-sm"
                    disabled={actionLoading}
                    onClick={(event) => handleRequestCorrection(event, 'replace')}
                  >
                    <Pencil className="mr-2 h-4 w-4" />
                    {t('memory.l2.correctAssertion')}
                  </Button>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      </summary>
      <div className="border-t border-[hsl(var(--memory-divider)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.36)] px-4 py-3">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {item.detailRows.map((row) => (
            <KnowledgeDetailField key={`${item.id}-${row.label}`} label={row.label} value={row.value} />
          ))}
        </div>
        {evidenceIds.length > 0 ? (
          <EvidenceEventList
            itemId={item.id}
            eventIds={evidenceIds}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            t={t}
          />
        ) : null}
        {technicalRows.length > 0 || evidenceIds.length > 0 ? (
          <details className="mt-3 rounded-sm border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel)/0.52)] px-3 py-2">
            <summary className="cursor-pointer text-xs text-[hsl(var(--memory-muted))]">
              {t('memory.pages.knowledge.sections.technicalDetails')}
            </summary>
            <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {technicalRows.map((row) => (
                <KnowledgeDetailField key={`${item.id}-technical-${row.label}`} label={row.label} value={row.value} />
              ))}
            </div>
            {evidenceIds.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {evidenceIds.map((eventId) => (
                  <span key={`${item.id}-${eventId}`} className="rounded-sm bg-[hsl(var(--memory-panel-subtle)/0.74)] px-2 py-1 font-mono text-[11px] text-[hsl(var(--memory-body))]">
                    {eventId}
                  </span>
                ))}
              </div>
            ) : null}
          </details>
        ) : null}
      </div>
    </details>
  );
};

const EvidenceEventList: React.FC<{
  itemId: string;
  eventIds: string[];
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  t: MemoryTranslateFn;
}> = ({ itemId, eventIds, evidenceEventsById, loadingEvidenceIds, t }) => (
  <section className="mt-3 rounded-sm border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel)/0.62)] px-3 py-3">
    <div className="text-xs font-medium text-[hsl(var(--memory-muted))]">{t('memory.pages.knowledge.sections.evidenceEvents')}</div>
    <div className="mt-2 space-y-2">
      {eventIds.map((eventId) => {
        const event = evidenceEventsById.get(eventId);
        const isLoading = loadingEvidenceIds[eventId];
        return (
          <details key={`${itemId}-evidence-${eventId}`} className="rounded-sm border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.58)] px-3 py-2" open={Boolean(event)}>
            <summary className="cursor-pointer text-sm font-medium text-[hsl(var(--memory-title))]">
              {event ? [event.event_type, event.source, formatEventTime(event.timestamp)].filter(Boolean).join(' · ') : eventId}
            </summary>
            {event ? (
              <div className="mt-2 space-y-2">
                <div className="whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">{event.content}</div>
                <div className="text-xs text-[hsl(var(--memory-muted))]">
                  {[event.author_type, event.content_type, event.memory_domain].filter(Boolean).join(' · ')}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-sm text-[hsl(var(--memory-muted))]">
                {isLoading ? t('memory.pages.knowledge.evidenceLoading') : t('memory.pages.knowledge.evidenceMissing')}
              </div>
            )}
          </details>
        );
      })}
    </div>
  </section>
);

const KnowledgeDetailField: React.FC<{ label: string; value: string | number | null | undefined }> = ({ label, value }) => {
  if (value === null || value === undefined || String(value).trim().length === 0) {
    return null;
  }

  return (
    <div className="rounded-sm border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel)/0.62)] px-3 py-2">
      <div className="text-xs text-[hsl(var(--memory-muted))]">{label}</div>
      <div className="mt-1 break-words text-sm text-[hsl(var(--memory-title))]">{String(value)}</div>
    </div>
  );
};
