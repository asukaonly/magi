import { DEFAULT_USER_ID } from '@/constants';
import type {
  L2Assertion,
  L2Entity,
  L2Snapshot,
  MemoryIdentityLink,
} from '@/api/modules/memory';
import type { MemoryTranslateFn } from './l2KnowledgeTypes';

const ASSERTION_FAMILY_VALUE_I18N: Record<string, 'literal' | 'controlled'> = {
  stress: 'controlled',
  mood: 'controlled',
  engagement: 'controlled',
  group_atmosphere: 'controlled',
  public_sentiment: 'controlled',
  state_profile: 'controlled',
  trigger: 'literal',
  relationship_shift: 'literal',
  identity_profile: 'literal',
  communication_profile: 'literal',
  preference_profile: 'literal',
  routine_profile: 'literal',
};

export const normalizeSearchText = (value: unknown) => String(value ?? '').trim().toLowerCase();

export const normalizeLabelKey = (value: string) => value
  .trim()
  .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
  .replace(/[^a-zA-Z0-9]+/g, '_')
  .replace(/^_+|_+$/g, '')
  .toLowerCase();

const collectEntityAliasCandidates = (value: string | null | undefined) => {
  const rawValue = String(value || '').trim().toLowerCase();
  if (!rawValue) {
    return [] as string[];
  }
  const variants = new Set<string>([rawValue]);
  const suffix = rawValue.includes(':') ? rawValue.split(':').pop() : null;
  if (suffix) {
    variants.add(suffix);
  }
  return Array.from(variants)
    .map((item) => item.replace(/[^\p{L}\p{N}]+/gu, ''))
    .filter(Boolean);
};

export const buildSelfEntityAliasSet = (
  canonicalSelfId: string | null | undefined,
  identityLinks: MemoryIdentityLink[]
) => {
  const aliases = new Set<string>();
  const addAlias = (value: string | null | undefined) => {
    collectEntityAliasCandidates(value).forEach((candidate) => aliases.add(candidate));
  };

  addAlias('user:self');
  addAlias(`user:${DEFAULT_USER_ID}`);
  addAlias(DEFAULT_USER_ID);
  addAlias('local user');
  addAlias(canonicalSelfId);

  identityLinks.forEach((link) => {
    addAlias(link.memory_owner_id);
    addAlias(link.runtime_user_id);
    addAlias(`user:${link.runtime_user_id}`);
  });

  return aliases;
};

const humanizeToken = (value: string) => {
  const text = value.split(':').pop() || value;
  return text
    .replace(/[._-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

export const textIncludesAny = (value: string, terms: string[]) => terms.some((term) => value.includes(term));

export const coerceKnowledgeText = (value: unknown): string => {
  if (typeof value === 'string') {
    return value;
  }
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

export const coerceKnowledgeEventIds = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map((item) => coerceKnowledgeText(item).trim())
      .filter(Boolean);
  }
  if (typeof value !== 'string') {
    return [];
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (parsed !== value) {
      return coerceKnowledgeEventIds(parsed);
    }
  } catch {
    // Fall back to treating the raw string as a single event id.
  }

  return [trimmed];
};

const interpolateFallback = (template: string, options: Record<string, unknown> = {}) => template.replace(
  /\{\{\s*(\w+)\s*\}\}/g,
  (_match, key: string) => String(options[key] ?? '')
);

export const translateWithFallback = (
  t: MemoryTranslateFn,
  key: string,
  fallback: string,
  options: Record<string, unknown> = {}
) => {
  const translated = t(key, options);
  return translated === key ? interpolateFallback(fallback, options) : translated;
};

const translateOptional = (t: MemoryTranslateFn, key: string) => {
  const translated = t(key);
  return translated === key ? null : translated;
};

const translateOptionalWithOptions = (
  t: MemoryTranslateFn,
  key: string,
  options: Record<string, unknown>
) => {
  const translated = t(key, options);
  return translated === key ? null : translated;
};

export const getReadableEntityType = (t: MemoryTranslateFn, entityType: string | null | undefined) => {
  if (!entityType) {
    return null;
  }
  return translateOptional(t, `memory.pages.knowledge.entityTypes.${normalizeLabelKey(entityType)}`) || humanizeToken(entityType);
};

const isSelfEntity = (
  entityId: string,
  entity: L2Entity | undefined,
  selfEntityAliases: Set<string>
) => {
  const candidates = [
    entityId,
    entity?.canonical_name,
    ...(Array.isArray(entity?.aliases) ? entity.aliases : []),
  ];
  return candidates.some((candidate) => collectEntityAliasCandidates(candidate).some((alias) => selfEntityAliases.has(alias)));
};

export const getReadableEntityName = (
  t: MemoryTranslateFn,
  entityId: string,
  entity: L2Entity | undefined,
  selfEntityAliases: Set<string>
) => {
  const canonicalName = entity?.canonical_name?.trim();
  if (isSelfEntity(entityId, entity, selfEntityAliases)) {
    return t('memory.pages.knowledge.entities.self');
  }
  return canonicalName || humanizeToken(entityId);
};

export const getEntityOverviewKey = (
  entityId: string,
  entity: L2Entity | undefined,
  selfEntityAliases: Set<string>
) => (
  isSelfEntity(entityId, entity, selfEntityAliases) ? 'user:self' : entityId
);

export const getReadableTraitLabel = (t: MemoryTranslateFn, traitName: string) => (
  translateOptional(t, `memory.pages.knowledge.traitLabels.${normalizeLabelKey(traitName)}`) || humanizeToken(traitName)
);

const getCuratedTraitLabel = (t: MemoryTranslateFn, traitName: string) => (
  translateOptional(t, `memory.pages.knowledge.traitLabels.${normalizeLabelKey(traitName)}`)
);

const getAssertionValueI18nMode = (assertion: L2Assertion) => {
  const explicitMode = String(assertion.trait_value_i18n || '').trim();
  if (explicitMode) {
    return explicitMode;
  }
  return ASSERTION_FAMILY_VALUE_I18N[normalizeLabelKey(assertion.trait_family || '')] || 'literal';
};

export const getReadableAssertionValue = (t: MemoryTranslateFn, assertion: L2Assertion) => {
  const rawValue = coerceKnowledgeText(assertion.trait_value);
  if (getAssertionValueI18nMode(assertion) !== 'controlled') {
    return rawValue;
  }

  const valueKey = normalizeLabelKey(rawValue);
  if (!valueKey) {
    return rawValue;
  }

  const familyKey = normalizeLabelKey(assertion.trait_family || '');
  const traitKey = normalizeLabelKey(assertion.trait_name);
  return (
    (familyKey ? translateOptional(t, `memory.pages.knowledge.traitValues.${familyKey}.${valueKey}`) : null) ||
    (traitKey ? translateOptional(t, `memory.pages.knowledge.traitValues.${traitKey}.${valueKey}`) : null) ||
    translateOptional(t, `memory.pages.knowledge.traitValues.common.${valueKey}`) ||
    rawValue
  );
};

export const getReadablePredicateLabel = (t: MemoryTranslateFn, predicate: string) => (
  translateOptional(t, `memory.pages.knowledge.predicateLabels.${normalizeLabelKey(predicate)}`) || humanizeToken(predicate).toLowerCase()
);

export const getReadableAssertionTitle = (
  t: MemoryTranslateFn,
  entityName: string,
  assertion: L2Assertion,
) => {
  const traitValue = getReadableAssertionValue(t, assertion);
  const traitKey = normalizeLabelKey(assertion.trait_name);
  const specificTitle = translateOptionalWithOptions(
    t,
    `memory.pages.knowledge.readable.assertions.${traitKey}`,
    { entity: entityName, value: traitValue }
  );
  if (specificTitle) {
    return specificTitle;
  }
  return translateWithFallback(
    t,
    'memory.pages.knowledge.readable.assertion',
    '{{entity}}\'s {{attribute}} may be "{{value}}".',
    { entity: entityName, attribute: getReadableTraitLabel(t, assertion.trait_name), value: traitValue }
  );
};

export const getEvidenceSummary = (
  t: MemoryTranslateFn,
  evidenceCount: number | null | undefined,
  confidence: number | null | undefined
) => {
  const parts: string[] = [];
  if (typeof evidenceCount === 'number') {
    parts.push(translateWithFallback(
      t,
      'memory.pages.knowledge.readable.evidenceSummary',
      '{{count}} evidence item(s)',
      { count: evidenceCount }
    ));
  }
  const confidenceLabel = formatConfidence(confidence);
  if (confidenceLabel) {
    parts.push(translateWithFallback(
      t,
      'memory.pages.knowledge.readable.confidenceSummary',
      '{{confidence}} confidence',
      { confidence: confidenceLabel }
    ));
  }
  return parts.join(' · ');
};

export const formatConfidence = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return `${Math.round(value * 100)}%`;
};

export const formatEventTime = (timestamp: number | null | undefined) => {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) {
    return null;
  }
  return new Date(timestamp * 1000).toLocaleString();
};

export const latestPositiveTimestamp = (...timestamps: Array<number | null | undefined>) => {
  const positiveTimestamps = timestamps.filter(
    (timestamp): timestamp is number => typeof timestamp === 'number' && Number.isFinite(timestamp) && timestamp > 0
  );
  return positiveTimestamps.length > 0 ? Math.max(...positiveTimestamps) : null;
};

const isRecordValue = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const toFiniteNumber = (value: unknown) => {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
};

export const getRecordNumber = (value: Record<string, unknown> | undefined, key: string) => (
  value ? toFiniteNumber(value[key]) : null
);

const stringifyKnowledgeValue = (value: unknown): string => {
  if (isRecordValue(value) && 'value' in value) {
    return stringifyKnowledgeValue(value.value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => stringifyKnowledgeValue(item)).filter(Boolean).join(' / ');
  }
  if (isRecordValue(value)) {
    return Object.entries(value)
      .slice(0, 3)
      .map(([key, entryValue]) => `${humanizeToken(key)}: ${stringifyKnowledgeValue(entryValue)}`)
      .join(' / ');
  }
  return String(value ?? '').trim();
};

export const buildCuratedProfileSummary = (
  t: MemoryTranslateFn,
  snapshot: L2Snapshot | undefined
) => {
  if (!snapshot) {
    return [];
  }
  const entries = [
    ...Object.entries(snapshot.core_traits || {}),
    ...Object.entries(snapshot.preferences || {}),
  ];
  const summary: string[] = [];
  if (snapshot.current_mood) {
    summary.push(`${t('memory.pages.knowledge.fields.currentMood')}: ${snapshot.current_mood}`);
  }
  entries.forEach(([trait, value]) => {
    const label = getCuratedTraitLabel(t, trait);
    const readableValue = stringifyKnowledgeValue(value);
    if (!label || !readableValue || summary.length >= 4) {
      return;
    }
    summary.push(`${label}: ${readableValue}`);
  });
  return summary;
};
