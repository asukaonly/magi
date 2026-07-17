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
  sourceKind?: string | null;
  sourceItemId?: string | null;
  status: string;
  updatedAt?: number | null;
  evidenceCount?: number | null;
  summary?: string | null;
  related?: string[];
  impact?: Array<{ label: string; value: number | string }>;
  listCells?: Record<string, { value: number | string; tone?: 'default' | 'muted' | 'status' }>;
  details?: Array<{ label: string; value: number | string }>;
      correction?:
    | {
        kind: 'assertion';
        correctable: boolean;
        currentValue: string;
        expectedUpdatedAt?: number;
      }
    | {
        kind: 'edge';
        correctable: boolean;
        expectedUpdatedAt?: number;
        relationship: {
          subjectId: string;
          subjectType: string;
          subjectName: string;
          predicate: string;
          predicateLabel: string;
          objectId: string;
          objectType: string;
          objectName: string;
        };
      };
}

export interface LayerTableColumn {
  id: string;
  label: string;
  width: number;
  align?: 'left' | 'right';
}

export interface LayerSummary {
  id: MaintenanceCategoryId;
  label: string;
  description: string;
  count: number;
  status: string;
  tone: 'ok' | 'warn' | 'danger';
  records: LayerRecord[];
  tableColumns: LayerTableColumn[];
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

const NON_CURRENT_ASSERTION_STATUSES = new Set([
  'archived',
  'expired',
  'invalidated',
  'shadow',
  'superseded',
  'user_rejected',
]);

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

const humanizeIdentifier = (value: unknown, fallback: string): string => {
  const raw = safeText(value, '');
  if (!raw) return fallback;
  if (raw === 'user' || raw === 'user:self' || raw.startsWith('user:')) return fallback;

  const withoutPrefix = raw.replace(/^(?:ent(?:ity)?|person|place|tool|group)[:_-]/i, '');
  const parts = withoutPrefix
    .split(/[:/_-]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const readableParts = parts.length > 1
    ? parts.filter((part) => !isOpaqueTraitSegment(part))
    : parts;
  return readableParts.join(' ') || fallback;
};

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

const formatPeriod = (start?: number | null, end?: number | null): string => {
  if (!start && !end) return '-';
  const formatter = new Intl.DateTimeFormat(undefined, { month: '2-digit', day: '2-digit' });
  const normalize = (value: number) => new Date(value > 10_000_000_000 ? value : value * 1000);
  if (!start) return formatter.format(normalize(end as number));
  if (!end || start === end) return formatter.format(normalize(start));
  return `${formatter.format(normalize(start))} - ${formatter.format(normalize(end))}`;
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
  return humanizeIdentifier(id, label('assertions.unknownEntity', '未知对象'));
}

function getRelationPredicateLabel(predicate: unknown, label: GovernanceLabelFn): string {
  const raw = safeText(predicate, '');
  const normalized = raw.toUpperCase();
  const knownPredicates = new Map<string, string>([
    ['USES', label('relations.predicates.uses', '使用')],
    ['VISITED', label('relations.predicates.visited', '去过')],
    ['LIKES', label('relations.predicates.likes', '喜欢')],
    ['WORKS_ON', label('relations.predicates.worksOn', '参与')],
    ['LOCATED_IN', label('relations.predicates.locatedIn', '位于')],
    ['MEMBER_OF', label('relations.predicates.memberOf', '属于')],
    ['RELATED_TO', label('relations.predicates.relatedTo', '关联')],
    ['HAS', label('relations.predicates.has', '拥有')],
    ['IS', label('relations.predicates.is', '是')],
    ['VIEWED', label('relations.predicates.viewed', '浏览了')],
    ['BROWSED', label('relations.predicates.viewed', '浏览了')],
    ['WATCHED', label('relations.predicates.watched', '看过')],
    ['OPENED', label('relations.predicates.opened', '打开过')],
    ['SEARCHED', label('relations.predicates.searched', '搜索过')],
    ['CREATED', label('relations.predicates.created', '创建了')],
    ['OWNS', label('relations.predicates.owns', '拥有')],
    ['WORKS_AT', label('relations.predicates.worksAt', '任职于')],
    ['MENTIONED', label('relations.predicates.mentioned', '提到过')],
    ['INTERACTED_WITH', label('relations.predicates.interactedWith', '互动过')],
    ['LISTENED_TO', label('relations.predicates.listenedTo', '听过')],
    ['PLAYED', label('relations.predicates.played', '播放过')],
  ]);
  return knownPredicates.get(normalized) || raw.replace(/[_-]+/g, ' ').toLowerCase() || label('relations.unknownPredicate', '关联');
}

function getRelationEntityTypeLabel(entityType: unknown, label: GovernanceLabelFn): string {
  const raw = safeText(entityType, label('relations.entityTypes.unknown', '未知'));
  const normalized = raw.toLowerCase();
  const knownTypes = new Map<string, string>([
    ['user', label('relations.entityTypes.user', '用户')],
    ['person', label('relations.entityTypes.person', '人物')],
    ['place', label('relations.entityTypes.place', '地点')],
    ['organization', label('relations.entityTypes.organization', '组织')],
    ['org', label('relations.entityTypes.organization', '组织')],
    ['project', label('relations.entityTypes.project', '项目')],
    ['tool', label('relations.entityTypes.tool', '工具')],
    ['group', label('relations.entityTypes.group', '群组')],
    ['event', label('relations.entityTypes.event', '事件')],
    ['media', label('relations.entityTypes.media', '内容')],
    ['hardware', label('relations.entityTypes.hardware', '硬件')],
    ['software', label('relations.entityTypes.software', '软件')],
    ['website', label('relations.entityTypes.website', '网站')],
    ['domain', label('relations.entityTypes.website', '网站')],
    ['other', label('relations.entityTypes.other', '其他')],
  ]);
  return knownTypes.get(normalized) || raw.replace(/[_-]+/g, ' ');
}

function getReadableStatus(value: unknown, label: GovernanceLabelFn, fallback?: string): string {
  const raw = safeText(value, '');
  if (!raw) return fallback || label('statuses.unknown', '未知');
  const normalized = raw.toLowerCase();
  const knownStatuses = new Map<string, string>([
    ['active', label('statuses.active', '有效')],
    ['valid', label('statuses.valid', '有效')],
    ['stable', label('statuses.stable', '稳定')],
    ['corroborated', label('statuses.corroborated', '已验证')],
    ['verified', label('statuses.corroborated', '已验证')],
    ['expired', label('statuses.expired', '已过期')],
    ['archived', label('statuses.archived', '已归档')],
    ['deprecated', label('statuses.superseded', '已替代')],
    ['superseded', label('statuses.superseded', '已替代')],
    ['conflicted', label('statuses.conflicted', '有冲突')],
    ['invalidated', label('statuses.invalidated', '已失效')],
    ['user_rejected', label('statuses.userRejected', '已否定')],
    ['shadow', label('statuses.shadow', '待确认')],
    ['pending', label('statuses.pending', '待处理')],
    ['queued', label('statuses.pending', '待处理')],
    ['invalid', label('statuses.invalid', '无效')],
    ['inactive', label('statuses.invalid', '无效')],
    ['rejected', label('statuses.invalid', '无效')],
    ['generated', label('statuses.generated', '已生成')],
    ['enabled', label('statuses.enabled', '已启用')],
    ['disabled', label('statuses.disabled', '已停用')],
    ['open', label('statuses.open', '已触发')],
    ['closed', label('statuses.closed', '正常')],
    ['healthy', label('statuses.healthy', '健康')],
    ['completed', label('statuses.completed', '已完成')],
    ['complete', label('statuses.completed', '已完成')],
    ['ready', label('statuses.ready', '就绪')],
  ]);
  return knownStatuses.get(normalized) || raw.replace(/[_-]+/g, ' ');
}

function getReadableSource(value: unknown, label: GovernanceLabelFn): string {
  const raw = safeText(value, label('sources.unknown', '未知来源'));
  const normalized = raw.toLowerCase();
  const knownSources = new Map<string, string>([
    ['chat', label('sources.chat', '对话')],
    ['conversation', label('sources.chat', '对话')],
    ['chrome_history', label('sources.chromeHistory', 'Chrome 浏览记录')],
    ['screenshot_timeline', label('sources.screenshotTimeline', '屏幕记录')],
    ['external_activity', label('sources.externalActivity', '外部活动')],
    ['calendar', label('sources.calendar', '日历')],
    ['photo_library', label('sources.photoLibrary', '照片')],
    ['git_activity', label('sources.gitActivity', '代码活动')],
    ['netease_music', label('sources.neteaseMusic', '网易云音乐')],
    ['screen_time', label('sources.screenTime', '屏幕使用')],
    ['system_media', label('sources.systemMedia', '媒体播放')],
    ['terminal_history', label('sources.terminalHistory', '终端记录')],
    ['coding_agent_history', label('sources.codingAgentHistory', '编程助手记录')],
  ]);
  return knownSources.get(normalized) || raw.replace(/[_-]+/g, ' ');
}

function getReadableEventType(value: unknown, label: GovernanceLabelFn): string {
  const raw = safeText(value, label('recordTypes.event', '事件'));
  const normalized = raw.toUpperCase().replace(/[.-]+/g, '_');
  const knownTypes = new Map<string, string>([
    ['SENSOR_EVENT', label('eventTypes.sensorEvent', '采集事件')],
    ['CHAT_MESSAGE', label('eventTypes.chatMessage', '对话消息')],
    ['TOOL_CALL', label('eventTypes.toolCall', '工具调用')],
    ['TOOL_RESULT', label('eventTypes.toolResult', '工具结果')],
    ['EXTERNAL_ACTIVITY', label('eventTypes.externalActivity', '外部活动')],
  ]);
  return knownTypes.get(normalized) || raw.replace(/[._-]+/g, ' ');
}

function getRelationEndpointName(
  entityId: unknown,
  entityType: unknown,
  entityNamesById: Map<string, string>,
  label: GovernanceLabelFn
): string {
  const name = getAssertionEntityName(entityId, entityNamesById, label);
  const rawType = safeText(entityType, '');
  if (!rawType) return name;

  const escapedType = rawType.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const withoutRepeatedType = name.replace(new RegExp(`^${escapedType}(?:\\s+|[:/_-]+)`, 'i'), '').trim();
  return withoutRepeatedType || name;
}

function getSnapshotPreview(snapshot: L2Snapshot, label: GovernanceLabelFn): string {
  const mood = safeText(snapshot.current_mood, '');
  if (mood) return mood;
  const candidates = [snapshot.current_context, snapshot.preferences, snapshot.core_traits];
  for (const candidate of candidates) {
    for (const value of Object.values(candidate || {})) {
      if (typeof value === 'string' && value.trim()) return clampText(value, '', 64);
      if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    }
  }
  return label('snapshots.noCurrentState', '暂无状态摘要');
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
  const tableColumns: Record<MaintenanceCategoryId, LayerTableColumn[]> = {
    sessions: [
      { id: 'updatedAt', label: label('fields.lastActive', '最近活跃'), width: 118 },
      { id: 'evidenceCount', label: label('fields.messages', '消息'), width: 68, align: 'right' },
      { id: 'status', label: label('fields.status', '状态'), width: 88 },
    ],
    events: [
      { id: 'source', label: label('fields.source', '来源'), width: 112 },
      { id: 'type', label: label('fields.eventType', '事件类型'), width: 118 },
      { id: 'updatedAt', label: label('fields.occurredAt', '发生时间'), width: 118 },
      { id: 'status', label: label('fields.status', '状态'), width: 86 },
    ],
    entities: [
      { id: 'entityType', label: label('fields.entityType', '对象类型'), width: 106 },
      { id: 'evidenceCount', label: label('fields.visibleRelated', '当前关联'), width: 82, align: 'right' },
      { id: 'updatedAt', label: label('fields.updatedAt', '更新时间'), width: 118 },
      { id: 'status', label: label('fields.status', '状态'), width: 82 },
    ],
    assertions: [
      { id: 'source', label: label('fields.source', '来源'), width: 112 },
      { id: 'evidenceCount', label: label('fields.evidenceCount', '证据'), width: 70, align: 'right' },
      { id: 'updatedAt', label: label('fields.updatedAt', '更新时间'), width: 118 },
      { id: 'status', label: label('fields.status', '状态'), width: 96 },
    ],
    relations: [
      { id: 'relationType', label: label('fields.relationType', '对象类型'), width: 118 },
      { id: 'observations', label: label('fields.observations', '观察'), width: 68, align: 'right' },
      { id: 'updatedAt', label: label('fields.updatedAt', '更新时间'), width: 118 },
      { id: 'status', label: label('fields.status', '状态'), width: 96 },
    ],
    snapshots: [
      { id: 'state', label: label('fields.currentState', '当前状态'), width: 118 },
      { id: 'evidenceCount', label: label('fields.interactions', '互动'), width: 68, align: 'right' },
      { id: 'updatedAt', label: label('fields.updatedAt', '更新时间'), width: 118 },
      { id: 'status', label: label('fields.status', '状态'), width: 82 },
    ],
    summaries: [
      { id: 'period', label: label('fields.period', '覆盖时间'), width: 118 },
      { id: 'evidenceCount', label: label('fields.events', '事件'), width: 68, align: 'right' },
      { id: 'updatedAt', label: label('fields.updatedAt', '更新时间'), width: 118 },
      { id: 'status', label: label('fields.status', '状态'), width: 86 },
    ],
    skills: [
      { id: 'skillType', label: label('fields.skillType', '技能类型'), width: 110 },
      { id: 'successRate', label: label('fields.successRate', '成功率'), width: 74, align: 'right' },
      { id: 'updatedAt', label: label('fields.lastUsed', '最近使用'), width: 118 },
      { id: 'status', label: label('fields.status', '状态'), width: 96 },
    ],
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
    status: getReadableStatus(session.status, label),
    updatedAt: session.last_active_at,
    evidenceCount: toOptionalNumber(session.message_count),
    summary: session.last_message_preview || session.last_user_message_preview || null,
    impact: [
      { label: label('impact.goals', '目标'), value: toFiniteNumber(session.goal_count) },
      { label: label('impact.entities', '实体'), value: toFiniteNumber(session.entity_count) },
      { label: label('impact.tactics', '策略'), value: toFiniteNumber(session.tactic_count) },
    ],
    listCells: {
      updatedAt: { value: formatTime(session.last_active_at) },
      evidenceCount: { value: toOptionalNumber(session.message_count) ?? '-', tone: 'muted' },
      status: { value: getReadableStatus(session.status, label), tone: 'status' },
    },
    details: [
      { label: label('fields.startedAt', '开始时间'), value: formatTime(session.started_at) },
      { label: label('fields.workspace', '工作区'), value: safeText(session.workspace_path, label('sources.chat', '对话')) },
      { label: label('fields.messages', '消息'), value: toOptionalNumber(session.message_count) ?? '-' },
    ],
  }));

  const l1Records: LayerRecord[] = l1Events.map((event) => ({
    id: safeText(event.event_id, label('fallbacks.unknownRecord', '未知记录')),
    layer: 'l1',
    categoryId: 'events',
    categoryLabel: categoryLabels.events,
    title: clampText(event.content, getReadableEventType(event.event_type, label), 88),
    type: getReadableEventType(event.event_type, label),
    source: getReadableSource(event.source, label),
    sourceKind: event.source || null,
    sourceItemId: event.source_item_id || null,
    status: event.deleted_at ? label('statuses.deleted', '已删除') : getReadableStatus(event.embedding_status, label, label('statuses.valid', '有效')),
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
    listCells: {
      source: { value: getReadableSource(event.source, label) },
      type: { value: getReadableEventType(event.event_type, label) },
      updatedAt: { value: formatTime(event.timestamp || event.created_at) },
      status: { value: event.deleted_at ? label('statuses.deleted', '已删除') : getReadableStatus(event.embedding_status, label, label('statuses.valid', '有效')), tone: 'status' },
    },
    details: [
      { label: label('fields.memoryDomain', '记忆范围'), value: safeText(event.memory_domain, '-') },
      { label: label('fields.retentionClass', '保留策略'), value: safeText(event.retention_class, '-') },
      { label: label('fields.contentType', '内容类型'), value: safeText(event.content_type, '-') },
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
      title: safeText(entity.canonical_name, label('fallbacks.unknownRecord', '未知记录')),
      type: label('recordTypes.entity', '实体'),
      source: getRelationEntityTypeLabel(entity.entity_type, label),
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
      listCells: {
        entityType: { value: getRelationEntityTypeLabel(entity.entity_type, label) },
        evidenceCount: { value: evidenceCount, tone: 'muted' },
        updatedAt: { value: formatTime(entity.updated_at) },
        status: { value: label('statuses.valid', '有效'), tone: 'status' },
      },
      details: [
        { label: label('fields.entityType', '对象类型'), value: getRelationEntityTypeLabel(entity.entity_type, label) },
        { label: label('fields.aliases', '别名'), value: aliases.join('、') || '-' },
        { label: label('fields.createdAt', '创建时间'), value: formatTime(entity.created_at) },
      ],
    };
  });

  const l2AssertionRecords: LayerRecord[] = l2Assertions.map((assertion) => {
    const evidenceEvents = toList(assertion.evidence_events);
    const entityName = getAssertionEntityName(assertion.entity_id, entityNamesById, label);
    const traitLabel = getAssertionTraitLabel(assertion.trait_name, label);
    const traitValue = safeText(assertion.trait_value, '');
    const lifecycleStatus = safeText(
      assertion.status,
      safeText(assertion.validation_state, 'active'),
    );
    const correctable = !NON_CURRENT_ASSERTION_STATUSES.has(lifecycleStatus.toLowerCase());
    return {
      id: safeText(assertion.assertion_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l2',
      categoryId: 'assertions',
      categoryLabel: categoryLabels.assertions,
      title: getAssertionStatement(entityName, traitLabel, traitValue, label),
      type: label('recordTypes.assertion', '断言'),
      source: getReadableSource(assertion.source_domain, label),
      status: getReadableStatus(lifecycleStatus, label),
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
      listCells: {
        source: { value: getReadableSource(assertion.source_domain, label) },
        evidenceCount: { value: evidenceEvents.length, tone: 'muted' },
        updatedAt: { value: formatTime(assertion.last_validated_at) },
        status: { value: getReadableStatus(lifecycleStatus, label), tone: 'status' },
      },
      details: [
        { label: label('fields.subject', '对象'), value: entityName },
        { label: label('fields.assertionType', '判断类型'), value: traitLabel },
        { label: label('fields.assertionValue', '判断内容'), value: traitValue || '-' },
        { label: label('fields.inferenceDepth', '形成方式'), value: safeText(assertion.inference_depth, '-') },
      ],
      correction: {
        kind: 'assertion',
        correctable,
        currentValue: traitValue,
        expectedUpdatedAt: assertion.updated_at ?? undefined,
      },
    };
  });

  const l2RelationRecords: LayerRecord[] = l2Relations.map((relation) => {
    const evidenceEventIds = toList(relation.evidence_event_ids);
    const subjectName = getRelationEndpointName(relation.subject_id, relation.subject_type, entityNamesById, label);
    const objectName = getRelationEndpointName(relation.object_id, relation.object_type, entityNamesById, label);
    const predicateLabel = getRelationPredicateLabel(relation.predicate, label);
    const subjectType = getRelationEntityTypeLabel(relation.subject_type, label);
    const objectType = getRelationEntityTypeLabel(relation.object_type, label);
    const relationType = `${subjectType} → ${objectType}`;
    return {
      id: safeText(relation.triple_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l2',
      categoryId: 'relations',
      categoryLabel: categoryLabels.relations,
      title: label('relations.statement', '{{subject}} {{predicate}} {{object}}', {
        subject: subjectName,
        predicate: predicateLabel,
        object: objectName,
      }),
      type: label('recordTypes.relation', '关系'),
      source: subjectType,
      status: getReadableStatus(relation.status, label),
      updatedAt: relation.updated_at || relation.last_observed_at,
      evidenceCount: evidenceEventIds.length,
      summary: relationType,
      related: evidenceEventIds,
      impact: [
        { label: label('impact.observations', '观察'), value: toFiniteNumber(relation.observation_count) },
        { label: label('impact.confidence', '可信度'), value: formatDecimal(relation.confidence) },
      ],
      listCells: {
        relationType: { value: relationType, tone: 'muted' },
        observations: { value: toFiniteNumber(relation.observation_count), tone: 'muted' },
        updatedAt: { value: formatTime(relation.updated_at || relation.last_observed_at) },
        status: { value: getReadableStatus(relation.status, label), tone: 'status' },
      },
      details: [
        { label: label('fields.subject', '主体'), value: subjectName },
        { label: label('fields.relationship', '关系'), value: predicateLabel },
        { label: label('fields.object', '客体'), value: objectName },
        { label: label('fields.observations', '观察'), value: toFiniteNumber(relation.observation_count) },
      ],
      correction: {
        kind: 'edge',
        correctable: String(relation.status).toLowerCase() === 'active',
        expectedUpdatedAt: relation.updated_at ?? undefined,
        relationship: {
          subjectId: relation.subject_id,
          subjectType: relation.subject_type,
          subjectName,
          predicate: relation.predicate,
          predicateLabel,
          objectId: relation.object_id,
          objectType: relation.object_type,
          objectName,
        },
      },
    };
  });

  const l2SnapshotRecords: LayerRecord[] = l2Snapshots.map((snapshot) => {
    const entityName = getAssertionEntityName(snapshot.entity_id, entityNamesById, label);
    const statePreview = getSnapshotPreview(snapshot, label);
    return {
      id: safeText(snapshot.snapshot_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l2',
      categoryId: 'snapshots',
      categoryLabel: categoryLabels.snapshots,
      title: label('snapshots.title', '{{entity}}的近期状态', { entity: entityName }),
      type: label('recordTypes.snapshot', '快照'),
      source: getRelationEntityTypeLabel(snapshot.entity_type, label),
      status: label('statuses.valid', '有效'),
      updatedAt: snapshot.last_updated_at,
      evidenceCount: toOptionalNumber(snapshot.interaction_count),
      summary: statePreview,
      impact: [
        { label: label('impact.engagement', '参与度'), value: toOptionalNumber(snapshot.current_engagement) ?? '-' },
        { label: label('impact.stress', '压力'), value: toOptionalNumber(snapshot.current_stress_level) ?? '-' },
      ],
      listCells: {
        state: { value: statePreview },
        evidenceCount: { value: toOptionalNumber(snapshot.interaction_count) ?? '-', tone: 'muted' },
        updatedAt: { value: formatTime(snapshot.last_updated_at) },
        status: { value: label('statuses.valid', '有效'), tone: 'status' },
      },
      details: [
        { label: label('fields.subject', '对象'), value: entityName },
        { label: label('fields.currentMood', '当前情绪'), value: safeText(snapshot.current_mood, '-') },
        { label: label('fields.interactions', '互动'), value: toOptionalNumber(snapshot.interaction_count) ?? '-' },
      ],
    };
  });

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
      status: getReadableStatus(summary.review_state, label, label('statuses.generated', '已生成')),
      updatedAt: summary.updated_at || summary.created_at,
      evidenceCount: toOptionalNumber(summary.source_event_count),
      summary: summary.content,
      related: keyTopics,
      impact: [
        { label: label('impact.events', '事件'), value: toFiniteNumber(summary.source_event_count) },
        { label: label('impact.topics', '主题'), value: keyTopics.length },
      ],
      listCells: {
        period: { value: formatPeriod(summary.period_start, summary.period_end) },
        evidenceCount: { value: toFiniteNumber(summary.source_event_count), tone: 'muted' },
        updatedAt: { value: formatTime(summary.updated_at || summary.created_at) },
        status: { value: getReadableStatus(summary.review_state, label, label('statuses.generated', '已生成')), tone: 'status' },
      },
      details: [
        { label: label('fields.period', '覆盖时间'), value: formatPeriod(summary.period_start, summary.period_end) },
        { label: label('fields.summaryType', '总结类型'), value: safeText(summary.summary_type, '-') },
        { label: label('fields.topics', '主题'), value: keyTopics.join('、') || '-' },
        { label: label('fields.generatedBy', '生成方式'), value: safeText(summary.generated_by_model, '-') },
      ],
    };
  });

  const l4Records: LayerRecord[] = l4Skills.map((skill) => {
    const successRate = `${Math.round(toFiniteNumber(skill.success_rate) * 100)}%`;
    return {
      id: safeText(skill.skill_id, label('fallbacks.unknownRecord', '未知记录')),
      layer: 'l4',
      categoryId: 'skills',
      categoryLabel: categoryLabels.skills,
      title: safeText(skill.skill_name, label('fallbacks.untitledSkill', '未命名技能')),
      type: safeText(skill.skill_category, label('recordTypes.skill', '技能')),
      source: label('sources.procedure', '程序记忆'),
      status: getReadableStatus(skill.circuit_breaker_state, label),
      updatedAt: skill.last_used_at,
      evidenceCount: toOptionalNumber(skill.total_attempts),
      summary: label('skillSummary', '成功 {{success}} / 失败 {{failure}}', {
        success: formatCount(skill.success_count),
        failure: formatCount(skill.failure_count),
      }),
      impact: [
        { label: label('impact.proficiency', '熟练度'), value: formatDecimal(skill.proficiency) },
        { label: label('impact.successRate', '成功率'), value: successRate },
      ],
      listCells: {
        skillType: { value: safeText(skill.skill_category, label('recordTypes.skill', '技能')) },
        successRate: { value: successRate },
        updatedAt: { value: formatTime(skill.last_used_at) },
        status: { value: getReadableStatus(skill.circuit_breaker_state, label), tone: 'status' },
      },
      details: [
        { label: label('fields.attempts', '尝试次数'), value: toOptionalNumber(skill.total_attempts) ?? '-' },
        { label: label('fields.successCount', '成功次数'), value: toOptionalNumber(skill.success_count) ?? '-' },
        { label: label('fields.failureCount', '失败次数'), value: toOptionalNumber(skill.failure_count) ?? '-' },
        { label: label('fields.proficiency', '熟练度'), value: formatDecimal(skill.proficiency) },
      ],
    };
  });

  const pendingAssertions = stats.attention?.pending_assertions ?? 0;
  const openBreakers = stats.l4?.open_circuit_breakers ?? 0;

  return [
    {
      id: 'sessions',
      label: categoryLabels.sessions,
      description: label('categories.sessionsDescription', '当前会话、目标和临时策略'),
      count: memory.l0Total ?? stats.l0?.active_sessions ?? l0Records.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l0Records,
      tableColumns: tableColumns.sessions,
    },
    {
      id: 'events',
      label: categoryLabels.events,
      description: label('categories.eventsDescription', '来源事件、片段和观察'),
      count: memory.l1Total ?? stats.l1?.event_count ?? l1Records.length,
      status: label('statuses.stable', '稳定'),
      tone: 'ok',
      records: l1Records,
      tableColumns: tableColumns.events,
    },
    {
      id: 'entities',
      label: categoryLabels.entities,
      description: label('categories.entitiesDescription', '人物、地点、项目和对象'),
      count: memory.l2EntitiesTotal ?? l2EntityRecords.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l2EntityRecords,
      tableColumns: tableColumns.entities,
    },
    {
      id: 'assertions',
      label: categoryLabels.assertions,
      description: label('categories.assertionsDescription', '偏好、判断和待确认事实'),
      count: memory.l2AssertionsTotal ?? l2AssertionRecords.length,
      status: pendingAssertions > 0 ? label('statuses.pendingCount', '待确认 {{count}}', { count: pendingAssertions }) : label('statuses.healthy', '健康'),
      tone: pendingAssertions > 0 ? 'warn' : 'ok',
      records: l2AssertionRecords,
      tableColumns: tableColumns.assertions,
    },
    {
      id: 'relations',
      label: categoryLabels.relations,
      description: label('categories.relationsDescription', '实体之间的关系和连接'),
      count: memory.l2RelationsTotal ?? l2RelationRecords.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l2RelationRecords,
      tableColumns: tableColumns.relations,
    },
    {
      id: 'snapshots',
      label: categoryLabels.snapshots,
      description: label('categories.snapshotsDescription', '状态、情绪和近期上下文'),
      count: memory.l2SnapshotsTotal ?? l2SnapshotRecords.length,
      status: label('statuses.healthy', '健康'),
      tone: 'ok',
      records: l2SnapshotRecords,
      tableColumns: tableColumns.snapshots,
    },
    {
      id: 'summaries',
      label: categoryLabels.summaries,
      description: label('categories.summariesDescription', '章节、阶段和周期总结'),
      count: memory.l3Total ?? stats.l3?.summary_count ?? l3Records.length,
      status: label('statuses.generated', '已生成'),
      tone: 'ok',
      records: l3Records,
      tableColumns: tableColumns.summaries,
    },
    {
      id: 'skills',
      label: categoryLabels.skills,
      description: label('categories.skillsDescription', '技能、流程和失败保护'),
      count: memory.l4Total ?? stats.l4?.skill_count ?? l4Records.length,
      status: openBreakers > 0 ? label('statuses.breakers', '熔断 {{count}}', { count: openBreakers }) : label('statuses.healthy', '健康'),
      tone: openBreakers > 0 ? 'danger' : 'ok',
      records: l4Records,
      tableColumns: tableColumns.skills,
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
