import { getEntityTypeLabel } from '@/utils/entity-types';
import { DEFAULT_USER_ID } from '@/constants';
import type {
  L2Entity,
  MemoryIdentityLink,
} from '@/api/modules/memory';
import type { MemoryTranslateFn } from './l2KnowledgeTypes';

export const normalizeSearchText = (value: unknown) => String(value ?? '').trim().toLowerCase();

export const normalizeLabelKey = (value: string) => value
  .trim()
  .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
  .replace(/[^a-zA-Z0-9]+/g, '_')
  .replace(/^_+|_+$/g, '')
  .toLowerCase();

export const buildSelfEntityAliasSet = (
  canonicalSelfId: string | null | undefined,
  identityLinks: MemoryIdentityLink[]
) => {
  const ids = new Set<string>(['user:self', `user:${DEFAULT_USER_ID}`, DEFAULT_USER_ID]);
  if (canonicalSelfId) ids.add(canonicalSelfId);
  for (const link of identityLinks) {
    ids.add(link.memory_owner_id);
    ids.add(link.runtime_user_id);
    ids.add(`user:${link.runtime_user_id}`);
  }
  return ids;
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
    const parsed: unknown = JSON.parse(trimmed);
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

export const getReadableEntityType = (t: MemoryTranslateFn, entityType: string | null | undefined) => (
  entityType ? getEntityTypeLabel(entityType, t) : null
);

const isSelfEntity = (entityId: string, selfEntityAliases: Set<string>) => selfEntityAliases.has(entityId);

export const getReadableEntityName = (
  t: MemoryTranslateFn,
  entityId: string,
  entity: L2Entity | undefined,
  selfEntityAliases: Set<string>
) => {
  const canonicalName = entity?.canonical_name?.trim();
  if (isSelfEntity(entityId, selfEntityAliases)) {
    return t('memory.pages.knowledge.entities.self');
  }
  return canonicalName || t('memory.governance.assertions.unknownEntity');
};

export const getEntityOverviewKey = (
  entityId: string,
  _entity: L2Entity | undefined,
  selfEntityAliases: Set<string>
) => (
  isSelfEntity(entityId, selfEntityAliases) ? 'user:self' : entityId
);

export const getReadablePredicateLabel = (t: MemoryTranslateFn, predicate: string) => (
  translateOptional(t, `memory.pages.knowledge.predicateLabels.${normalizeLabelKey(predicate)}`) || humanizeToken(predicate).toLowerCase()
);

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

const toFiniteNumber = (value: unknown) => {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
};

export const getRecordNumber = (value: Record<string, unknown> | undefined, key: string) => (
  value ? toFiniteNumber(value[key]) : null
);
