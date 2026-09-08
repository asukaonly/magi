import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { EntityTypeReview } from '@/api/modules/entityIdentity';
import { Button } from '@/components/ui/button';
import { getEntityTypeLabel } from '@/utils/entity-types';
import { asEventHandler } from '@/utils/as-event-handler';
import { EntityEvidence } from './EntityEvidence';

export function EntityTypeReviewCards({ reviews, busy, onInspect, onReject }: {
  reviews: EntityTypeReview[];
  busy: boolean;
  onInspect: (review: EntityTypeReview) => void;
  onReject: (review: EntityTypeReview) => Promise<void>;
}) {
  const { t } = useTranslation('app');
  if (!reviews.length) return null;
  return <section className="space-y-4">
    <h2 className="font-medium">{t('memory.identity.reviewTitle')}</h2>
    {reviews.map((review) => <article key={review.review_id} className="space-y-3 rounded-xl border p-4">
      <p>{t('memory.identity.typePreview', { name: review.entity.canonical_name, from: getEntityTypeLabel(review.entity.entity_type, t), to: getEntityTypeLabel(review.proposed_type, t) })}</p>
      <ReviewEvidence eventIds={review.evidence_event_ids} />
      <div className="flex gap-2"><Button disabled={busy} onClick={() => onInspect(review)}>{t('memory.identity.preview')}</Button><Button variant="outline" disabled={busy} onClick={asEventHandler(() => onReject(review))}>{t('memory.identity.keepType')}</Button></div>
    </article>)}
  </section>;
}

function ReviewEvidence({ eventIds }: { eventIds: string[] }) {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(false);
  return <details onToggle={(event) => setOpen(event.currentTarget.open)}><summary className="cursor-pointer">{t('memory.identity.evidence', { count: eventIds.length })}</summary>{open ? <EntityEvidence eventIds={eventIds} /> : null}</details>;
}
