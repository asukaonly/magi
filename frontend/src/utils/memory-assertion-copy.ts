import type { L2Assertion } from '@/api/modules/memory';

export type MemoryAssertionTranslateFn = (key: string, options?: Record<string, unknown>) => string;

export interface PendingAssertionCopy {
  title: string;
  body: string;
}

const CONTROLLED_VALUE_FAMILIES = new Set([
  'mood',
  'stress',
  'engagement',
  'group_atmosphere',
  'public_sentiment',
]);

const normalizeLabelKey = (value: string) => value
  .trim()
  .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
  .replace(/[^a-zA-Z0-9]+/g, '_')
  .replace(/^_+|_+$/g, '')
  .toLowerCase();

const humanizeToken = (value: string) => {
  const text = value.split(':').pop() || value;
  return text
    .replace(/[._-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

const translateOptional = (t: MemoryAssertionTranslateFn, key: string): string | null => {
  const translated = t(key);
  return translated === key ? null : translated;
};

const translateOptionalWithOptions = (
  t: MemoryAssertionTranslateFn,
  key: string,
  options: Record<string, unknown>,
): string | null => {
  const translated = t(key, options);
  return translated === key ? null : translated;
};

const assertionTitle = (assertion: L2Assertion): string => (
  String(assertion.trait_name || assertion.assertion_id || '').trim()
);

const assertionBody = (assertion: L2Assertion): string => (
  String(assertion.trait_value || '').trim()
);

const isInternalTraitName = (value: string): boolean => {
  const text = value.trim();
  if (!text) {
    return false;
  }
  return (
    text.startsWith('interest.')
    || /^[a-z0-9_-]+(\.[a-z0-9_-]+)+$/i.test(text)
    || /^[a-z][a-z0-9_]*$/i.test(text)
  );
};

const readableTraitName = (assertion: L2Assertion, displayedValue: string): string => {
  const traitName = assertionTitle(assertion);
  if (!traitName || traitName === displayedValue || traitName === assertion.assertion_id) {
    return '';
  }
  return isInternalTraitName(traitName) ? '' : traitName;
};

const assertionDisplayValue = (assertion: L2Assertion, t: MemoryAssertionTranslateFn): string => {
  const value = assertionBody(assertion);
  if (!value) {
    const title = assertionTitle(assertion);
    if (title && title !== assertion.assertion_id && !isInternalTraitName(title)) {
      return title;
    }
    return t('memory.pending.assertions.unknownValue');
  }

  const explicitMode = String(assertion.trait_value_i18n || '').trim();
  const familyKey = normalizeLabelKey(assertion.trait_family || '');
  const shouldTranslate = explicitMode === 'controlled' || (!explicitMode && CONTROLLED_VALUE_FAMILIES.has(familyKey));
  if (!shouldTranslate) {
    return value;
  }

  const valueKey = normalizeLabelKey(value);
  const traitKey = normalizeLabelKey(assertion.trait_name);
  return (
    (familyKey ? translateOptional(t, `memory.pages.knowledge.traitValues.${familyKey}.${valueKey}`) : null)
    || (traitKey ? translateOptional(t, `memory.pages.knowledge.traitValues.${traitKey}.${valueKey}`) : null)
    || translateOptional(t, `memory.pages.knowledge.traitValues.common.${valueKey}`)
    || value
  );
};

const readableAssertionTitle = (
  assertion: L2Assertion,
  value: string,
  t: MemoryAssertionTranslateFn,
): string | null => {
  const traitKey = normalizeLabelKey(assertion.trait_name);
  if (!traitKey) {
    return null;
  }
  const specific = translateOptionalWithOptions(
    t,
    `memory.pages.knowledge.readable.assertions.${traitKey}`,
    { value },
  );
  if (specific) {
    return specific;
  }
  const traitLabel = translateOptional(t, `memory.pages.knowledge.traitLabels.${traitKey}`);
  if (!traitLabel) {
    return null;
  }
  return t('memory.pages.knowledge.readable.assertion', {
    entity: t('memory.pages.knowledge.fields.self'),
    attribute: traitLabel || humanizeToken(assertion.trait_name),
    value,
  });
};

const readableConflictValue = (value: unknown): string => {
  const text = String(value || '').trim();
  return text && !isInternalTraitName(text) ? text : '';
};

export const getPendingAssertionCopy = (
  assertion: L2Assertion,
  t: MemoryAssertionTranslateFn,
): PendingAssertionCopy => {
  const value = assertionDisplayValue(assertion, t);
  const context = assertion.conflict_context;
  const oldValue = readableConflictValue(context?.previous_value) || value;
  const newValue = readableConflictValue(context?.current_value);
  if (newValue && oldValue !== newValue) {
    return {
      title: t('memory.pending.assertions.conflictPairTitle', { oldValue, newValue }),
      body: t('memory.pending.assertions.conflictPairBody', { oldValue, newValue }),
    };
  }

  const state = String(assertion.validation_state || assertion.status || '').trim().toLowerCase();
  if (state === 'contradicted') {
    return {
      title: t('memory.pending.assertions.uncertainTitle', { value }),
      body: t('memory.pending.assertions.uncertainBody'),
    };
  }

  if (assertion.inference_depth === 'topology_only') {
    return { title: t('memory.provenance.behavior_recent', { value }), body: t('memory.pending.assertions.tentativeBody') };
  }
  const readableTitle = readableAssertionTitle(assertion, value, t);
  if (readableTitle) {
    return {
      title: readableTitle,
      body: t('memory.pending.assertions.tentativeBody'),
    };
  }

  const traitName = readableTraitName(assertion, value);
  return {
    title: t('memory.pending.assertions.tentativeTitle', { value }),
    body: traitName
      ? t('memory.pending.assertions.traitBody', { trait: traitName })
      : t('memory.pending.assertions.tentativeBody'),
  };
};

export const getAssertionEvidenceBasis = (assertion: L2Assertion): string => {
  if (assertion.user_feedback === 'confirmed') return 'user_confirmed';
  if (['direct', 'explicit'].includes(assertion.inference_depth)) return 'direct_report';
  return assertion.inference_depth ? 'inferred' : 'unknown';
};
