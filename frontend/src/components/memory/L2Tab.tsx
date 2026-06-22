/**
 * L2Tab - L2 cognition workspace rendered as focused in-page sections.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Brain, Check, DatabaseZap, GitMerge, Network, Orbit, Pencil, RefreshCcw, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { DEFAULT_USER_ID } from '@/constants';
import {
  memoryApi,
  type L1Event,
  type L2Assertion,
  type L2Entity,
  type L2GraphConflictRule,
  type MemoryIdentityLink,
  type L2GraphConflictRulePayload,
  type L2Mention,
  type L2Relation,
  type L2Snapshot,
  type L2Statistics,
  type ManualL2EventPayload,
} from '@/api/modules/memory';

type KnowledgeDetailRow = { label: string; value: string | number | null | undefined };

export type L2KnowledgeSection =
  | 'overview'
  | 'knowledgeBase'
  | 'advanced'
  | 'knowledgeGraph'
  | 'theoryOfMind'
  | 'mindSnapshots'
  | 'lab'
  | 'canonicalEntities'
  | 'recentMentions'
  | 'conflictRules';

interface L2TabProps {
  section?: L2KnowledgeSection;
  stats: L2Statistics;
  relations: L2Relation[];
  assertions: L2Assertion[];
  identityLinks: MemoryIdentityLink[];
  entities: L2Entity[];
  mentions: L2Mention[];
  snapshots: L2Snapshot[];
  conflictRules: L2GraphConflictRule[];
  events: L1Event[];
  dominantPredicates?: Array<[string, number]>;
  knowledgeQuery?: string;
  knowledgeStatusFilter?: string;
  knowledgeEntityTypeFilter?: string;
  actionLoading: boolean;
  onFlushMicrobatches?: () => Promise<void>;
  onSubmitManualEvent: (payload: ManualL2EventPayload) => Promise<void>;
  onReplayExtraction: (eventId: string) => Promise<void>;
  onRunReconcile: (entityIds: string[]) => Promise<void>;
  onRunSnapshotRefresh: (entityIds: string[]) => Promise<void>;
  onUpsertGraphConflictRule: (payload: L2GraphConflictRulePayload) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
}

const defaultManualState: ManualL2EventPayload = {
  text: '',
  user_id: DEFAULT_USER_ID,
  session_id: 'l2-lab',
  source: 'l2_lab',
  entity_focus_hint: '',
};

const defaultRuleState: L2GraphConflictRulePayload = {
  predicate: '',
  opposite_predicates: [],
  opposite_resolution: 'mark_deprecated',
  exclusive_group: '',
  exclusive_scope: 'same_subject',
  exclusive_resolution: 'mark_deprecated',
};

const PANEL_CARD_CLASS =
  'rounded-sm border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.74)] shadow-none';

const SOFT_PANEL_CLASS =
  'rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel)/0.72)] px-4 py-3 text-sm text-[hsl(var(--memory-body))]';

const ENTITY_KNOWLEDGE_PREVIEW_LIMIT = 20;

type KnowledgeStatusGroup = 'active' | 'needsReview' | 'conflicted' | 'deprecated';
type KnowledgeBaseGroupId = 'all' | 'aboutSelf' | 'preferences' | 'relationships' | 'workProjects' | 'interests' | 'other';
type MemoryTranslateFn = (key: string, options?: Record<string, unknown>) => string;

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

interface KnowledgeItem {
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

interface KnowledgeBaseGroup {
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

interface EntityOverviewItem {
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

const buildSelfEntityAliasSet = (
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

const coerceKnowledgeText = (value: unknown): string => {
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

const coerceKnowledgeEventIds = (value: unknown): string[] => {
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

const translateWithFallback = (
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

const getReadableTraitLabel = (t: MemoryTranslateFn, traitName: string) => (
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

const getReadableAssertionValue = (t: MemoryTranslateFn, assertion: L2Assertion) => {
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

const formatConfidence = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return `${Math.round(value * 100)}%`;
};

const formatEventTime = (timestamp: number | null | undefined) => {
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

export const L2Tab: React.FC<L2TabProps> = ({
  section = 'lab',
  stats,
  relations,
  assertions,
  identityLinks,
  entities,
  mentions,
  snapshots,
  conflictRules,
  events,
  dominantPredicates = [],
  knowledgeQuery = '',
  knowledgeStatusFilter = 'all',
  knowledgeEntityTypeFilter = 'all',
  actionLoading,
  onFlushMicrobatches,
  onSubmitManualEvent,
  onReplayExtraction,
  onRunReconcile,
  onRunSnapshotRefresh,
  onUpsertGraphConflictRule,
  onSubmitAssertionFeedback,
  onCorrectAssertion,
}) => {
  const { t } = useTranslation('app');
  const [manualEvent, setManualEvent] = useState<ManualL2EventPayload>(defaultManualState);
  const [selectedEntityId, setSelectedEntityId] = useState('');
  const [selectedEventId, setSelectedEventId] = useState('');
  const [selectedKnowledgeGroupId, setSelectedKnowledgeGroupId] = useState<KnowledgeBaseGroupId>('aboutSelf');
  const [ruleForm, setRuleForm] = useState<L2GraphConflictRulePayload>(defaultRuleState);
  const [ruleOppositesText, setRuleOppositesText] = useState('');
  const [fetchedEvidenceEvents, setFetchedEvidenceEvents] = useState<Record<string, L1Event | null>>({});
  const [loadingEvidenceIds, setLoadingEvidenceIds] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!selectedEntityId && entities.length > 0) {
      setSelectedEntityId(entities[0].entity_id);
    }
  }, [entities, selectedEntityId]);

  useEffect(() => {
    if (!selectedEventId && events.length > 0) {
      setSelectedEventId(events[0].event_id);
    }
  }, [events, selectedEventId]);

  const selectedEntity = useMemo(
    () => entities.find((entity) => entity.entity_id === selectedEntityId) ?? null,
    [entities, selectedEntityId]
  );

  const entityById = useMemo(
    () => new Map(entities.map((entity) => [entity.entity_id, entity] as const)),
    [entities]
  );

  const selfEntityAliases = useMemo(
    () => buildSelfEntityAliasSet(stats.canonical_self_id, identityLinks),
    [identityLinks, stats.canonical_self_id]
  );

  const visibleEventById = useMemo(
    () => new Map(events.map((event) => [event.event_id, event] as const)),
    [events]
  );

  const evidenceEventsById = useMemo(() => {
    const merged = new Map<string, L1Event | null>(fetchedEvidenceEvents ? Object.entries(fetchedEvidenceEvents) : []);
    visibleEventById.forEach((event, eventId) => merged.set(eventId, event));
    return merged;
  }, [fetchedEvidenceEvents, visibleEventById]);

  const loadEvidenceEvents = useCallback(
    async (eventIds: string[]) => {
      const missingIds = eventIds
        .filter((eventId) => eventId && !evidenceEventsById.has(eventId) && !loadingEvidenceIds[eventId])
        .slice(0, 8);
      if (missingIds.length === 0) {
        return;
      }

      setLoadingEvidenceIds((current) => ({
        ...current,
        ...Object.fromEntries(missingIds.map((eventId) => [eventId, true])),
      }));

      try {
        const results = await Promise.all(
          missingIds.map(async (eventId) => {
            const response = await memoryApi.getL1Events({ event_id: eventId, limit: 1 });
            return [eventId, response.items?.[0] ?? null] as const;
          })
        );
        setFetchedEvidenceEvents((current) => ({
          ...current,
          ...Object.fromEntries(results),
        }));
      } catch (error) {
        console.error('Failed to load L1 evidence events:', error);
      } finally {
        setLoadingEvidenceIds((current) => {
          const next = { ...current };
          missingIds.forEach((eventId) => {
            delete next[eventId];
          });
          return next;
        });
      }
    },
    [evidenceEventsById, loadingEvidenceIds]
  );

  const getEntityName = useCallback((entityId: string) => {
    const entity = entityById.get(entityId);
    return getReadableEntityName(t, entityId, entity, selfEntityAliases);
  }, [entityById, selfEntityAliases, t]);

  const getEntityType = useCallback(
    (entityId: string, fallback?: string | null) => entityById.get(entityId)?.entity_type || fallback || null,
    [entityById]
  );
  const getEntityTypeLabel = useCallback(
    (entityType: string | null | undefined) => getReadableEntityType(t, entityType) || entityType || null,
    [t]
  );

  const evidenceBreakdownEntries = useMemo(
    () => Object.entries(stats.extract_by_evidence_class || {}).sort((left, right) => right[1] - left[1]),
    [stats.extract_by_evidence_class]
  );

  const skipReasonEntries = useMemo(
    () => Object.entries(stats.skip_by_reason || {}).sort((left, right) => right[1] - left[1]),
    [stats.skip_by_reason]
  );

  const entityTypeBreakdown = useMemo(
    () =>
      Array.from(
        entities.reduce((map, entity) => {
          map.set(entity.entity_type, (map.get(entity.entity_type) ?? 0) + 1);
          return map;
        }, new Map<string, number>())
      ).sort((left, right) => right[1] - left[1]),
    [entities]
  );

  const dominantTraits = useMemo(
    () =>
      Array.from(
        assertions.reduce((map, assertion) => {
          map.set(assertion.trait_name, (map.get(assertion.trait_name) ?? 0) + 1);
          return map;
        }, new Map<string, number>())
      ).sort((left, right) => right[1] - left[1]),
    [assertions]
  );

  const knowledgeItems = useMemo<KnowledgeItem[]>(() => {
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
  }, [assertions, getEntityName, getEntityType, getEntityTypeLabel, relations, t]);

  const filteredKnowledgeItems = useMemo(() => {
    const query = normalizeSearchText(knowledgeQuery);
    return knowledgeItems.filter((item) => {
      const matchesQuery = !query || normalizeSearchText(item.searchableText).includes(query);
      const matchesStatus = knowledgeStatusFilter === 'all' || item.statusGroup === knowledgeStatusFilter;
      const matchesType = knowledgeEntityTypeFilter === 'all' || item.entityType === knowledgeEntityTypeFilter;
      return matchesQuery && matchesStatus && matchesType;
    });
  }, [knowledgeEntityTypeFilter, knowledgeItems, knowledgeQuery, knowledgeStatusFilter]);

  const knowledgeBaseGroups = useMemo<KnowledgeBaseGroup[]>(() => {
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
  }, [filteredKnowledgeItems, t]);

  const selectedKnowledgeGroup = knowledgeBaseGroups.find((group) => group.id === selectedKnowledgeGroupId) ?? knowledgeBaseGroups[0];
  const selectedKnowledgeGroupItems = selectedKnowledgeGroup?.items ?? [];
  const selectedKnowledgeReviewItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted');
  const selectedKnowledgeStableItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'active' && item.kind === 'assertion');
  const selectedKnowledgeRelationItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'active' && item.kind === 'relation');
  const selectedKnowledgeDeprecatedItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'deprecated');

  const activeKnowledgeItems = knowledgeItems.filter((item) => item.statusGroup === 'active');
  const reviewKnowledgeItems = knowledgeItems.filter((item) => item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted');
  const entityOverviewItems = useMemo<EntityOverviewItem[]>(() => {
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
  }, [entities, entityById, getEntityName, getEntityTypeLabel, knowledgeItems, selfEntityAliases, snapshots, t]);
  const reviewItems = reviewKnowledgeItems.slice(0, 6);
  const overviewEntities = entityOverviewItems.slice(0, 8);

  const handleManualSubmit = async () => {
    if (!manualEvent.text.trim() || !manualEvent.user_id.trim()) {
      return;
    }
    await onSubmitManualEvent({
      ...manualEvent,
      text: manualEvent.text.trim(),
      user_id: manualEvent.user_id.trim(),
      session_id: manualEvent.session_id?.trim() || undefined,
      entity_focus_hint: manualEvent.entity_focus_hint?.trim() || undefined,
    });
    setManualEvent((current) => ({ ...current, text: '' }));
  };

  const handleRuleSave = async () => {
    if (!ruleForm.predicate.trim()) {
      return;
    }
    await onUpsertGraphConflictRule({
      predicate: ruleForm.predicate.trim(),
      opposite_predicates: ruleOppositesText
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      opposite_resolution: ruleForm.opposite_resolution,
      exclusive_group: ruleForm.exclusive_group?.trim() || null,
      exclusive_scope: ruleForm.exclusive_scope ?? 'same_subject',
      exclusive_resolution: ruleForm.exclusive_resolution,
    });
    setRuleForm(defaultRuleState);
    setRuleOppositesText('');
  };

  const renderOverview = () => (
    <div className="space-y-4">
      <section className="border-b border-[hsl(var(--memory-divider)/0.58)] pb-4">
        <p className="text-base font-medium leading-7 text-[hsl(var(--memory-title))]">
          {t('memory.pages.knowledge.overview.summary', {
            total: activeKnowledgeItems.length,
            review: reviewKnowledgeItems.length,
            entities: entityOverviewItems.length,
          })}
        </p>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-[hsl(var(--memory-body))]">
          {t('memory.pages.knowledge.overview.guidance')}
        </p>
      </section>

      {reviewItems.length > 0 ? (
        <KnowledgeListPanel
          title={t('memory.pages.knowledge.sections.reviewQueue')}
          emptyText={t('memory.pages.knowledge.emptyReviewQueue')}
          items={reviewItems}
          count={reviewKnowledgeItems.length}
          actionLoading={actionLoading}
          evidenceEventsById={evidenceEventsById}
          loadingEvidenceIds={loadingEvidenceIds}
          onLoadEvidenceEvents={loadEvidenceEvents}
          onSubmitAssertionFeedback={onSubmitAssertionFeedback}
          onCorrectAssertion={onCorrectAssertion}
          t={t}
        />
      ) : null}
      <EntityOverviewPanel
        title={t('memory.pages.knowledge.sections.entityOverview')}
        emptyText={t('memory.pages.knowledge.emptyEntityOverview')}
        items={overviewEntities}
        count={entityOverviewItems.length}
        actionLoading={actionLoading}
        evidenceEventsById={evidenceEventsById}
        loadingEvidenceIds={loadingEvidenceIds}
        onLoadEvidenceEvents={loadEvidenceEvents}
        onSubmitAssertionFeedback={onSubmitAssertionFeedback}
        onCorrectAssertion={onCorrectAssertion}
        t={t}
      />
    </div>
  );

  const renderKnowledgeBase = () => (
    <div className="space-y-4">
      <KnowledgeBaseBrowser
        groups={knowledgeBaseGroups}
        selectedGroupId={selectedKnowledgeGroup?.id ?? 'all'}
        selectedGroup={selectedKnowledgeGroup}
        reviewItems={selectedKnowledgeReviewItems}
        stableItems={selectedKnowledgeStableItems}
        relationItems={selectedKnowledgeRelationItems}
        deprecatedItems={selectedKnowledgeDeprecatedItems}
        emptyText={t('memory.pages.knowledge.emptyKnowledge')}
        actionLoading={actionLoading}
        evidenceEventsById={evidenceEventsById}
        loadingEvidenceIds={loadingEvidenceIds}
        onLoadEvidenceEvents={loadEvidenceEvents}
        onSubmitAssertionFeedback={onSubmitAssertionFeedback}
        onCorrectAssertion={onCorrectAssertion}
        onSelectGroup={setSelectedKnowledgeGroupId}
        t={t}
      />
    </div>
  );

  const renderAdvanced = () => (
    <div className="space-y-4">
      <section className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.78)] px-4 py-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.pages.knowledge.sections.maintenance')}</h2>
            <p className="mt-1 text-sm leading-6 text-[hsl(var(--memory-body))]">{t('memory.pages.knowledge.advancedHint')}</p>
          </div>
          {onFlushMicrobatches ? (
            <Button
              variant="outline"
              className="h-9 rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 text-sm text-[hsl(var(--memory-title))]"
              onClick={() => void onFlushMicrobatches()}
              disabled={actionLoading}
            >
              {actionLoading ? <RefreshCcw className="mr-2 h-4 w-4 animate-spin" /> : <DatabaseZap className="mr-2 h-4 w-4" />}
              {t('memory.pages.knowledge.actions.flushMicrobatches')}
            </Button>
          ) : null}
        </div>
      </section>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3" open>
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.title')}</summary>
        <div className="mt-4">{renderLab()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.entities')}</summary>
        <div className="mt-4">{renderCanonicalEntities()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.mentions')}</summary>
        <div className="mt-4">{renderRecentMentions()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.conflictRules')}</summary>
        <div className="mt-4">{renderConflictRules()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.pages.knowledge.sections.diagnostics')}</summary>
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          <BreakdownCard
            title={t('memory.pages.knowledge.sections.entityTypes')}
            emptyText={t('memory.pages.knowledge.focusAll')}
            entries={entityTypeBreakdown}
          />
          <BreakdownCard
            title={t('memory.pages.knowledge.sections.structureOverview')}
            emptyText={t('memory.l2.noRelations')}
            entries={dominantPredicates.slice(0, 8)}
          />
          <BreakdownCard
            title={t('memory.l2.lab.evidenceBreakdown')}
            emptyText={t('memory.l2.lab.noEvidenceBreakdown')}
            entries={evidenceBreakdownEntries}
          />
          <BreakdownCard
            title={t('memory.l2.lab.skipReasonBreakdown')}
            emptyText={t('memory.l2.lab.noSkipReasons')}
            entries={skipReasonEntries}
          />
        </div>
      </details>
    </div>
  );

  const renderKnowledgeGraph = () => (
    <div className="space-y-4">
      <InfoCard
        icon={<Network className="h-5 w-5" />}
        title={t('memory.l2.relations')}
        emptyText={t('memory.l2.noRelations')}
      >
        {relations.slice(0, 60).map((relation) => (
          <div key={relation.triple_id} className={SOFT_PANEL_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <div className="font-medium text-[hsl(var(--memory-title))]">{relation.subject_id}</div>
              <Badge variant={relation.status === 'active' ? 'secondary' : 'outline'}>{relation.status}</Badge>
            </div>
            <div className="mt-2 text-[hsl(var(--memory-body))]">
              {relation.predicate} → {relation.object_id}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="secondary">{`${(relation.confidence * 100).toFixed(0)}%`}</Badge>
              <Badge variant="outline">{`${relation.observation_count} obs`}</Badge>
            </div>
          </div>
        ))}
      </InfoCard>
    </div>
  );

  const renderTheoryOfMind = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base text-[hsl(var(--memory-title))]">
              <Brain className="h-5 w-5" />
              {t('memory.pages.knowledge.sections.traitFocus')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <StatLine label={t('memory.l2.assertionCount')} value={String(assertions.length)} />
            <div className="flex flex-wrap gap-2">
              {dominantTraits.slice(0, 8).map(([trait, count]) => (
                <SummaryPill key={trait}>
                  {trait} · {count}
                </SummaryPill>
              ))}
              {dominantTraits.length === 0 ? (
                <SummaryPill>{t('memory.l2.noAssertions')}</SummaryPill>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <InfoCard
          icon={<Brain className="h-5 w-5" />}
          title={t('memory.l2.assertions')}
          emptyText={t('memory.l2.noAssertions')}
        >
          {assertions.slice(0, 60).map((assertion) => (
            <div key={assertion.assertion_id} className={SOFT_PANEL_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-[hsl(var(--memory-title))]">{assertion.entity_id}</span>
                <Badge variant="outline">{assertion.validation_state}</Badge>
              </div>
              <div className="mt-2 text-[hsl(var(--memory-body))]">
                {getReadableTraitLabel(t, assertion.trait_name)}: {getReadableAssertionValue(t, assertion)}
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{`${(assertion.confidence_score * 100).toFixed(0)}%`}</Badge>
                  <Badge variant="outline">{assertion.inference_depth}</Badge>
                  {assertion.user_feedback && (
                    <Badge variant={assertion.user_feedback === 'confirmed' ? 'default' : 'destructive'}>
                      {assertion.user_feedback === 'confirmed' ? t('memory.l2.confirmed') : t('memory.l2.rejected')}
                    </Badge>
                  )}
                </div>
                {onSubmitAssertionFeedback && (
                  <div className="flex shrink-0 gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-green-600 hover:bg-green-100 dark:hover:bg-green-900/30"
                      disabled={actionLoading || assertion.user_feedback === 'confirmed'}
                      onClick={() => onSubmitAssertionFeedback(assertion.assertion_id, 'confirmed')}
                      title={t('memory.l2.confirmAssertion')}
                    >
                      <Check className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-red-600 hover:bg-red-100 dark:hover:bg-red-900/30"
                      disabled={actionLoading || assertion.user_feedback === 'rejected'}
                      onClick={() => onSubmitAssertionFeedback(assertion.assertion_id, 'rejected')}
                      title={t('memory.l2.rejectAssertion')}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );

  const renderMindSnapshots = () => (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <MetricCard label={t('memory.l2.lab.snapshotCount')} value={snapshots.length} />
        <MetricCard
          label={t('memory.pages.knowledge.sections.snapshotMood')}
          value={snapshots.filter((snapshot) => snapshot.current_mood).length}
        />
        <MetricCard
          label={t('memory.pages.knowledge.sections.snapshotTraits')}
          value={snapshots.reduce((count, snapshot) => count + Object.keys(snapshot.core_traits || {}).length, 0)}
        />
      </div>

      <InfoCard
        icon={<Orbit className="h-5 w-5" />}
        title={t('memory.l2.lab.snapshots')}
        emptyText={t('memory.l2.lab.noSnapshots')}
      >
        {snapshots.slice(0, 60).map((snapshot) => (
          <div key={snapshot.snapshot_id} className={SOFT_PANEL_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-[hsl(var(--memory-title))]">{snapshot.entity_id}</span>
              {snapshot.current_mood ? <Badge variant="secondary">{snapshot.current_mood}</Badge> : null}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(snapshot.core_traits || {}).slice(0, 6).map(([trait, value]) => (
                <SummaryPill key={`${snapshot.snapshot_id}-${trait}`}>
                  {trait}: {String(value)}
                </SummaryPill>
              ))}
              {Object.keys(snapshot.core_traits || {}).length === 0 ? (
                <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l2.lab.noCoreTraits')}</span>
              ) : null}
            </div>
          </div>
        ))}
      </InfoCard>
    </div>
  );

  const renderLab = () => (
    <div className="grid gap-4 xl:grid-cols-[1.12fr_0.88fr]">
      <Card className={`${PANEL_CARD_CLASS} border-dashed`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-[hsl(var(--memory-title))]">
            <DatabaseZap className="h-5 w-5" />
            {t('memory.l2.lab.title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.l2.lab.manualEventLabel')}</label>
          <Textarea
            value={manualEvent.text}
            onChange={(event) => setManualEvent((current) => ({ ...current, text: event.target.value }))}
            placeholder={t('memory.l2.lab.manualEventPlaceholder')}
          />
          <div className="grid gap-3 md:grid-cols-3">
            <Input
              value={manualEvent.user_id}
              onChange={(event) => setManualEvent((current) => ({ ...current, user_id: event.target.value }))}
              placeholder={t('memory.l2.lab.userIdPlaceholder')}
            />
            <Input
              value={manualEvent.session_id || ''}
              onChange={(event) => setManualEvent((current) => ({ ...current, session_id: event.target.value }))}
              placeholder={t('memory.l2.lab.sessionIdPlaceholder')}
            />
            <Input
              value={manualEvent.entity_focus_hint || ''}
              onChange={(event) => setManualEvent((current) => ({ ...current, entity_focus_hint: event.target.value }))}
              placeholder={t('memory.l2.lab.entityFocusPlaceholder')}
            />
          </div>
          <Button onClick={handleManualSubmit} disabled={actionLoading || !manualEvent.text.trim()}>
            <DatabaseZap className="mr-2 h-4 w-4" />
            {t('memory.l2.lab.injectEvent')}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.eventReplayLabel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
              value={selectedEventId}
              onChange={(event) => setSelectedEventId(event.target.value)}
            >
              <option value="">{t('memory.l2.lab.selectEvent')}</option>
              {events.map((event) => (
                <option key={event.event_id} value={event.event_id}>
                  {event.event_id} · {event.event_type}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              className="w-full rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle))]"
              onClick={() => onReplayExtraction(selectedEventId)}
              disabled={actionLoading || !selectedEventId}
            >
              <RefreshCcw className="mr-2 h-4 w-4" />
              {t('memory.l2.lab.replayExtraction')}
            </Button>
          </CardContent>
        </Card>

        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.entityActionLabel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
              value={selectedEntityId}
              onChange={(event) => setSelectedEntityId(event.target.value)}
            >
              <option value="">{t('memory.l2.lab.selectEntity')}</option>
              {entities.map((entity) => (
                <option key={entity.entity_id} value={entity.entity_id}>
                  {entity.entity_id} · {entity.canonical_name}
                </option>
              ))}
            </select>
            <div className="grid gap-2 md:grid-cols-2">
              <Button
                variant="outline"
                className="rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle))]"
                onClick={() => onRunReconcile(selectedEntityId ? [selectedEntityId] : [])}
                disabled={actionLoading || !selectedEntityId}
              >
                <GitMerge className="mr-2 h-4 w-4" />
                {t('memory.l2.lab.runReconcile')}
              </Button>
              <Button
                variant="outline"
                className="rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle))]"
                onClick={() => onRunSnapshotRefresh(selectedEntityId ? [selectedEntityId] : [])}
                disabled={actionLoading || !selectedEntityId}
              >
                <Orbit className="mr-2 h-4 w-4" />
                {t('memory.l2.lab.refreshSnapshot')}
              </Button>
            </div>
            {selectedEntity ? (
              <div className={SOFT_PANEL_CLASS}>
                <div className="font-medium text-[hsl(var(--memory-title))]">{selectedEntity.canonical_name}</div>
                <div className="mt-1 text-[hsl(var(--memory-body))]">{selectedEntity.entity_id}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedEntity.aliases.length > 0 ? (
                    selectedEntity.aliases.map((alias) => (
                      <SummaryPill key={`${selectedEntity.entity_id}-${alias}`}>{alias}</SummaryPill>
                    ))
                  ) : (
                    <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l2.lab.noAliases')}</span>
                  )}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );

  const renderCanonicalEntities = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[0.78fr_1.22fr]">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.entities')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <StatLine label={t('memory.l2.lab.entityCount')} value={String(entities.length)} />
            <div className="flex flex-wrap gap-2">
              {entityTypeBreakdown.map(([entityType, count]) => (
                <SummaryPill key={entityType}>
                  {entityType} · {count}
                </SummaryPill>
              ))}
            </div>
          </CardContent>
        </Card>

        <InfoCard
          icon={<GitMerge className="h-5 w-5" />}
          title={t('memory.l2.lab.entities')}
          emptyText={t('memory.l2.lab.noEntities')}
        >
          {entities.slice(0, 60).map((entity) => (
            <div key={entity.entity_id} className={SOFT_PANEL_CLASS}>
              <div className="font-medium text-[hsl(var(--memory-title))]">{entity.canonical_name}</div>
              <div className="mt-1 text-[hsl(var(--memory-body))]">{entity.entity_id}</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {entity.aliases.length > 0 ? (
                  entity.aliases.map((alias) => (
                    <SummaryPill key={`${entity.entity_id}-${alias}`}>{alias}</SummaryPill>
                  ))
                ) : (
                  <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l2.lab.noAliases')}</span>
                )}
              </div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );

  const renderRecentMentions = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <InfoCard
          icon={<RefreshCcw className="h-5 w-5" />}
          title={t('memory.l2.lab.mentions')}
          emptyText={t('memory.l2.lab.noMentions')}
        >
          {mentions.slice(0, 60).map((mention) => (
            <div key={String(mention.mention_id)} className={SOFT_PANEL_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-[hsl(var(--memory-title))]">{mention.mention_text}</span>
                {mention.resolved_entity_id ? (
                  <Badge variant="secondary">{mention.resolved_entity_id}</Badge>
                ) : (
                  <Badge variant="outline">{t('memory.l2.lab.unresolved')}</Badge>
                )}
              </div>
              <div className="mt-2 text-[hsl(var(--memory-body))]">{mention.evidence_text || '-'}</div>
            </div>
          ))}
        </InfoCard>

        <InfoCard
          icon={<RefreshCcw className="h-5 w-5" />}
          title={t('memory.pages.knowledge.sections.recentEventContext')}
          emptyText={t('memory.l1.noEvents')}
        >
          {events.slice(0, 20).map((event) => (
            <div key={event.event_id} className={SOFT_PANEL_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-[hsl(var(--memory-title))]">{event.event_type}</span>
                <Badge variant="outline">{event.source}</Badge>
              </div>
              <div className="mt-2 line-clamp-3 text-[hsl(var(--memory-body))]">{event.content}</div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );

  const renderConflictRules = () => (
    <div className="grid gap-4 xl:grid-cols-[0.96fr_1.04fr]">
      <InfoCard
        icon={<GitMerge className="h-5 w-5" />}
        title={t('memory.l2.lab.conflictRules')}
        emptyText={t('memory.l2.lab.noConflictRules')}
      >
        {conflictRules.map((rule) => (
          <div key={rule.predicate} className={SOFT_PANEL_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-[hsl(var(--memory-title))]">{rule.predicate}</span>
              <Badge variant="outline">{rule.exclusive_group || t('memory.l2.lab.noExclusiveGroup')}</Badge>
            </div>
            <div className="mt-2 text-[hsl(var(--memory-body))]">
              {rule.opposite_predicates.length > 0
                ? rule.opposite_predicates.join(', ')
                : t('memory.l2.lab.noOpposites')}
            </div>
          </div>
        ))}
      </InfoCard>

      <Card className={PANEL_CARD_CLASS}>
        <CardHeader>
          <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.ruleEditorTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            value={ruleForm.predicate}
            onChange={(event) => setRuleForm((current) => ({ ...current, predicate: event.target.value }))}
            placeholder={t('memory.l2.lab.rulePredicatePlaceholder')}
          />
          <Input
            value={ruleOppositesText}
            onChange={(event) => setRuleOppositesText(event.target.value)}
            placeholder={t('memory.l2.lab.ruleOppositesPlaceholder')}
          />
          <Input
            value={ruleForm.exclusive_group || ''}
            onChange={(event) => setRuleForm((current) => ({ ...current, exclusive_group: event.target.value }))}
            placeholder={t('memory.l2.lab.ruleExclusiveGroupPlaceholder')}
          />
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="l2-rule-opposite-resolution" className="text-sm font-medium text-[hsl(var(--memory-title))]">
                {t('memory.l2.lab.ruleOppositeResolution')}
              </label>
              <select
                id="l2-rule-opposite-resolution"
                className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
                value={ruleForm.opposite_resolution}
                onChange={(event) =>
                  setRuleForm((current) => ({ ...current, opposite_resolution: event.target.value }))
                }
              >
                <option value="mark_deprecated">{t('memory.l2.lab.ruleResolutionOptions.mark_deprecated')}</option>
                <option value="mark_conflicted">{t('memory.l2.lab.ruleResolutionOptions.mark_conflicted')}</option>
              </select>
            </div>
            <div className="space-y-2">
              <label htmlFor="l2-rule-exclusive-resolution" className="text-sm font-medium text-[hsl(var(--memory-title))]">
                {t('memory.l2.lab.ruleExclusiveResolution')}
              </label>
              <select
                id="l2-rule-exclusive-resolution"
                className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
                value={ruleForm.exclusive_resolution}
                onChange={(event) =>
                  setRuleForm((current) => ({ ...current, exclusive_resolution: event.target.value }))
                }
              >
                <option value="mark_deprecated">{t('memory.l2.lab.ruleResolutionOptions.mark_deprecated')}</option>
                <option value="mark_conflicted">{t('memory.l2.lab.ruleResolutionOptions.mark_conflicted')}</option>
              </select>
            </div>
          </div>
          <Button onClick={handleRuleSave} disabled={actionLoading || !ruleForm.predicate.trim()}>
            <GitMerge className="mr-2 h-4 w-4" />
            {t('memory.l2.lab.saveRule')}
          </Button>
        </CardContent>
      </Card>
    </div>
  );

  switch (section) {
    case 'overview':
      return renderOverview();
    case 'knowledgeBase':
      return renderKnowledgeBase();
    case 'advanced':
      return renderAdvanced();
    case 'knowledgeGraph':
      return renderKnowledgeGraph();
    case 'theoryOfMind':
      return renderTheoryOfMind();
    case 'mindSnapshots':
      return renderMindSnapshots();
    case 'lab':
      return renderLab();
    case 'canonicalEntities':
      return renderCanonicalEntities();
    case 'recentMentions':
      return renderRecentMentions();
    case 'conflictRules':
      return renderConflictRules();
    default:
      return null;
  }
};

const KnowledgeListPanel: React.FC<{
  title: string;
  emptyText: string;
  items: KnowledgeItem[];
  count?: number;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
  t: (key: string, options?: Record<string, unknown>) => string;
}> = ({ title, emptyText, items, count, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onCorrectAssertion, t }) => (
  <section className="overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.64)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
      <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
      <span className="text-xs text-[hsl(var(--memory-muted))]">{count ?? items.length}</span>
    </div>
    {items.length === 0 ? (
      <div className="px-4 py-4">
        <EmptyState copy={emptyText} />
      </div>
    ) : (
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.52)]">
        {items.map((item) => (
          <KnowledgeItemRow
            key={item.id}
            item={item}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onCorrectAssertion={onCorrectAssertion}
            t={t}
          />
        ))}
      </div>
    )}
  </section>
);

const KnowledgeBaseBrowser: React.FC<{
  groups: KnowledgeBaseGroup[];
  selectedGroupId: KnowledgeBaseGroupId;
  selectedGroup: KnowledgeBaseGroup | undefined;
  reviewItems: KnowledgeItem[];
  stableItems: KnowledgeItem[];
  relationItems: KnowledgeItem[];
  deprecatedItems: KnowledgeItem[];
  emptyText: string;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
  onSelectGroup: (groupId: KnowledgeBaseGroupId) => void;
  t: MemoryTranslateFn;
}> = ({
  groups,
  selectedGroupId,
  selectedGroup,
  reviewItems,
  stableItems,
  relationItems,
  deprecatedItems,
  emptyText,
  actionLoading,
  evidenceEventsById,
  loadingEvidenceIds,
  onLoadEvidenceEvents,
  onSubmitAssertionFeedback,
  onCorrectAssertion,
  onSelectGroup,
  t,
}) => {
  const hasItems = Boolean(selectedGroup && selectedGroup.totalCount > 0);

  return (
    <section className="grid gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
      <aside className="min-w-0 rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.72)]">
        <div className="border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
          <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.pages.knowledge.sections.knowledgeDirectory')}</h2>
        </div>
        <div className="space-y-1 p-2">
          {groups.map((group) => {
            const isSelected = group.id === selectedGroupId;
            return (
              <button
                key={group.id}
                type="button"
                className={`w-full rounded-sm border px-3 py-2 text-left transition-colors ${isSelected
                  ? 'border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel))] text-[hsl(var(--memory-title))]'
                  : 'border-transparent text-[hsl(var(--memory-body))] hover:border-[hsl(var(--memory-border)/0.5)] hover:bg-[hsl(var(--memory-panel-subtle)/0.38)]'}`}
                onClick={() => onSelectGroup(group.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{group.label}</span>
                  <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{group.totalCount}</span>
                </div>
                <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] leading-5 text-[hsl(var(--memory-muted))]">
                  <span>{t('memory.pages.knowledge.groupCounts.stable', { count: group.counts.stable })}</span>
                  <span>{t('memory.pages.knowledge.groupCounts.review', { count: group.counts.review })}</span>
                  <span>{t('memory.pages.knowledge.groupCounts.relations', { count: group.counts.relations })}</span>
                  <span>{t('memory.pages.knowledge.groupCounts.deprecated', { count: group.counts.deprecated })}</span>
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="min-w-0 overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.64)]">
        <div className="border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{selectedGroup?.label ?? t('memory.pages.knowledge.groups.all')}</h2>
            {selectedGroup ? (
              <span className="text-xs text-[hsl(var(--memory-muted))]">
                {t('memory.pages.knowledge.knowledgeBaseSummary', {
                  total: selectedGroup.totalCount,
                  stable: selectedGroup.counts.stable,
                  review: selectedGroup.counts.review,
                  relations: selectedGroup.counts.relations,
                  deprecated: selectedGroup.counts.deprecated,
                })}
              </span>
            ) : null}
          </div>
        </div>

        {!hasItems ? (
          <div className="px-4 py-4">
            <EmptyState copy={emptyText} />
          </div>
        ) : (
          <div className="space-y-3 p-3">
            {reviewItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.pendingSignals')}
                items={reviewItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onCorrectAssertion={onCorrectAssertion}
                t={t}
              />
            ) : null}
            {stableItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.stableKnowledge')}
                items={stableItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onCorrectAssertion={onCorrectAssertion}
                t={t}
              />
            ) : null}
            {relationItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.relations')}
                items={relationItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onCorrectAssertion={onCorrectAssertion}
                t={t}
              />
            ) : null}
            {deprecatedItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.deprecatedKnowledge')}
                items={deprecatedItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onCorrectAssertion={onCorrectAssertion}
                t={t}
              />
            ) : null}
          </div>
        )}
      </section>
    </section>
  );
};

const KnowledgeGroupItemSection: React.FC<{
  title: string;
  items: KnowledgeItem[];
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
  t: MemoryTranslateFn;
}> = ({ title, items, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onCorrectAssertion, t }) => (
  <section className="min-w-0 overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel)/0.58)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.46)] px-3 py-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
      <span>{title}</span>
      <span className="shrink-0">{t('memory.pages.knowledge.totalItemCount', { total: items.length })}</span>
    </div>
    <div className="max-h-[42rem] divide-y divide-[hsl(var(--memory-divider)/0.46)] overflow-y-auto overscroll-contain">
      {items.map((item) => (
        <KnowledgeItemRow
          key={`${title}-${item.id}`}
          item={item}
          actionLoading={actionLoading}
          evidenceEventsById={evidenceEventsById}
          loadingEvidenceIds={loadingEvidenceIds}
          onLoadEvidenceEvents={onLoadEvidenceEvents}
          onSubmitAssertionFeedback={onSubmitAssertionFeedback}
          onCorrectAssertion={onCorrectAssertion}
          t={t}
        />
      ))}
    </div>
  </section>
);

const EntityOverviewPanel: React.FC<{
  title: string;
  emptyText: string;
  items: EntityOverviewItem[];
  count?: number;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
  t: MemoryTranslateFn;
}> = ({ title, emptyText, items, count, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onCorrectAssertion, t }) => (
  <section className="overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.64)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
      <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
      <span className="text-xs text-[hsl(var(--memory-muted))]">{count ?? items.length}</span>
    </div>
    {items.length === 0 ? (
      <div className="px-4 py-4">
        <EmptyState copy={emptyText} />
      </div>
    ) : (
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.52)]">
        {items.map((item) => (
          <EntityOverviewRow
            key={item.id}
            item={item}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onCorrectAssertion={onCorrectAssertion}
            t={t}
          />
        ))}
      </div>
    )}
  </section>
);

const EntityOverviewRow: React.FC<{
  item: EntityOverviewItem;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
  t: MemoryTranslateFn;
}> = ({ item, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onCorrectAssertion, t }) => {
  const metrics = [
    t('memory.pages.knowledge.entityMetrics.stableKnowledge', { count: item.knowledgeCount }),
    t('memory.pages.knowledge.entityMetrics.pendingSignals', { count: item.reviewCount }),
    t('memory.pages.knowledge.entityMetrics.relations', { count: item.relationCount }),
    t('memory.pages.knowledge.entityMetrics.assertions', { count: item.assertionCount }),
  ];
  const summary = item.summary.length > 0
    ? item.summary.slice(0, 4).join(' · ')
    : t('memory.pages.knowledge.entitySummaryFallback', {
      stable: item.knowledgeCount,
      relations: item.relationCount,
      assertions: item.assertionCount,
    });
  const lastUpdated = formatEventTime(item.lastUpdatedAt);

  return (
    <details className="group">
      <summary className="cursor-pointer list-none px-4 py-3 transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.38)] [&::-webkit-details-marker]:hidden">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-sm font-semibold leading-6 text-[hsl(var(--memory-title))]">{item.name}</span>
            </div>
            <div className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{summary}</div>
            {lastUpdated ? (
              <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                {t('memory.pages.knowledge.fields.updatedAt')}: {lastUpdated}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap justify-start gap-1.5 md:justify-end">
            {metrics.map((metric) => (
              <SummaryPill key={`${item.id}-${metric}`}>{metric}</SummaryPill>
            ))}
          </div>
        </div>
      </summary>
      <div className="border-t border-[hsl(var(--memory-divider)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.36)] px-4 py-3">
        <div className="space-y-3">
          <EntityKnowledgeMiniList
            title={t('memory.pages.knowledge.sections.stableKnowledge')}
            emptyText={t('memory.pages.knowledge.emptyStableKnowledge')}
            items={item.activeItems.slice(0, ENTITY_KNOWLEDGE_PREVIEW_LIMIT)}
            totalCount={item.activeItems.length}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onCorrectAssertion={onCorrectAssertion}
            t={t}
          />
          <EntityKnowledgeMiniList
            title={t('memory.pages.knowledge.sections.pendingSignals')}
            emptyText={t('memory.pages.knowledge.emptyPendingSignals')}
            items={item.reviewItems.slice(0, ENTITY_KNOWLEDGE_PREVIEW_LIMIT)}
            totalCount={item.reviewItems.length}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onCorrectAssertion={onCorrectAssertion}
            t={t}
          />
        </div>
      </div>
    </details>
  );
};

const EntityKnowledgeMiniList: React.FC<{
  title: string;
  emptyText: string;
  items: KnowledgeItem[];
  totalCount: number;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
  t: MemoryTranslateFn;
}> = ({ title, emptyText, items, totalCount, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onCorrectAssertion, t }) => (
  <section className="min-w-0 overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel)/0.58)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.46)] px-3 py-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
      <span>{title}</span>
      <span className="shrink-0">
        {items.length < totalCount
          ? t('memory.pages.knowledge.visibleItemCount', { shown: items.length, total: totalCount })
          : t('memory.pages.knowledge.totalItemCount', { total: totalCount })}
      </span>
    </div>
    {items.length === 0 ? (
      <div className="px-3 py-3 text-sm leading-6 text-[hsl(var(--memory-muted))]">{emptyText}</div>
    ) : (
      <div className="max-h-[32rem] divide-y divide-[hsl(var(--memory-divider)/0.46)] overflow-y-auto overscroll-contain">
        {items.map((knowledgeItem) => (
          <KnowledgeItemRow
            key={`${title}-${knowledgeItem.id}`}
            item={knowledgeItem}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onCorrectAssertion={onCorrectAssertion}
            t={t}
          />
        ))}
      </div>
    )}
  </section>
);

const KnowledgeItemRow: React.FC<{
  item: KnowledgeItem;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed' | 'rejected') => Promise<void>;
  onCorrectAssertion?: (assertionId: string, newValue: string) => Promise<void>;
  t: (key: string, options?: Record<string, unknown>) => string;
}> = ({ item, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onCorrectAssertion, t }) => {
  const safeCorrectionValue = coerceKnowledgeText(item.correctionValue);
  const [isOpen, setIsOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [correctionDraft, setCorrectionDraft] = useState(safeCorrectionValue);
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
  const trimmedCorrectionDraft = correctionDraft.trim();
  const currentCorrectionValue = safeCorrectionValue.trim();
  const canReview = Boolean(
    item.assertionId &&
    onSubmitAssertionFeedback &&
    (item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted')
  );
  const canCorrect = Boolean(canReview && onCorrectAssertion && item.correctionValue !== undefined);
  const isDetailsOpen = isOpen || isEditing;
  const technicalRows = [
    ...(item.technicalRows ?? []),
    item.updatedAt ? { label: t('memory.pages.knowledge.fields.updatedAt'), value: formatEventTime(item.updatedAt) } : null,
  ].filter((row): row is KnowledgeDetailRow => Boolean(row));
  const handleFeedback = (
    event: React.MouseEvent<HTMLButtonElement>,
    feedback: 'confirmed' | 'rejected'
  ) => {
    event.preventDefault();
    event.stopPropagation();
    if (item.assertionId && onSubmitAssertionFeedback) {
      void onSubmitAssertionFeedback(item.assertionId, feedback);
    }
  };
  const handleStartCorrection = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setCorrectionDraft(safeCorrectionValue);
    setIsEditing(true);
    setIsOpen(true);
  };
  const handleCancelCorrection = () => {
    setCorrectionDraft(safeCorrectionValue);
    setIsEditing(false);
  };
  const handleSaveCorrection = async () => {
    if (!item.assertionId || !onCorrectAssertion || !trimmedCorrectionDraft || trimmedCorrectionDraft === currentCorrectionValue) {
      return;
    }
    try {
      await onCorrectAssertion(item.assertionId, trimmedCorrectionDraft);
      setIsEditing(false);
    } catch {
      return;
    }
  };

  useEffect(() => {
    if (!isEditing) {
      setCorrectionDraft(safeCorrectionValue);
    }
  }, [isEditing, safeCorrectionValue]);

  return (
    <details
      className="group"
      open={isDetailsOpen}
      onToggle={(event) => {
        const nextOpen = event.currentTarget.open;
        setIsOpen(nextOpen);
        if (!nextOpen) {
          setIsEditing(false);
        }
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
          {canReview ? (
            <div className="flex shrink-0 justify-end gap-2">
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
              <Button
                variant="outline"
                size="sm"
                className="h-8 rounded-sm"
                disabled={actionLoading || item.userFeedback === 'rejected'}
                onClick={(event) => handleFeedback(event, 'rejected')}
              >
                <X className="mr-2 h-4 w-4" />
                {t('memory.l2.rejectAssertion')}
              </Button>
              {canCorrect ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-sm"
                  disabled={actionLoading}
                  onClick={handleStartCorrection}
                >
                  <Pencil className="mr-2 h-4 w-4" />
                  {t('memory.l2.correctAssertion')}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      </summary>
      <div className="border-t border-[hsl(var(--memory-divider)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.36)] px-4 py-3">
        {isEditing ? (
          <div className="mb-3 rounded-sm border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel)/0.68)] px-3 py-3">
            <label className="text-xs font-medium text-[hsl(var(--memory-muted))]" htmlFor={`${item.id}-correction-input`}>
              {t('memory.l2.correctionValue')}
            </label>
            <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto]">
              <Input
                id={`${item.id}-correction-input`}
                value={correctionDraft}
                placeholder={t('memory.l2.correctionPlaceholder')}
                onChange={(event) => setCorrectionDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    void handleSaveCorrection();
                  }
                  if (event.key === 'Escape') {
                    event.preventDefault();
                    handleCancelCorrection();
                  }
                }}
              />
              <Button
                variant="outline"
                size="sm"
                className="h-9 rounded-sm"
                disabled={actionLoading || !trimmedCorrectionDraft || trimmedCorrectionDraft === currentCorrectionValue}
                onClick={() => void handleSaveCorrection()}
              >
                {t('memory.l2.saveCorrection')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-9 rounded-sm"
                disabled={actionLoading}
                onClick={handleCancelCorrection}
              >
                {t('memory.l2.cancelCorrection')}
              </Button>
            </div>
          </div>
        ) : null}
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

const MetricCard: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <Card className={PANEL_CARD_CLASS}>
    <CardContent className="pt-5">
      <div className="text-[1.85rem] font-semibold tracking-[-0.03em] text-[hsl(var(--memory-title))]">{value}</div>
      <div className="mt-1 text-sm text-[hsl(var(--memory-muted))]">{label}</div>
    </CardContent>
  </Card>
);

const InfoCard: React.FC<{
  icon: React.ReactNode;
  title: string;
  emptyText: string;
  children: React.ReactNode;
}> = ({ icon, title, emptyText, children }) => {
  const items = React.Children.toArray(children).filter(Boolean);

  return (
    <Card className={PANEL_CARD_CLASS}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base text-[hsl(var(--memory-title))]">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <EmptyState copy={emptyText} />
        ) : (
          <div className="space-y-3">{items}</div>
        )}
      </CardContent>
    </Card>
  );
};

const BreakdownCard: React.FC<{
  title: string;
  emptyText: string;
  entries: Array<[string, number]>;
}> = ({ title, emptyText, entries }) => (
  <Card className={PANEL_CARD_CLASS}>
    <CardHeader>
      <CardTitle className="text-base text-[hsl(var(--memory-title))]">{title}</CardTitle>
    </CardHeader>
    <CardContent>
      {entries.length === 0 ? (
        <EmptyState copy={emptyText} />
      ) : (
        <div className="space-y-3">
          {entries.map(([label, value]) => (
            <div key={label} className={`${SOFT_PANEL_CLASS} flex items-center justify-between`}>
              <span className="font-medium text-[hsl(var(--memory-title))]">{label}</span>
              <Badge variant="secondary">{value}</Badge>
            </div>
          ))}
        </div>
      )}
    </CardContent>
  </Card>
);

const SummaryPill: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="inline-flex items-center rounded-full border border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.95)] px-3 py-1 text-xs text-[hsl(var(--memory-body))]">
    {children}
  </span>
);

const StatLine: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className={`${SOFT_PANEL_CLASS} flex items-center justify-between`}>
    <span>{label}</span>
    <span className="text-base font-semibold text-[hsl(var(--memory-title))]">{value}</span>
  </div>
);

const EmptyState: React.FC<{ copy: string }> = ({ copy }) => (
  <div className="rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.32)] px-4 py-3 text-sm leading-6 text-[hsl(var(--memory-muted))] shadow-[inset_0_0_0_1px_hsl(var(--memory-divider)/0.2)]">
    {copy}
  </div>
);

export default L2Tab;
