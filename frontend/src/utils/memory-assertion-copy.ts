import type { L2Assertion, L2PendingReview } from '@/api/modules/memory';

export type MemoryAssertionTranslateFn = (key: string, options?: Record<string, unknown>) => string;

export interface MemoryFactDisplay {
  display_text?: string | null;
  natural_summary?: string | null;
}

export interface PendingAssertionCopy {
  title: string;
  body: string;
}

// Fact semantics and entity resolution belong to the host read model.
export const getAssertionDisplayText = (
  fact: MemoryFactDisplay,
  t: MemoryAssertionTranslateFn,
): string => fact.display_text?.trim() || fact.natural_summary?.trim()
  || t('memory.facts.unavailable', { defaultValue: '完整事实暂不可用' });

const translatedLabel = (t: MemoryAssertionTranslateFn, key: string): string | null => {
  const value = t(key);
  return value && value !== key ? value : null;
};

export const getAssertionTraitLabel = (
  assertion: { trait_name?: string | null; trait_family?: string | null },
  t: MemoryAssertionTranslateFn,
): string => {
  const trait = (assertion.trait_name || '').replace(/[^a-zA-Z0-9]+/g, '_').toLowerCase();
  const family = assertion.trait_family || '';
  const prefix = assertion.trait_name?.split('.')[0] || '';
  return translatedLabel(t, `memory.pages.knowledge.traitLabels.${trait}`)
    || translatedLabel(t, `memory.facts.families.${family}`)
    || translatedLabel(t, `memory.facts.families.${prefix}`)
    || t('memory.facts.unknownTrait', { defaultValue: '事实判断' });
};

export const getAssertionStatusLabel = (status: string, t: MemoryAssertionTranslateFn): string => {
  const keys: Record<string, string> = {
    tentative: 'needsReview', shadow: 'needsReview', pending: 'needsReview',
    pending_confirmation: 'needsReview', contradicted: 'conflicted', conflicted: 'conflicted',
    active: 'active', stable: 'stable', corroborated: 'corroborated', verified: 'corroborated',
    valid: 'valid', superseded: 'superseded', expired: 'expired', archived: 'archived',
    invalidated: 'invalidated', user_rejected: 'userRejected', rejected: 'userRejected',
  };
  return t(`memory.governance.statuses.${keys[status.toLowerCase()] || 'unknown'}`);
};

export const getPendingAssertionCopy = (
  assertion: L2Assertion,
  t: MemoryAssertionTranslateFn,
): PendingAssertionCopy => {
  const value = getAssertionDisplayText(assertion, t);
  const context = assertion.conflict_context;
  const oldValue = context?.previous_display_text?.trim();
  const newValue = context?.current_display_text?.trim();
  if (oldValue && newValue && oldValue !== newValue) {
    return {
      title: t('memory.pending.assertions.conflictPairTitle', { oldValue, newValue }),
      body: t('memory.pending.assertions.conflictPairBody', { oldValue, newValue }),
    };
  }
  const state = assertion.status || assertion.validation_state;
  return {
    title: value,
    body: state === 'contradicted'
      ? t('memory.pending.assertions.uncertainBody')
      : t('memory.pending.assertions.tentativeBody'),
  };
};

export const getPendingReviewCopy = (
  review: L2PendingReview,
  t: MemoryAssertionTranslateFn,
): PendingAssertionCopy => ({
  title: getAssertionDisplayText(review.proposed, t),
  body: t('memory.pending.reviews.body'),
});

export const getAssertionEvidenceBasis = (assertion: Pick<L2Assertion, 'user_feedback' | 'inference_depth'>): string => {
  if (assertion.user_feedback === 'confirmed') return 'user_confirmed';
  if (['direct', 'explicit'].includes(assertion.inference_depth)) return 'direct_report';
  return assertion.inference_depth ? 'inferred' : 'unknown';
};
