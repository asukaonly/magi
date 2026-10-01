import { useState } from 'react';
import { ArrowRight, ChevronDown, Shapes } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { EntityTypeReview, EntityTypeReviewGroup } from '@/api/modules/entityIdentity';
import { Button } from '@/components/ui/button';
import { getEntityTypeLabel } from '@/utils/entity-types';
import { asEventHandler } from '@/utils/as-event-handler';
import { EntityEvidence } from './EntityEvidence';

interface Props {
  reviews: EntityTypeReviewGroup[];
  busy: boolean;
  onInspect: (review: EntityTypeReview) => void;
  onReject: (group: EntityTypeReviewGroup) => Promise<void>;
}

export function EntityTypeReviewCards({ reviews, ...actions }: Props) {
  const { t } = useTranslation('app');
  if (!reviews.length) return null;
  return <section aria-label={t('memory.identity.reviewTitle')}>
    <h2 className="mb-3 text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.identity.reviewTitle')}</h2>
    <div className="space-y-3">
      {reviews.map((group) => <EntityReviewRow key={group.entity.entity_id} group={group}
        namesake={reviews.filter((item) => item.entity.canonical_name === group.entity.canonical_name).length > 1}
        {...actions} />)}
    </div>
  </section>;
}

function EntityReviewRow({ group, namesake, busy, onInspect, onReject }: Omit<Props, 'reviews'> & { group: EntityTypeReviewGroup; namesake: boolean }) {
  const { t } = useTranslation('app');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const selected = group.proposals.find((proposal) => proposal.review_id === selectedId)
    ?? (group.proposals.length === 1 ? group.proposals[0] : undefined);
  const eventIds = [...new Set(group.proposals.flatMap((proposal) => proposal.evidence_event_ids))];
  const currentType = getEntityTypeLabel(group.entity.entity_type, t);
  return <article className="rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.68)] p-5 sm:p-6">
    <div className="flex items-start gap-3 sm:gap-4">
      <Shapes className="mt-1 h-5 w-5 shrink-0 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="break-words text-base font-semibold text-[hsl(var(--memory-title))]">{group.entity.canonical_name}</h3>
          {namesake ? <span className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.identity.namesake')}</span> : null}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
          <span className="text-[hsl(var(--memory-muted))]">{t('memory.identity.currentType', { type: currentType })}</span>
          <ArrowRight className="h-3.5 w-3.5 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
          {group.proposals.length === 1 ? <span className="font-medium text-[hsl(var(--memory-title))]">{t('memory.identity.suggestedType', { type: getEntityTypeLabel(group.proposals[0].proposed_type, t) })}</span> :
            <fieldset className="flex flex-wrap gap-2">
              <legend className="sr-only">{t('memory.identity.chooseType')}</legend>
              {group.proposals.map((proposal) => <label key={proposal.review_id} className="flex cursor-pointer items-center gap-2 rounded-md bg-[hsl(var(--memory-panel-subtle)/0.7)] px-3 py-2">
                <input type="radio" name={`type-${group.entity.entity_id}`} checked={selected?.review_id === proposal.review_id}
                  disabled={busy} onChange={() => setSelectedId(proposal.review_id)} className="accent-[hsl(var(--memory-accent))]" />
                {getEntityTypeLabel(proposal.proposed_type, t)}
              </label>)}
            </fieldset>}
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <button type="button" className="inline-flex items-center gap-1.5 rounded text-xs text-[hsl(var(--memory-muted))] hover:text-[hsl(var(--memory-title))] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
            aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen(!evidenceOpen)}>
            {t('memory.identity.evidence', { count: eventIds.length })}
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${evidenceOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" disabled={busy} onClick={asEventHandler(() => onReject(group))}>{t('memory.identity.keepNamedType', { type: currentType })}</Button>
            <Button variant="outline" size="sm" disabled={busy || !selected} onClick={() => { if (selected) onInspect(selected); }}>
              {selected ? t('memory.identity.acceptNamedType', { type: getEntityTypeLabel(selected.proposed_type, t) }) : t('memory.identity.chooseType')}
            </Button>
          </div>
        </div>
        {evidenceOpen ? <div className="mt-5 rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.5)] p-4"><EntityEvidence eventIds={eventIds} /></div> : null}
      </div>
    </div>
  </article>;
}
