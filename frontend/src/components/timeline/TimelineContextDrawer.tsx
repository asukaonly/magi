import React from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { TimelineContextBundle } from '@/api/modules/timeline';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

interface TimelineContextDrawerProps {
  selectedAnchorId: string | null;
  loading: boolean;
  contextBundle: TimelineContextBundle | null;
  onClose?: () => void;
}

const stringValue = (record: Record<string, unknown>, keys: string[], fallback = ''): string => {
  for (const key of keys) {
    const value = record[key];
    if (value != null && String(value).trim()) {
      return String(value);
    }
  }
  return fallback;
};

const formatTimestamp = (value: unknown): string | null => {
  if (value == null || value === '') return null;
  const numeric = typeof value === 'number' ? value * 1000 : Number(value) * 1000;
  const timestamp = Number.isFinite(numeric) ? numeric : Date.parse(String(value));
  if (!Number.isFinite(timestamp)) return null;
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(timestamp));
};

const EvidenceSection: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section className="space-y-2">
    <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
    {children}
  </section>
);

export const TimelineContextDrawer: React.FC<TimelineContextDrawerProps> = ({
  selectedAnchorId,
  loading,
  contextBundle,
  onClose,
}) => {
  const { t } = useTranslation('app');

  return (
    <aside className="min-h-0 border-t border-border/60 xl:border-l xl:border-t-0">
      <div className="h-full overflow-y-auto px-5 py-5">
        {selectedAnchorId == null ? (
          <p className="py-8 text-center text-sm text-muted-foreground/60">
            {t('timeline.drawer.empty')}
          </p>
        ) : loading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <LoadingSpinner className="h-4 w-4" />
            {t('timeline.feed.loadingDetails')}
          </div>
        ) : contextBundle ? (
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold text-foreground">{contextBundle.anchor.title}</h2>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                  {contextBundle.anchor.summary}
                </p>
              </div>
              {onClose && (
                <button onClick={onClose} className="shrink-0 text-muted-foreground/50 hover:text-foreground">
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {(contextBundle.l3_reflections || []).length > 0 && (
              <EvidenceSection title={t('timeline.drawer.reflections')}>
                {contextBundle.l3_reflections.map((reflection, i) => (
                  <div
                    key={`${(reflection as Record<string, unknown>).summary_id || i}`}
                    className="rounded-md bg-muted/40 px-3 py-2.5 text-sm text-muted-foreground"
                  >
                    {String((reflection as Record<string, unknown>).content || (reflection as Record<string, unknown>).summary || '')}
                  </div>
                ))}
              </EvidenceSection>
            )}

            {(contextBundle.l1_events || []).length > 0 && (
              <EvidenceSection title={t('timeline.drawer.sourceEvidence')}>
                <div className="space-y-2">
                  {contextBundle.l1_events.slice(0, 8).map((event, i) => {
                    const record = event as Record<string, unknown>;
                    const title = stringValue(record, ['title', 'event_type', 'event_id'], t('timeline.drawer.untitledEvent'));
                    const summary = stringValue(record, ['summary', 'content']);
                    const source = stringValue(record, ['source_type', 'source'], 'memory');
                    const timestamp = formatTimestamp(record.timestamp || record.occurred_at || record.created_at);
                    return (
                      <div key={`${record.event_id || i}`} className="rounded-md border border-border/35 px-3 py-2.5">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-sm font-medium text-foreground">{title}</span>
                          {timestamp ? <span className="shrink-0 text-[11px] text-muted-foreground/60">{timestamp}</span> : null}
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground/60">
                          {t(`timeline.sources.${source}`, source)}
                        </div>
                        {summary ? <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">{summary}</p> : null}
                      </div>
                    );
                  })}
                </div>
              </EvidenceSection>
            )}

            {(contextBundle.l2_state_evidence || []).length > 0 && (
              <EvidenceSection title={t('timeline.drawer.derivedEvidence')}>
                <div className="space-y-1.5">
                  {contextBundle.l2_state_evidence.slice(0, 8).map((item, i) => {
                    const record = item as Record<string, unknown>;
                    const label = stringValue(record, ['trait_name', 'predicate', 'relation_type'], t('timeline.drawer.evidenceItem'));
                    const value = stringValue(record, ['trait_value', 'object_id', 'object_label', 'summary']);
                    return (
                      <div key={`${record.assertion_id || record.triple_id || i}`} className="text-sm text-muted-foreground">
                        <span className="font-medium text-foreground">{label.replace(/[_-]+/g, ' ')}</span>
                        {value ? <span className="ml-1.5">{value}</span> : null}
                      </div>
                    );
                  })}
                </div>
              </EvidenceSection>
            )}

            {(contextBundle.l4_related_procedures || []).length > 0 && (
              <EvidenceSection title={t('timeline.drawer.procedures')}>
                {contextBundle.l4_related_procedures.map((proc, i) => (
                  <div
                    key={`${(proc as Record<string, unknown>).skill_id || i}`}
                    className="text-sm text-foreground"
                  >
                    {String((proc as Record<string, unknown>).skill_name || '')}
                  </div>
                ))}
              </EvidenceSection>
            )}

            {(contextBundle.chat_excerpts || []).length > 0 && (
              <EvidenceSection title={t('timeline.drawer.relatedChat')}>
                <div className="space-y-2">
                  {contextBundle.chat_excerpts.slice(0, 5).map((excerpt, i) => (
                    <div
                      key={`${(excerpt as Record<string, unknown>).event_id || i}`}
                      className="rounded-md bg-muted/35 px-3 py-2.5 text-sm text-muted-foreground"
                    >
                      {String((excerpt as Record<string, unknown>).content || '')}
                    </div>
                  ))}
                </div>
              </EvidenceSection>
            )}

            {(contextBundle.l1_events || []).length === 0
              && (contextBundle.l2_state_evidence || []).length === 0
              && (contextBundle.l3_reflections || []).length === 0
              && (contextBundle.chat_excerpts || []).length === 0 ? (
                <div className="rounded-md border border-dashed border-border/60 px-3 py-4 text-sm text-muted-foreground">
                  {t('timeline.drawer.noEvidence')}
                </div>
              ) : null}
          </div>
        ) : null}
      </div>
    </aside>
  );
};

export default TimelineContextDrawer;
