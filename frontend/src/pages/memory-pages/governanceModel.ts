import type {
  L0Session,
  L1Event,
  L2Assertion,
  L2Entity,
  L2Relation,
  L2Snapshot,
  L2Statistics,
  L3Summary,
  L4Skill,
  MemoryStatistics,
} from '@/api/modules/memory';

export type GovernanceTab = 'objects' | 'tasks' | 'manual' | 'forget' | 'diagnostics';
export type MemoryLayerId = 'l0' | 'l1' | 'l2' | 'l3' | 'l4';
export type MaintenanceCategoryId =
  | 'sessions'
  | 'events'
  | 'entities'
  | 'assertions'
  | 'relations'
  | 'snapshots'
  | 'summaries'
  | 'skills';

export interface LayerRecord {
  id: string;
  layer: MemoryLayerId;
  categoryId: MaintenanceCategoryId;
  categoryLabel: string;
  title: string;
  type: string;
  source: string;
  status: string;
  updatedAt?: number | null;
  evidenceCount?: number | null;
  summary?: string | null;
  related?: string[];
  impact?: Array<{ label: string; value: number | string }>;
}

export interface LayerSummary {
  id: MaintenanceCategoryId;
  label: string;
  description: string;
  count: number;
  status: string;
  tone: 'ok' | 'warn' | 'danger';
  records: LayerRecord[];
}

type GovernanceStatistics = Partial<Omit<MemoryStatistics, 'l0' | 'l1' | 'l2' | 'l3' | 'l4' | 'attention'>> & {
  l0?: Partial<MemoryStatistics['l0']>;
  l1?: Partial<MemoryStatistics['l1']>;
  l2?: Partial<MemoryStatistics['l2']>;
  l3?: Partial<MemoryStatistics['l3']>;
  l4?: Partial<MemoryStatistics['l4']>;
  attention?: Partial<NonNullable<MemoryStatistics['attention']>>;
};

export interface GovernanceMemorySnapshot {
  stats: GovernanceStatistics;
  l0Sessions?: L0Session[] | null;
  l0Total?: number | null;
  l1Events?: L1Event[] | null;
  l1Total?: number | null;
  l2Assertions?: L2Assertion[] | null;
  l2AssertionsTotal?: number | null;
  l2Relations?: L2Relation[] | null;
  l2RelationsTotal?: number | null;
  l2Entities?: L2Entity[] | null;
  l2EntitiesTotal?: number | null;
  l2Snapshots?: L2Snapshot[] | null;
  l2SnapshotsTotal?: number | null;
  l2Stats?: Partial<L2Statistics> | null;
  l3Summaries?: L3Summary[] | null;
  l3Total?: number | null;
  l4Skills?: L4Skill[] | null;
  l4Total?: number | null;
}

export type GovernanceLabelFn = (key: string, defaultValue: string, values?: Record<string, unknown>) => string;

export const RECORD_PAGE_SIZE = 20;

const toList = <T,>(value: T[] | null | undefined): T[] => (Array.isArray(value) ? value : []);

export const toFiniteNumber = (value: unknown, fallback = 0): number => {
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const toOptionalNumber = (value: unknown): number | null => {
  const numeric = toFiniteNumber(value, Number.NaN);
  return Number.isFinite(numeric) ? numeric : null;
};

const formatDecimal = (value: unknown, digits = 2): string => toFiniteNumber(value).toFixed(digits);

export const formatCount = (value: unknown): string => new Intl.NumberFormat().format(Math.max(0, toFiniteNumber(value)));

const isOpaqueTraitSegment = (value: string): boolean => /^[a-f0-9]{8,}$/i.test(value);

export const formatTime = (timestamp?: number | null): string => {
  if (!timestamp) return '-';
  const normalized = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
  return new Intl.DateTimeFormat(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(normalized));
};

const clampText = (value: string | null | undefined, fallback: string, max = 96): string => {
  const cleaned = String(value || '').replace(/\s+/g, ' ').trim();
  if (!cleaned) return fallback;
  return cleaned.length > max ? `${cleaned.slice(0, max - 1)}…` : cleaned;
};

const safeText = (value: unknown, fallback: string): string => {
  const cleaned = String(value ?? '').trim();
  return cleaned || fallback;
};

function getAssertionEntityName(
  entityId: unknown,
  entityNamesById: Map<string, string>,
  label: GovernanceLabelFn
): string {
  const id = safeText(entityId, '');
  if (!id) return label('assertions.unknownEntity', '未知对象');
  const knownName = entityNamesById.get(id);
  if (knownName) return knownName;
  if (id === 'user' || id === 'user:self' || id.startsWith('user:')) return label('assertions.userEntity', '用户');
  return id;
}

function getAssertionTraitLabel(
  traitName: unknown,
  label: GovernanceLabelFn
): string {
  const rawTrait = safeText(traitName, '');
  if (!rawTrait) return label('assertions.unknownTrait', '某项判断');

  const normalized = rawTrait.toLowerCase();
  const directLabels = new Map<string, string>([
    ['communication.response_style.preferred', label('assertions.traits.communicationResponseStylePreferred', '沟通风格偏好')],
    ['response_style.preferred', label('assertions.traits.responseStylePreferred', '回应风格偏好')],
    ['interest', label('assertions.traits.interest', '兴趣')],
    ['preference', label('assertions.traits.preference', '偏好')],
    ['preferences', label('assertions.traits.preference', '偏好')],
    ['identity', label('assertions.traits.identity', '身份')],
    ['routine', label('assertions.traits.routine', '习惯')],
    ['location', label('assertions.traits.location', '地点')],
    ['project', label('assertions.traits.project', '项目')],
    ['tool', label('assertions.traits.tool', '工具')],
    ['judgment', label('assertions.traits.judgment', '判断')],
    ['judgement', label('assertions.traits.judgment', '判断')],
  ]);
  const direct = directLabels.get(normalized);
  if (direct) return direct;

  const parts = rawTrait.split('.').map((part) => part.trim()).filter(Boolean);
  const prefix = parts[0]?.toLowerCase();
  const prefixLabels = new Map<string, string>([
    ['interest', label('assertions.traits.interest', '兴趣')],
    ['preference', label('assertions.traits.preference', '偏好')],
    ['preferences', label('assertions.traits.preference', '偏好')],
    ['identity', label('assertions.traits.identity', '身份')],
    ['routine', label('assertions.traits.routine', '习惯')],
    ['location', label('assertions.traits.location', '地点')],
    ['project', label('assertions.traits.project', '项目')],
    ['tool', label('assertions.traits.tool', '工具')],
    ['judgment', label('assertions.traits.judgment', '判断')],
    ['judgement', label('assertions.traits.judgment', '判断')],
  ]);
  const prefixLabel = prefixLabels.get(prefix);
  if (prefixLabel && parts.length > 1) return prefixLabel;

  const segmentLabels = new Map<string, string>([
    ['communication', label('assertions.traitSegments.communication', '沟通')],
    ['response_style', label('assertions.traitSegments.responseStyle', '回应风格')],
    ['preferred', label('assertions.traitSegments.preferred', '偏好')],
    ['preference', label('assertions.traitSegments.preference', '偏好')],
    ['preferences', label('assertions.traitSegments.preference', '偏好')],
    ['identity', label('assertions.traitSegments.identity', '身份')],
    ['routine', label('assertions.traitSegments.routine', '习惯')],
    ['location', label('assertions.traitSegments.location', '地点')],
    ['project', label('assertions.traitSegments.project', '项目')],
    ['tool', label('assertions.traitSegments.tool', '工具')],
    ['judgment', label('assertions.traitSegments.judgment', '判断')],
    ['judgement', label('assertions.traitSegments.judgment', '判断')],
  ]);
  const readableParts = parts
    .filter((part) => !isOpaqueTraitSegment(part))
    .map((part) => segmentLabels.get(part.toLowerCase()) ?? part.replace(/[_-]+/g, ' '));

  return readableParts.length ? readableParts.join(' · ') : rawTrait;
}

function getAssertionStatement(
  entityName: string,
  traitLabel: string,
  traitValue: unknown,
  label: GovernanceLabelFn
): string {
  const value = safeText(traitValue, '');
  if (!value) {
    return label('assertions.statementWithoutValue', '{{entity}}的{{trait}}', { entity: entityName, trait: traitLabel });
  }
  return label('assertions.statementWithValue', '{{entity}}的{{trait}}是{{value}}', {
    entity: entityName,
    trait: traitLabel,
    value,
  });
}

export const getStatusToneClass = (tone: LayerSummary['tone']) => {
  if (tone === 'danger') {
    return 'bg-red-50 text-red-700 ring-red-200';
  }
  if (tone === 'warn') {
    return 'bg-amber-50 text-amber-700 ring-amber-200';
  }
  return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
};

export const getRowStatusClass = (status: string) => {
  const normalized = status.toLowerCase();
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('异常') || normalized.includes('冲突')) {
    return 'text-red-600';
  }
  if (normalized.includes('pending') || normalized.includes('待') || normalized.includes('queued')) {
    return 'text-amber-600';
  }
  return 'text-emerald-600';
};

export function buildLayerSummaries(memory: GovernanceMemorySnapshot, label: GovernanceLabelFn): LayerSummary[] {
  const l0Sessions = toList(memory.l0Sessions);
  const l1Events = toList(memory.l1Events);
  const l2Assertions = toList(memory.l2Assertions);
  const l2Relations = toList(memory.l2Relations);
  const l2Entities = toList(memory.l2Entities);
  const l2Snapshots = toList(memory.l2Snapshots);
  const l3Summaries = toList(memory.l3Summaries);
  const l4Skills = toList(memory.l4Skills);
  const stats = memory.stats;
  const categoryLabels: Record<MaintenanceCategoryId, string> = {
    sessions: label('categories.sessions', '会话工作台'),
    events: label('categories.events', '原始事件'),
    entities: label('categories.entities', '实体'),
    assertions: label('categories.assertions', '断言'),
    relations: label('categories.relations', '关系图谱'),
    snapshots: label('categories.snapshots', '状态快照'),
    summaries: label('categories.summaries', '经历总结'),
    skills: label('categories.skills', '工具技能'),
  };
  const l2EntityEvidence = (entityId: string) => (
    l2Assertions.filter((assertion) => assertion.entity_id === entityId).length +
    l2Relations.filter((relation) => relation.subject_id === entityId || relation.object_id === entityId).length
  );
  const entityNamesById = new Map<string, string>();
  l2Entities.forEach((entity) => {
    const entityId = safeText(entity.entity_id, '');
    if (entityId) {
      entityNamesById.set(entityId, safeText(entity.canonical_name, entityId));
    }
  });

  const l0Records: LayerRecord[] = l0Sessions.map((session) => ({
    id: safeText(session.short_session_id || session.session_id, label('fallbacks.unknownRecord', '未知记录')),
    layer: 'l0',
    categoryId: 'sessions',
    categoryLabel: categoryLabels.sessions,
    title: clampText(session.display_title, label('fallbacks.untitledSession', '未命名会话'), 64),
    type: label('recordTypes.session', '会话'),
    source: session.workspace_path ? label('sources.workspace', '工作区') : label('sources.chat', '对话'),
    status: safeText(session.status, label('statuses.unknown', '未知')),
    updatedAt: session.last_active_at,
    evidenceCount: toOptionalNumber(session.message_count),
    summary: session.last_message_preview || session.last_user_message_preview || null,
    impact: [
      { label: label('impact.goals', '目标'), value: toFiniteNumber(session.goal_count) },
      { label: label('impact.entities', '实体'), value: toFiniteNumber(session.entity_count) },
      { label: label('impact.tactics', '策略'), value: toFiniteNumber(session.tactic_count) },
    ],
  }));

  const l1Records: LayerRecord[] = l1Events.map((event) => ({
    id: safeText(event.event_id, label('fallbacks.unknownRecord', '未知记录')),
    layer: 'l1',
    categoryId: 'events',
    categoryLabel: categoryLabels.events,
    title: clampText(event.content, safeText(event.event_type, label('recordTypes.event', '事件')), 88),
    type: safeText(event.event_type, label('recordTypes.event', '事件')),
    source: safeText(event.source, label('sources.unknown', '未知来源')),
    status: event.deleted_at ? label('statuses.deleted', '已删除') : safeText(event.embedding_status, label('statuses.valid', '有效')),
    updatedAt: event.timestamp || event.created_at,
    evidenceCount: toOptionalNumber(event.embedding_chunk_count),
    summary: event.content,
    related: [
      event.session_id ? `${label('fields.session', '会话')} ${event.session_id}` : '',
      event.turn_id ? `${label('fields.turn', '回合')} ${event.turn_id}` : '',
    ].filter(Boolean),
    impact: [
      { label: label('impact.importance', '重要度'), value: formatDecimal(event.importance_score) },
      { label: label('impact.cognition', '进入认知'), value: event.cognition_eligible ? label('yes', '是') : label('no', '否') },
    ],
  }));

  const l2EntityRecords: LayerRecord[] = l2Entities.map((entity) => {
    const aliases = toList(entity.aliases);
    const evidenceCount = l2EntityEvidence(entity.entity_id);
    return {
      id: safeText(entity.entity_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l2',
      categoryId: 'entities',
      categoryLabel: categoryLabels.entities,
      title: `${label('recordTypes.entity', '实体')}：${safeText(entity.canonical_name, label('fallbacks.unknownRecord', '未知记录'))}`,
      type: label('recordTypes.entity', '实体'),
      source: safeText(entity.entity_type, label('sources.unknown', '未知来源')),
      status: label('statuses.valid', '有效'),
      updatedAt: entity.updated_at,
      evidenceCount,
      summary: aliases.length ? `${label('fields.aliases', '别名')}：${aliases.join('、')}` : null,
      related: aliases,
      impact: [
        { label: label('impact.relations', '关系'), value: l2Relations.filter((item) => item.subject_id === entity.entity_id || item.object_id === entity.entity_id).length },
        { label: label('impact.assertions', '断言'), value: l2Assertions.filter((item) => item.entity_id === entity.entity_id).length },
        { label: label('impact.snapshots', '快照'), value: l2Snapshots.filter((item) => item.entity_id === entity.entity_id).length },
      ],
    };
  });

  const l2AssertionRecords: LayerRecord[] = l2Assertions.map((assertion) => {
    const evidenceEvents = toList(assertion.evidence_events);
    const entityName = getAssertionEntityName(assertion.entity_id, entityNamesById, label);
    const traitLabel = getAssertionTraitLabel(assertion.trait_name, label);
    const traitValue = safeText(assertion.trait_value, '');
    return {
      id: safeText(assertion.assertion_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l2',
      categoryId: 'assertions',
      categoryLabel: categoryLabels.assertions,
      title: getAssertionStatement(entityName, traitLabel, traitValue, label),
      type: label('recordTypes.assertion', '断言'),
      source: safeText(assertion.source_domain, label('sources.unknown', '未知来源')),
      status: safeText(assertion.validation_state, label('statuses.unknown', '未知')),
      updatedAt: assertion.last_validated_at,
      evidenceCount: evidenceEvents.length,
      summary: traitValue
        ? label('assertions.summaryWithValue', '{{trait}}：{{value}}', { trait: traitLabel, value: traitValue })
        : label('assertions.summaryWithoutValue', '{{trait}}：未记录具体值', { trait: traitLabel }),
      related: evidenceEvents,
      impact: [
        { label: label('impact.confidence', '可信度'), value: formatDecimal(assertion.confidence_score) },
        { label: label('impact.volatility', '波动'), value: formatDecimal(assertion.volatility_index) },
      ],
    };
  });

  const l2RelationRecords: LayerRecord[] = l2Relations.map((relation) => {
    const evidenceEventIds = toList(relation.evidence_event_ids);
    return {
      id: safeText(relation.triple_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l2',
      categoryId: 'relations',
      categoryLabel: categoryLabels.relations,
      title: `${label('recordTypes.relation', '关系')}：${safeText(relation.subject_id, '?')} ${safeText(relation.predicate, '?')} ${safeText(relation.object_id, '?')}`,
      type: label('recordTypes.relation', '关系'),
      source: safeText(relation.subject_type, label('sources.unknown', '未知来源')),
      status: safeText(relation.status, label('statuses.unknown', '未知')),
      updatedAt: relation.updated_at || relation.last_observed_at,
      evidenceCount: evidenceEventIds.length,
      summary: `${safeText(relation.subject_type, '?')} → ${safeText(relation.object_type, '?')}`,
      related: evidenceEventIds,
      impact: [
        { label: label('impact.observations', '观察'), value: toFiniteNumber(relation.observation_count) },
        { label: label('impact.confidence', '可信度'), value: formatDecimal(relation.confidence) },
      ],
    };
  });

  const l2SnapshotRecords: LayerRecord[] = l2Snapshots.map((snapshot) => ({
    id: safeText(snapshot.snapshot_id, label('fallbacks.unknownRecord', '未知记录')),
    layer: 'l2',
    categoryId: 'snapshots',
    categoryLabel: categoryLabels.snapshots,
    title: `${label('recordTypes.snapshot', '快照')}：${safeText(snapshot.entity_id, label('fallbacks.unknownRecord', '未知记录'))}`,
    type: label('recordTypes.snapshot', '快照'),
    source: safeText(snapshot.entity_type, label('sources.unknown', '未知来源')),
    status: label('statuses.valid', '有效'),
    updatedAt: snapshot.last_updated_at,
    evidenceCount: toOptionalNumber(snapshot.interaction_count),
    summary: snapshot.current_mood || null,
    impact: [
      { label: label('impact.engagement', '参与度'), value: toOptionalNumber(snapshot.current_engagement) ?? '-' },
      { label: label('impact.stress', '压力'), value: toOptionalNumber(snapshot.current_stress_level) ?? '-' },
    ],
  }));

  const l3Records: LayerRecord[] = l3Summaries.map((summary) => {
    const keyTopics = toList(summary.key_topics);
    return {
      id: safeText(summary.summary_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l3',
      categoryId: 'summaries',
      categoryLabel: categoryLabels.summaries,
      title: clampText(summary.content, safeText(summary.summary_category, label('recordTypes.summary', '总结')), 88),
      type: safeText(summary.summary_category, label('recordTypes.summary', '总结')),
      source: safeText(summary.summary_type, label('sources.unknown', '未知来源')),
      status: safeText(summary.review_state, label('statuses.generated', '已生成')),
      updatedAt: summary.updated_at || summary.created_at,
      evidenceCount: toOptionalNumber(summary.source_event_count),
      summary: summary.content,
      related: keyTopics,
      impact: [
        { label: label('impact.events', '事件'), value: toFiniteNumber(summary.source_event_count) },
        { label: label('impact.topics', '主题'), value: keyTopics.length },
      ],
    };
  });

  const l4Records: LayerRecord[] = l4Skills.map((skill) => ({
    id: safeText(skill.skill_id, label('fallbacks.unknownRecord', '未知记录')),
    layer: 'l4',
    categoryId: 'skills',
    categoryLabel: categoryLabels.skills,
    title: safeText(skill.skill_name, label('fallbacks.untitledSkill', '未命名技能')),
    type: safeText(skill.skill_category, label('recordTypes.skill', '技能')),
    source: label('sources.procedure', '程序记忆'),
    status: safeText(skill.circuit_breaker_state, label('statuses.unknown', '未知')),
    updatedAt: skill.last_used_at,
    evidenceCount: toOptionalNumber(skill.total_attempts),
    summary: label('skillSummary', '成功 {{success}} / 失败 {{failure}}', {
      success: formatCount(skill.success_count),
      failure: formatCount(skill.failure_count),
    }),
    impact: [
      { label: label('impact.proficiency', '熟练度'), value: formatDecimal(skill.proficiency) },
      { label: label('impact.successRate', '成功率'), value: `${Math.round(toFiniteNumber(skill.success_rate) * 100)}%` },
    ],
  }));

  const pendingAssertions = stats.attention?.pending_assertions ?? 0;
  const openBreakers = stats.l4?.open_circuit_breakers ?? 0;

  return [
    {
      id: 'sessions',
      label: categoryLabels.sessions,
      description: label('categories.sessionsDescription', '当前会话、目标和临时策略'),
      count: memory.l0Total || stats.l0?.active_sessions || l0Records.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l0Records,
    },
    {
      id: 'events',
      label: categoryLabels.events,
      description: label('categories.eventsDescription', '来源事件、片段和观察'),
      count: memory.l1Total || stats.l1?.event_count || l1Records.length,
      status: label('statuses.stable', '稳定'),
      tone: 'ok',
      records: l1Records,
    },
    {
      id: 'entities',
      label: categoryLabels.entities,
      description: label('categories.entitiesDescription', '人物、地点、项目和对象'),
      count: memory.l2EntitiesTotal || l2EntityRecords.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l2EntityRecords,
    },
    {
      id: 'assertions',
      label: categoryLabels.assertions,
      description: label('categories.assertionsDescription', '偏好、判断和待确认事实'),
      count: memory.l2AssertionsTotal || l2AssertionRecords.length,
      status: pendingAssertions > 0 ? label('statuses.pendingCount', '待确认 {{count}}', { count: pendingAssertions }) : label('statuses.healthy', '健康'),
      tone: pendingAssertions > 0 ? 'warn' : 'ok',
      records: l2AssertionRecords,
    },
    {
      id: 'relations',
      label: categoryLabels.relations,
      description: label('categories.relationsDescription', '实体之间的关系和连接'),
      count: memory.l2RelationsTotal || l2RelationRecords.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l2RelationRecords,
    },
    {
      id: 'snapshots',
      label: categoryLabels.snapshots,
      description: label('categories.snapshotsDescription', '状态、情绪和近期上下文'),
      count: memory.l2SnapshotsTotal || l2SnapshotRecords.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l2SnapshotRecords,
    },
    {
      id: 'summaries',
      label: categoryLabels.summaries,
      description: label('categories.summariesDescription', '章节、阶段和周期总结'),
      count: memory.l3Total || stats.l3?.summary_count || l3Records.length,
      status: label('statuses.generated', '已生成'),
      tone: 'ok',
      records: l3Records,
    },
    {
      id: 'skills',
      label: categoryLabels.skills,
      description: label('categories.skillsDescription', '技能、流程和失败保护'),
      count: memory.l4Total || stats.l4?.skill_count || l4Records.length,
      status: openBreakers > 0 ? label('statuses.breakers', '熔断 {{count}}', { count: openBreakers }) : label('statuses.healthy', '健康'),
      tone: openBreakers > 0 ? 'danger' : 'ok',
      records: l4Records,
    },
  ];
}

export function getRecordListCopy(
  record: LayerRecord,
  label: GovernanceLabelFn
) {
  if (record.categoryId === 'assertions') {
    return {
      title: clampText(record.title, label('fallbacks.unknownRecord', '未知记录'), 88),
      subtitle: record.summary ? clampText(record.summary, record.type, 88) : null,
    };
  }

  if (record.categoryId === 'events') {
    return {
      title: record.title,
      subtitle: record.summary && record.summary !== record.title ? clampText(record.summary, record.type, 88) : record.type,
    };
  }

  if (record.categoryId === 'entities') {
    return {
      title: record.title,
      subtitle: record.summary || label('objects.recordSubtitle.entity', '{{type}} · {{source}}', { type: record.type, source: record.source }),
    };
  }

  if (record.categoryId === 'relations') {
    return {
      title: record.title,
      subtitle: record.summary || label('objects.recordSubtitle.relation', '{{source}} 关系', { source: record.source }),
    };
  }

  return {
    title: record.title,
    subtitle: record.summary || record.categoryLabel,
  };
}
