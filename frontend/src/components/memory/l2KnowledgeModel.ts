import { DEFAULT_USER_ID } from '@/constants';
import type {
  L2Assertion,
  L2Entity,
  L2Relation,
  L2Snapshot,
  MemoryIdentityLink,
} from '@/api/modules/memory';

export type KnowledgeDetailRow = { label: string; value: string | number | null | undefined };
export type KnowledgeStatusGroup = 'active' | 'needsReview' | 'conflicted' | 'deprecated';
export type KnowledgeBaseGroupId = 'all' | 'aboutSelf' | 'preferences' | 'relationships' | 'workProjects' | 'interests' | 'other';
export type MemoryTranslateFn = (key: string, options?: Record<string, unknown>) => string;

export interface KnowledgeItem {
  id: string;
  kind: 'relation' | 'assertion';
  groupId: KnowledgeBaseGroupId;
  kindLabel: string;
  title: string;
  body?: string | null;
  entityType?: string | null;
  entityIds: string[];
  statusGroup: KnowledgeStatusGroup;
  statusLabel: string;
  confidence?: number | null;
  evidenceCount?: number | null;
  evidenceIds?: string[];
  updatedAt?: number | null;
  detailRows: KnowledgeDetailRow[];
  technicalRows?: KnowledgeDetailRow[];
  searchableText: string;
  assertionId?: string;
  correctionValue?: string;
  userFeedback?: string | null;
}

export interface KnowledgeBaseGroup {
  id: KnowledgeBaseGroupId;
  label: string;
  items: KnowledgeItem[];
  counts: {
    stable: number;
    review: number;
    relations: number;
    deprecated: number;
  };
  totalCount: number;
}

export interface EntityOverviewItem {
  id: string;
  name: string;
  typeLabel: string | null;
  snapshot?: L2Snapshot;
  summary: string[];
  activeItems: KnowledgeItem[];
  reviewItems: KnowledgeItem[];
  relationCount: number;
  assertionCount: number;
  knowledgeCount: number;
  reviewCount: number;
  lastUpdatedAt?: number | null;
  score: number;
  searchableText: string;
}

interface BuildKnowledgeItemsParams {
  relations: L2Relation[];
  assertions: L2Assertion[];
  entityById: Map<string, L2Entity>;
  selfEntityAliases: Set<string>;
  t: MemoryTranslateFn;
}

interface FilterKnowledgeItemsParams {
  query: string;
  statusFilter: string;
  entityTypeFilter: string;
}

interface BuildEntityOverviewItemsParams {
  entities: L2Entity[];
  entityById: Map<string, L2Entity>;
  snapshots: L2Snapshot[];
  knowledgeItems: KnowledgeItem[];
  selfEntityAliases: Set<string>;
  t: MemoryTranslateFn;
}

export const ENTITY_KNOWLEDGE_PREVIEW_LIMIT = 20;

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

const KNOWLEDGE_BASE_GROUP_IDS: Exclude<KnowledgeBaseGroupId, 'all'>[] = [
  'aboutSelf',
  'preferences',
  'relationships',
  'workProjects',
  'interests',
  'other',
];

const EMPTY_KNOWLEDGE_GROUP_COUNTS = {
  stable: 0,
  review: 0,
  relations: 0,
  deprecated: 0,
};

const normalizeSearchText = (value: unknown) => String(value ?? '').trim().toLowerCase();

const normalizeLabelKey = (value: string) => value
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

const textIncludesAny = (value: string, terms: string[]) => terms.some((term) => value.includes(term));

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

const getAssertionKnowledgeGroupId = (assertion: L2Assertion): KnowledgeBaseGroupId => {
  const trait = normalizeLabelKey(assertion.trait_name);
  const family = normalizeLabelKey(assertion.trait_family || '');
  const entityType = normalizeLabelKey(assertion.entity_type || '');
  const sourceDomain = normalizeLabelKey(assertion.source_domain || '');
  const text = `${trait} ${entityType} ${sourceDomain}`;

  if (
    textIncludesAny(trait, ['identity', 'self', 'name', 'address', 'profile', 'personal', 'birthday', 'timezone', 'language']) ||
    ['identity_profile', 'communication_profile', 'routine_profile', 'state_profile', 'mood', 'stress', 'engagement'].includes(family)
  ) {
    return 'aboutSelf';
  }
  if (
    family === 'preference_profile' ||
    textIncludesAny(trait, ['preference', 'prefers', 'favorite', 'favourite', 'like', 'dislike', 'coffee', 'music', 'artist', 'food', 'taste', 'style', 'habit'])
  ) {
    return 'preferences';
  }
  if (textIncludesAny(text, ['work', 'project', 'task', 'job', 'company', 'team', 'role', 'repo', 'code'])) {
    return 'workProjects';
  }
  if (textIncludesAny(text, ['relationship', 'contact', 'friend', 'family', 'colleague', 'person', 'people', 'group', 'organization', 'organisation'])) {
    return 'relationships';
  }
  if (textIncludesAny(text, ['interest', 'hobby', 'music', 'media', 'book', 'movie', 'game', 'topic', 'food', 'coffee', 'travel'])) {
    return 'interests';
  }
  return 'other';
};

const getRelationKnowledgeGroupId = (relation: L2Relation): KnowledgeBaseGroupId => {
  const predicate = normalizeLabelKey(relation.predicate);
  const subjectType = normalizeLabelKey(relation.subject_type || '');
  const objectType = normalizeLabelKey(relation.object_type || '');
  const text = `${predicate} ${subjectType} ${objectType}`;

  if (textIncludesAny(text, ['work', 'project', 'task', 'job', 'company', 'team', 'uses', 'tool', 'technology', 'hardware', 'software', 'repo', 'code'])) {
    return 'workProjects';
  }
  if (textIncludesAny(text, ['person', 'people', 'user', 'group', 'organization', 'organisation', 'friend', 'family', 'colleague', 'knows', 'works_with'])) {
    return 'relationships';
  }
  if (textIncludesAny(text, ['like', 'interest', 'listen', 'view', 'read', 'watch', 'play', 'music', 'media', 'book', 'movie', 'game', 'topic', 'food', 'coffee', 'artist'])) {
    return 'interests';
  }
  return 'relationships';
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

const getReadableEntityType = (t: MemoryTranslateFn, entityType: string | null | undefined) => {
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

const getReadableEntityName = (
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

const getEntityOverviewKey = (
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

const getReadablePredicateLabel = (t: MemoryTranslateFn, predicate: string) => (
  translateOptional(t, `memory.pages.knowledge.predicateLabels.${normalizeLabelKey(predicate)}`) || humanizeToken(predicate).toLowerCase()
);

const getReadableAssertionTitle = (
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

const getEvidenceSummary = (
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

const latestPositiveTimestamp = (...timestamps: Array<number | null | undefined>) => {
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

const getRecordNumber = (value: Record<string, unknown> | undefined, key: string) => (
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

const buildCuratedProfileSummary = (
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

const getAssertionStatusGroup = (assertion: L2Assertion): KnowledgeStatusGroup => {
  const feedback = normalizeSearchText(assertion.user_feedback);
  const validationState = normalizeSearchText(assertion.validation_state);
  const status = normalizeSearchText(assertion.status);
  if (
    feedback === 'rejected' ||
    ['user_rejected', 'rejected', 'superseded', 'expired', 'archived'].includes(validationState) ||
    ['user_rejected', 'rejected', 'superseded', 'expired', 'archived'].includes(status)
  ) {
    return 'deprecated';
  }
  if (['conflicted', 'contradicted'].includes(validationState) || ['conflicted', 'contradicted'].includes(status)) {
    return 'conflicted';
  }
  if (feedback === 'confirmed' || ['stable', 'corroborated'].includes(validationState) || status === 'stable') {
    return 'active';
  }
  return 'needsReview';
};

export const buildKnowledgeItems = ({
  relations,
  assertions,
  entityById,
  selfEntityAliases,
  t,
}: BuildKnowledgeItemsParams): KnowledgeItem[] => {
  const getEntityName = (entityId: string) => getReadableEntityName(t, entityId, entityById.get(entityId), selfEntityAliases);
  const getEntityType = (entityId: string, fallback?: string | null) => entityById.get(entityId)?.entity_type || fallback || null;
  const getEntityTypeLabel = (entityType: string | null | undefined) => getReadableEntityType(t, entityType) || entityType || null;

  const relationItems = relations.map((relation): KnowledgeItem => {
    const subjectName = getEntityName(relation.subject_id);
    const objectName = getEntityName(relation.object_id);
    const predicateLabel = getReadablePredicateLabel(t, relation.predicate);
    const entityType = getEntityType(relation.subject_id, relation.subject_type);
    const evidenceIds = coerceKnowledgeEventIds(relation.evidence_event_ids);
    const evidenceCount = relation.observation_count || evidenceIds.length;
    const statusGroup: KnowledgeStatusGroup = relation.status === 'conflicted'
      ? 'conflicted'
      : relation.status === 'deprecated'
        ? 'deprecated'
        : 'active';
    return {
      id: `relation:${relation.triple_id}`,
      kind: 'relation',
      groupId: getRelationKnowledgeGroupId(relation),
      kindLabel: t('memory.pages.knowledge.kind.relation'),
      title: translateWithFallback(
        t,
        'memory.pages.knowledge.readable.relation',
        '{{subject}} {{predicate}} {{object}}.',
        { subject: subjectName, predicate: predicateLabel, object: objectName }
      ),
      body: getEvidenceSummary(t, evidenceCount, relation.confidence),
      entityType,
      entityIds: Array.from(new Set([relation.subject_id, relation.object_id].filter(Boolean))),
      statusGroup,
      statusLabel: t(`memory.pages.knowledge.statusOptions.${statusGroup}`),
      confidence: relation.confidence,
      evidenceCount,
      evidenceIds,
      updatedAt: relation.last_observed_at || relation.updated_at || relation.first_observed_at,
      detailRows: [
        { label: t('memory.pages.knowledge.fields.subject'), value: subjectName },
        { label: t('memory.pages.knowledge.fields.predicate'), value: predicateLabel },
        { label: t('memory.pages.knowledge.fields.object'), value: objectName },
      ],
      technicalRows: [
        { label: t('memory.pages.knowledge.fields.technicalType'), value: `${getEntityTypeLabel(relation.subject_type)} -> ${getEntityTypeLabel(relation.object_type)}` },
        { label: t('memory.pages.knowledge.fields.technicalId'), value: relation.triple_id },
      ],
      searchableText: [subjectName, objectName, relation.subject_id, relation.object_id, predicateLabel, relation.predicate, relation.status, relation.triple_id].join(' '),
    };
  });

  const assertionItems = assertions.map((assertion): KnowledgeItem => {
    const entityName = getEntityName(assertion.entity_id);
    const traitLabel = getReadableTraitLabel(t, assertion.trait_name);
    const rawTraitValue = coerceKnowledgeText(assertion.trait_value);
    const traitValue = getReadableAssertionValue(t, assertion);
    const evidenceIds = coerceKnowledgeEventIds(assertion.evidence_events);
    const evidenceCount = evidenceIds.length;
    const statusGroup = getAssertionStatusGroup(assertion);
    return {
      id: `assertion:${assertion.assertion_id}`,
      kind: 'assertion',
      groupId: getAssertionKnowledgeGroupId(assertion),
      kindLabel: t('memory.pages.knowledge.kind.assertion'),
      title: getReadableAssertionTitle(t, entityName, assertion),
      body: getEvidenceSummary(t, evidenceCount, assertion.confidence_score),
      entityType: assertion.entity_type,
      entityIds: [assertion.entity_id].filter(Boolean),
      statusGroup,
      statusLabel: t(`memory.pages.knowledge.statusOptions.${statusGroup}`),
      confidence: assertion.confidence_score,
      evidenceCount,
      evidenceIds,
      updatedAt: assertion.last_validated_at || assertion.user_feedback_at || assertion.first_inferred_at,
      detailRows: [
        { label: t('memory.pages.knowledge.fields.entity'), value: entityName },
        { label: t('memory.pages.knowledge.fields.predicate'), value: traitLabel },
        { label: t('memory.pages.knowledge.fields.object'), value: traitValue },
      ],
      technicalRows: [
        { label: t('memory.pages.knowledge.fields.technicalType'), value: getEntityTypeLabel(assertion.entity_type) },
        { label: t('memory.pages.knowledge.fields.sourceDomain'), value: assertion.source_domain },
        { label: t('memory.pages.knowledge.fields.inferenceDepth'), value: assertion.inference_depth },
        { label: t('memory.pages.knowledge.fields.technicalId'), value: assertion.assertion_id },
      ],
      searchableText: [entityName, assertion.entity_id, assertion.entity_type, traitLabel, assertion.trait_name, traitValue, rawTraitValue, assertion.validation_state, assertion.source_domain].join(' '),
      assertionId: assertion.assertion_id,
      correctionValue: rawTraitValue,
      userFeedback: assertion.user_feedback,
    };
  });

  return [...assertionItems, ...relationItems];
};

export const filterKnowledgeItems = (
  knowledgeItems: KnowledgeItem[],
  { query, statusFilter, entityTypeFilter }: FilterKnowledgeItemsParams
) => {
  const normalizedQuery = normalizeSearchText(query);
  return knowledgeItems.filter((item) => {
    const matchesQuery = !normalizedQuery || normalizeSearchText(item.searchableText).includes(normalizedQuery);
    const matchesStatus = statusFilter === 'all' || item.statusGroup === statusFilter;
    const matchesType = entityTypeFilter === 'all' || item.entityType === entityTypeFilter;
    return matchesQuery && matchesStatus && matchesType;
  });
};

export const buildKnowledgeBaseGroups = (
  filteredKnowledgeItems: KnowledgeItem[],
  t: MemoryTranslateFn
): KnowledgeBaseGroup[] => {
  const buildCounts = (items: KnowledgeItem[]) => ({
    stable: items.filter((item) => item.statusGroup === 'active' && item.kind === 'assertion').length,
    review: items.filter((item) => item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted').length,
    relations: items.filter((item) => item.kind === 'relation' && item.statusGroup === 'active').length,
    deprecated: items.filter((item) => item.statusGroup === 'deprecated').length,
  });
  const groupsById = new Map<KnowledgeBaseGroupId, KnowledgeItem[]>();
  KNOWLEDGE_BASE_GROUP_IDS.forEach((groupId) => groupsById.set(groupId, []));
  filteredKnowledgeItems.forEach((item) => {
    groupsById.get(item.groupId)?.push(item);
  });

  const topicGroups = KNOWLEDGE_BASE_GROUP_IDS
    .map((groupId): KnowledgeBaseGroup => {
      const items = groupsById.get(groupId) ?? [];
      return {
        id: groupId,
        label: t(`memory.pages.knowledge.groups.${groupId}`),
        items,
        counts: buildCounts(items),
        totalCount: items.length,
      };
    })
    .filter((group) => group.totalCount > 0);

  return [
    {
      id: 'all',
      label: t('memory.pages.knowledge.groups.all'),
      items: filteredKnowledgeItems,
      counts: filteredKnowledgeItems.length > 0 ? buildCounts(filteredKnowledgeItems) : EMPTY_KNOWLEDGE_GROUP_COUNTS,
      totalCount: filteredKnowledgeItems.length,
    },
    ...topicGroups,
  ];
};

export const buildEntityOverviewItems = ({
  entities,
  entityById,
  snapshots,
  knowledgeItems,
  selfEntityAliases,
  t,
}: BuildEntityOverviewItemsParams): EntityOverviewItem[] => {
  type EntityDraft = {
    entityId: string;
    sourceEntityIds: Set<string>;
    entityType: string | null;
    snapshot?: L2Snapshot;
    items: KnowledgeItem[];
    relationIds: Set<string>;
    assertionIds: Set<string>;
    lastUpdatedAt: number | null;
  };

  const getEntityName = (entityId: string) => getReadableEntityName(t, entityId, entityById.get(entityId), selfEntityAliases);
  const getEntityTypeLabel = (entityType: string | null | undefined) => getReadableEntityType(t, entityType) || entityType || null;
  const drafts = new Map<string, EntityDraft>();
  const ensureDraft = (entityId: string, entityType?: string | null) => {
    const entity = entityById.get(entityId);
    const overviewKey = getEntityOverviewKey(entityId, entity, selfEntityAliases);
    const snapshot = snapshots.find(
      (item) => getEntityOverviewKey(item.entity_id, entityById.get(item.entity_id), selfEntityAliases) === overviewKey
    );
    const existing = drafts.get(overviewKey);
    if (existing) {
      existing.sourceEntityIds.add(entityId);
      existing.entityType = existing.entityType || entity?.entity_type || snapshot?.entity_type || entityType || null;
      existing.snapshot = existing.snapshot || snapshot;
      existing.lastUpdatedAt = latestPositiveTimestamp(
        existing.lastUpdatedAt,
        entity?.updated_at,
        entity?.created_at,
        snapshot?.last_interaction_at,
        snapshot?.last_updated_at
      );
      return existing;
    }
    const draft: EntityDraft = {
      entityId: overviewKey,
      sourceEntityIds: new Set([entityId]),
      entityType: entity?.entity_type || snapshot?.entity_type || entityType || null,
      snapshot,
      items: [],
      relationIds: new Set<string>(),
      assertionIds: new Set<string>(),
      lastUpdatedAt: latestPositiveTimestamp(
        entity?.updated_at,
        entity?.created_at,
        snapshot?.last_interaction_at,
        snapshot?.last_updated_at
      ),
    };
    drafts.set(overviewKey, draft);
    return draft;
  };

  entities.forEach((entity) => ensureDraft(entity.entity_id, entity.entity_type));
  snapshots.forEach((snapshot) => ensureDraft(snapshot.entity_id, snapshot.entity_type));
  knowledgeItems.forEach((item) => {
    item.entityIds.forEach((entityId) => {
      const draft = ensureDraft(entityId, item.entityType);
      draft.items.push(item);
      if (item.kind === 'relation') {
        draft.relationIds.add(item.id);
      } else {
        draft.assertionIds.add(item.id);
      }
    });
  });

  return Array.from(drafts.values())
    .map((draft): EntityOverviewItem => {
      const snapshot = draft.snapshot;
      const currentContext = snapshot?.current_context;
      const relationshipTopology = snapshot?.relationship_topology;
      const activeItems = draft.items.filter((item) => item.statusGroup === 'active');
      const reviewItems = draft.items.filter((item) => item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted');
      const summary = buildCuratedProfileSummary(t, snapshot);
      const relationCount = Math.max(
        draft.relationIds.size,
        getRecordNumber(currentContext, 'relation_count') ?? 0,
        (getRecordNumber(relationshipTopology, 'outgoing_count') ?? 0) + (getRecordNumber(relationshipTopology, 'incoming_count') ?? 0)
      );
      const assertionCount = Math.max(
        draft.assertionIds.size,
        getRecordNumber(currentContext, 'active_assertion_count') ?? 0
      );
      const lastUpdatedAt = latestPositiveTimestamp(
        snapshot?.last_interaction_at,
        snapshot?.last_updated_at,
        draft.lastUpdatedAt,
        ...draft.items.map((item) => item.updatedAt)
      );
      const interactionCount = snapshot?.interaction_count ?? getRecordNumber(currentContext, 'interaction_count') ?? 0;
      const score = reviewItems.length * 6 + activeItems.length * 3 + relationCount + assertionCount + interactionCount * 0.1 + (lastUpdatedAt ? lastUpdatedAt / 1_000_000_000 : 0);
      const name = getEntityName(draft.entityId);
      const typeLabel = getEntityTypeLabel(draft.entityType);
      return {
        id: draft.entityId,
        name,
        typeLabel,
        snapshot,
        summary,
        activeItems,
        reviewItems,
        relationCount,
        assertionCount,
        knowledgeCount: activeItems.length,
        reviewCount: reviewItems.length,
        lastUpdatedAt,
        score,
        searchableText: [
          draft.entityId,
          ...draft.sourceEntityIds,
          name,
          draft.entityType,
          typeLabel,
          ...summary,
          ...draft.items.map((item) => item.searchableText),
        ].join(' '),
      };
    })
    .sort((left, right) => right.score - left.score || left.name.localeCompare(right.name));
};
