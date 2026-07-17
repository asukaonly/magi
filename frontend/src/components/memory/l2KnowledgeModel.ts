import type {
  L2Assertion,
  L2Relation,
  L2Snapshot,
} from '@/api/modules/memory';
import {
  type BuildEntityOverviewItemsParams,
  type BuildKnowledgeItemsParams,
  type EntityOverviewItem,
  type FilterKnowledgeItemsParams,
  type KnowledgeBaseGroup,
  type KnowledgeBaseGroupId,
  type KnowledgeItem,
  type KnowledgeStatusGroup,
  type MemoryTranslateFn,
} from './l2KnowledgeTypes';
import {
  buildCuratedProfileSummary,
  coerceKnowledgeEventIds,
  coerceKnowledgeText,
  getEntityOverviewKey,
  getEvidenceSummary,
  getReadableAssertionTitle,
  getReadableAssertionValue,
  getReadableEntityName,
  getReadableEntityType,
  getReadablePredicateLabel,
  getReadableTraitLabel,
  getRecordNumber,
  latestPositiveTimestamp,
  normalizeLabelKey,
  normalizeSearchText,
  textIncludesAny,
  translateWithFallback,
} from './l2KnowledgeModelHelpers';

export {
  ENTITY_KNOWLEDGE_PREVIEW_LIMIT,
  type EntityOverviewItem,
  type KnowledgeBaseGroup,
  type KnowledgeBaseGroupId,
  type KnowledgeCorrectionAction,
  type KnowledgeDetailRow,
  type KnowledgeItem,
  type KnowledgeStatusGroup,
  type MemoryTranslateFn,
} from './l2KnowledgeTypes';
export {
  buildSelfEntityAliasSet,
  coerceKnowledgeEventIds,
  coerceKnowledgeText,
  formatConfidence,
  formatEventTime,
  getReadableAssertionValue,
  getReadableTraitLabel,
  translateWithFallback,
} from './l2KnowledgeModelHelpers';

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
      expectedUpdatedAt: assertion.updated_at,
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
