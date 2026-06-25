import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Layers3,
  Loader2,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react';
import { memoryApi, type EpisodeReconsolidateResult } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useMemory } from '@/hooks/useMemory';
import { cn } from '@/lib/utils';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_INFO_PANEL_CLASS,
} from './MemoryPageFrame';

type GovernanceTab = 'objects' | 'tasks' | 'manual' | 'forget' | 'diagnostics';
type MemoryLayerId = 'l0' | 'l1' | 'l2' | 'l3' | 'l4';
type MaintenanceCategoryId =
  | 'sessions'
  | 'events'
  | 'entities'
  | 'assertions'
  | 'relations'
  | 'snapshots'
  | 'summaries'
  | 'skills';

interface LayerRecord {
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

interface LayerSummary {
  id: MaintenanceCategoryId;
  label: string;
  description: string;
  count: number;
  status: string;
  tone: 'ok' | 'warn' | 'danger';
  records: LayerRecord[];
}

const RECORD_PAGE_SIZE = 6;

const toList = <T,>(value: T[] | null | undefined): T[] => (Array.isArray(value) ? value : []);

const toFiniteNumber = (value: unknown, fallback = 0): number => {
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const toOptionalNumber = (value: unknown): number | null => {
  const numeric = toFiniteNumber(value, Number.NaN);
  return Number.isFinite(numeric) ? numeric : null;
};

const formatDecimal = (value: unknown, digits = 2): string => toFiniteNumber(value).toFixed(digits);

const formatCount = (value: unknown): string => new Intl.NumberFormat().format(Math.max(0, toFiniteNumber(value)));

const formatTime = (timestamp?: number | null): string => {
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

const getStatusToneClass = (tone: LayerSummary['tone']) => {
  if (tone === 'danger') {
    return 'bg-red-50 text-red-700 ring-red-200';
  }
  if (tone === 'warn') {
    return 'bg-amber-50 text-amber-700 ring-amber-200';
  }
  return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
};

const getRowStatusClass = (status: string) => {
  const normalized = status.toLowerCase();
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('异常') || normalized.includes('冲突')) {
    return 'text-red-600';
  }
  if (normalized.includes('pending') || normalized.includes('待') || normalized.includes('queued')) {
    return 'text-amber-600';
  }
  return 'text-emerald-600';
};

export const MemoryGovernancePage = () => {
  const { t } = useTranslation('app');
  const [activeTab, setActiveTab] = useState<GovernanceTab>('objects');
  const [activeLayer, setActiveLayer] = useState<MaintenanceCategoryId>('entities');
  const [activePage, setActivePage] = useState(1);
  const [selectedRecord, setSelectedRecord] = useState<LayerRecord | null>(null);
  const [reconsolidating, setReconsolidating] = useState(false);
  const [reconsolidateResult, setReconsolidateResult] = useState<EpisodeReconsolidateResult | null>(null);
  const [reconsolidateError, setReconsolidateError] = useState<string | null>(null);

  const memory = useMemory({ initialLoadScope: 'all' });

  const label = (key: string, defaultValue: string, values?: Record<string, unknown>) =>
    t(`memory.governance.${key}`, { defaultValue, ...(values || {}) });

  const layerSummaries = useMemo<LayerSummary[]>(() => {
    const l0Sessions = toList(memory.l0Sessions);
    const l1Events = toList(memory.l1Events);
    const l2Assertions = toList(memory.l2Assertions);
    const l2Relations = toList(memory.l2Relations);
    const l2Entities = toList(memory.l2Entities);
    const l2Snapshots = toList(memory.l2Snapshots);
    const l3Summaries = toList(memory.l3Summaries);
    const l4Skills = toList(memory.l4Skills);
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
      return {
        id: safeText(assertion.assertion_id, label('fallbacks.unknownRecord', '未知记录')),
        layer: 'l2',
        categoryId: 'assertions',
        categoryLabel: categoryLabels.assertions,
        title: `${label('recordTypes.assertion', '断言')}：${safeText(assertion.trait_name, label('fallbacks.unknownRecord', '未知记录'))}`,
        type: label('recordTypes.assertion', '断言'),
        source: safeText(assertion.source_domain, label('sources.unknown', '未知来源')),
        status: safeText(assertion.validation_state, label('statuses.unknown', '未知')),
        updatedAt: assertion.last_validated_at,
        evidenceCount: evidenceEvents.length,
        summary: assertion.trait_value,
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

    const pendingAssertions = memory.stats.attention?.pending_assertions ?? 0;
    const openBreakers = memory.stats.l4?.open_circuit_breakers ?? 0;

    return [
      {
        id: 'sessions',
        label: categoryLabels.sessions,
        description: label('categories.sessionsDescription', '当前会话、目标和临时策略'),
        count: memory.l0Total || memory.stats.l0?.active_sessions || l0Records.length,
        status: label('statuses.healthy', '健康'),
        tone: 'ok',
        records: l0Records,
      },
      {
        id: 'events',
        label: categoryLabels.events,
        description: label('categories.eventsDescription', '来源事件、片段和观察'),
        count: memory.l1Total || memory.stats.l1?.event_count || l1Records.length,
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
        count: memory.l3Total || memory.stats.l3?.summary_count || l3Records.length,
        status: label('statuses.generated', '已生成'),
        tone: 'ok',
        records: l3Records,
      },
      {
        id: 'skills',
        label: categoryLabels.skills,
        description: label('categories.skillsDescription', '技能、流程和失败保护'),
        count: memory.l4Total || memory.stats.l4?.skill_count || l4Records.length,
        status: openBreakers > 0 ? label('statuses.breakers', '熔断 {{count}}', { count: openBreakers }) : label('statuses.healthy', '健康'),
        tone: openBreakers > 0 ? 'danger' : 'ok',
        records: l4Records,
      },
    ];
  }, [memory, t]);

  const activeLayerSummary = layerSummaries.find((layer) => layer.id === activeLayer) || layerSummaries[0];
  const activeRecords = activeLayerSummary.records;
  const pageCount = Math.max(1, Math.ceil(activeRecords.length / RECORD_PAGE_SIZE));
  const currentPage = Math.min(activePage, pageCount);
  const visibleRecords = activeRecords.slice((currentPage - 1) * RECORD_PAGE_SIZE, currentPage * RECORD_PAGE_SIZE);
  const pendingAssertionCount = toFiniteNumber(memory.stats.attention?.pending_assertions);
  const openBreakerCount = toFiniteNumber(memory.stats.l4?.open_circuit_breakers);
  const l1EventCount = toFiniteNumber(memory.stats.l1?.event_count) || memory.l1Total;
  const extractSkippedCount = toFiniteNumber(memory.l2Stats?.extract_skipped);

  const diagnostics = useMemo(() => {
    return [
      {
        id: 'pending-assertions',
        severity: pendingAssertionCount > 0 ? 'warn' : 'ok',
        title: label('diagnostics.pendingAssertionsObject', '仍有待确认断言'),
        detail: label('diagnostics.pendingAssertionsDetail', '{{count}} 条判断还没有用户确认或拒绝。', { count: pendingAssertionCount }),
      },
      {
        id: 'l4-breakers',
        severity: openBreakerCount > 0 ? 'danger' : 'ok',
        title: label('diagnostics.openToolBreakers', '存在打开的工具熔断器'),
        detail: label('diagnostics.openBreakersDetail', '{{count}} 个工具记忆暂时不可用。', { count: openBreakerCount }),
      },
      {
        id: 'l2-skipped',
        severity: extractSkippedCount > 0 ? 'warn' : 'ok',
        title: label('diagnostics.skippedStructureExtraction', '结构抽取跳过记录'),
        detail: label('diagnostics.skippedExtractionDetail', '{{count}} 条事件被规则跳过。', { count: extractSkippedCount }),
      },
    ];
  }, [extractSkippedCount, label, openBreakerCount, pendingAssertionCount]);

  const handleReconsolidate = async () => {
    setReconsolidating(true);
    setReconsolidateError(null);
    setReconsolidateResult(null);
    try {
      const result = await memoryApi.reconsolidateEpisodes();
      setReconsolidateResult(result);
    } catch (error) {
      setReconsolidateError(String(error));
    } finally {
      setReconsolidating(false);
    }
  };

  const handleReplaySelected = async () => {
    if (!selectedRecord) return;
    if (selectedRecord.categoryId === 'events') {
      await memory.replayL2Extraction(selectedRecord.id);
      return;
    }
    if (selectedRecord.categoryId === 'entities') {
      await memory.runL2Reconcile([selectedRecord.id]);
    }
  };

  return (
    <MemoryPageFrame
      title={label('title', '整理')}
      description={label('objectSubtitle', '按记忆对象查看、整理、遗忘和诊断。')}
      actions={(
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          onClick={() => void memory.refreshAll()}
          disabled={memory.loading}
        >
          {memory.loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          {label('actions.refresh', '刷新')}
        </Button>
      )}
      className="max-w-[1180px]"
      contentClassName="min-h-0 flex-1 overflow-hidden pb-0"
      scrollable={false}
    >
      <div className="flex h-full min-h-0 flex-col gap-4">
        <section className="grid gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)] p-3 md:grid-cols-4">
          <MetricCell icon={<Layers3 className="h-5 w-5" />} label={label('metrics.objects', '维护对象')} value={formatCount(layerSummaries.reduce((sum, layer) => sum + layer.count, 0))} />
          <MetricCell icon={<AlertTriangle className="h-5 w-5" />} label={label('metrics.pending', '待处理')} value={formatCount(pendingAssertionCount)} tone={pendingAssertionCount > 0 ? 'warn' : 'default'} />
          <MetricCell icon={<Database className="h-5 w-5" />} label={label('metrics.events', '原始事件')} value={formatCount(l1EventCount)} />
          <MetricCell icon={<ShieldAlert className="h-5 w-5" />} label={label('metrics.toolBreakers', '工具熔断')} value={formatCount(openBreakerCount)} tone={openBreakerCount > 0 ? 'danger' : 'default'} />
        </section>

        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as GovernanceTab)} className="flex min-h-0 flex-1 flex-col space-y-4">
          <div className="shrink-0 overflow-x-auto pb-1 [scrollbar-width:thin] [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
            <TabsList className="inline-flex h-auto min-w-full justify-start gap-1 rounded-sm border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.86)] p-1">
              {[
                ['objects', label('tabs.objects', '对象明细')],
                ['tasks', label('tabs.tasks', '定时任务')],
                ['manual', label('tabs.manual', '手动整理')],
                ['forget', label('tabs.forget', '遗忘清理')],
                ['diagnostics', label('tabs.diagnostics', '诊断')],
              ].map(([value, text]) => (
                <TabsTrigger
                  key={value}
                  value={value}
                  className="rounded-sm border border-transparent px-4 py-2 text-sm text-[hsl(var(--memory-body))] data-[state=active]:border-[hsl(var(--memory-border))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))]"
                >
                  {text}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <TabsContent value="objects" className="mt-0 min-h-0 flex-1">
            <LayerWorkspace
              layers={layerSummaries}
              activeLayer={activeLayer}
              activeRecords={activeRecords}
              visibleRecords={visibleRecords}
              page={currentPage}
              pageCount={pageCount}
              pageSize={RECORD_PAGE_SIZE}
              onSelectLayer={(layer) => {
                setActiveLayer(layer);
                setActivePage(1);
                setSelectedRecord(null);
              }}
              onSelectRecord={setSelectedRecord}
              onPageChange={(page) => {
                setActivePage(Math.min(Math.max(1, page), pageCount));
                setSelectedRecord(null);
              }}
              label={label}
            />
          </TabsContent>

          <TabsContent value="tasks" className="mt-0">
            <TaskMaintenancePanel label={label} />
          </TabsContent>

          <TabsContent value="manual" className="mt-0">
            <ManualMaintenancePanel
              label={label}
              reconsolidating={reconsolidating}
              reconsolidateResult={reconsolidateResult}
              reconsolidateError={reconsolidateError}
              onReconsolidate={handleReconsolidate}
              onFlushMicrobatches={memory.flushL2Microbatches}
              l2ActionLoading={memory.l2ActionLoading}
            />
          </TabsContent>

          <TabsContent value="forget" className="mt-0">
            <ForgetMaintenancePanel label={label} />
          </TabsContent>

          <TabsContent value="diagnostics" className="mt-0">
            <DiagnosticsPanel label={label} diagnostics={diagnostics} />
          </TabsContent>
        </Tabs>
      </div>

      <RecordDrawer
        record={selectedRecord}
        open={selectedRecord !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedRecord(null);
        }}
        label={label}
        actionLoading={memory.l2ActionLoading}
        onReplay={() => void handleReplaySelected()}
      />
    </MemoryPageFrame>
  );
};

function MetricCell({
  icon,
  label,
  value,
  tone = 'default',
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: 'default' | 'warn' | 'danger';
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 border-[hsl(var(--memory-divider)/0.5)] px-2 py-2 md:border-r md:last:border-r-0">
      <div className={cn(
        'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.76)] text-[hsl(var(--memory-accent))]',
        tone === 'warn' && 'bg-amber-50 text-amber-700',
        tone === 'danger' && 'bg-red-50 text-red-700'
      )}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-[hsl(var(--memory-muted))]">{label}</div>
        <div className="mt-0.5 text-lg font-semibold text-[hsl(var(--memory-title))]">{value}</div>
      </div>
    </div>
  );
}

function LayerWorkspace({
  layers,
  activeLayer,
  activeRecords,
  visibleRecords,
  page,
  pageCount,
  pageSize,
  onSelectLayer,
  onSelectRecord,
  onPageChange,
  label,
}: {
  layers: LayerSummary[];
  activeLayer: MaintenanceCategoryId;
  activeRecords: LayerRecord[];
  visibleRecords: LayerRecord[];
  page: number;
  pageCount: number;
  pageSize: number;
  onSelectLayer: (layer: MaintenanceCategoryId) => void;
  onSelectRecord: (record: LayerRecord) => void;
  onPageChange: (page: number) => void;
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
}) {
  const selectedLayer = layers.find((layer) => layer.id === activeLayer) || layers[0];
  const pageStart = activeRecords.length === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(activeRecords.length, page * pageSize);
  return (
    <section className="grid h-full min-h-0 gap-3 lg:grid-cols-[230px_minmax(0,1fr)]">
      <aside className="min-h-0 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)] p-2">
        <div className="px-2 pb-2 pt-1 text-xs font-medium text-[hsl(var(--memory-muted))]">
          {label('objects.choose', '选择对象')}
        </div>
        <div className="max-h-[min(530px,calc(100vh-340px))] space-y-1.5 overflow-y-auto pr-1 [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
          {layers.map((layer) => (
            <button
              key={layer.id}
              type="button"
              onClick={() => onSelectLayer(layer.id)}
              className={cn(
                'flex w-full items-center justify-between rounded-lg border px-3 py-3 text-left transition-colors',
                layer.id === activeLayer
                  ? 'border-[hsl(var(--memory-accent)/0.36)] bg-[hsl(var(--memory-accent-soft)/0.45)]'
                  : 'border-transparent hover:bg-[hsl(var(--memory-panel-subtle)/0.58)]'
              )}
            >
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-[hsl(var(--memory-title))]">{layer.label}</span>
                <span className="mt-1 block truncate text-xs text-[hsl(var(--memory-muted))]">{layer.description}</span>
              </span>
              <span className="ml-3 shrink-0 text-right">
                <span className="block text-sm font-medium text-[hsl(var(--memory-title))]">{formatCount(layer.count)}</span>
                <span className={cn('mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] ring-1', getStatusToneClass(layer.tone))}>
                  {layer.status}
                </span>
              </span>
            </button>
          ))}
        </div>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-col rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)]">
        <div className="flex flex-col gap-3 border-b border-[hsl(var(--memory-divider)/0.58)] px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{selectedLayer.label}</h2>
            <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
              {label('objects.tableSubtitle', '{{description}}（共 {{count}} 条）', {
                description: selectedLayer.description,
                count: formatCount(selectedLayer.count),
              })}
            </p>
          </div>
          <div className="flex min-w-0 items-center gap-2 rounded-sm border border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-muted))]">
            <Search className="h-4 w-4" />
            <span>{label('objects.searchHint', '点击记录查看详情和影响')}</span>
          </div>
        </div>

        {activeRecords.length === 0 ? (
          <div className="min-h-0 flex-1 p-4">
            <div className={MEMORY_EMPTY_PANEL_CLASS}>{label('objects.empty', '这个对象类型暂时没有可展示的记录。')}</div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-x-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
              <div className="min-w-[760px]">
                <div className="grid grid-cols-[minmax(150px,1.1fr)_120px_120px_120px_92px_40px] border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
                  <span>ID</span>
                  <span>{label('fields.type', '类型')}</span>
                  <span>{label('fields.source', '来源')}</span>
                  <span>{label('fields.updatedAt', '更新时间')}</span>
                  <span>{label('fields.status', '状态')}</span>
                  <span />
                </div>
                <div className="max-h-[390px] divide-y divide-[hsl(var(--memory-divider)/0.46)] overflow-y-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
                  {visibleRecords.map((record) => (
                    <button
                      key={`${record.categoryId}:${record.id}`}
                      type="button"
                      aria-label={label('objects.openRecord', '打开记录 {{id}}', { id: record.id })}
                      onClick={() => onSelectRecord(record)}
                      className="grid w-full grid-cols-[minmax(150px,1.1fr)_120px_120px_120px_92px_40px] items-center px-4 py-3 text-left text-sm transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.48)]"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-[hsl(var(--memory-title))]">{record.id}</span>
                        <span className="mt-0.5 block truncate text-xs text-[hsl(var(--memory-muted))]">{record.title}</span>
                      </span>
                      <span className="truncate text-[hsl(var(--memory-body))]">{record.type}</span>
                      <span className="truncate text-[hsl(var(--memory-body))]">{record.source}</span>
                      <span className="text-[hsl(var(--memory-body))]">{formatTime(record.updatedAt)}</span>
                      <span className={cn('font-medium', getRowStatusClass(record.status))}>{record.status}</span>
                      <ChevronRight className="h-4 w-4 text-[hsl(var(--memory-muted))]" />
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-2 border-t border-[hsl(var(--memory-divider)/0.5)] px-4 py-3 text-sm text-[hsl(var(--memory-body))] sm:flex-row sm:items-center sm:justify-between">
              <span>
                {label('objects.pageSummary', '{{start}}-{{end}} / {{total}} 条', {
                  start: pageStart,
                  end: pageEnd,
                  total: activeRecords.length,
                })}
              </span>
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 rounded-sm px-3"
                  disabled={page <= 1}
                  onClick={() => onPageChange(page - 1)}
                >
                  <ChevronLeft className="mr-1 h-4 w-4" />
                  {label('objects.prevPage', '上一页')}
                </Button>
                <span className="min-w-[56px] text-center text-xs text-[hsl(var(--memory-muted))]">
                  {label('objects.pageIndex', '{{page}} / {{pageCount}}', { page, pageCount })}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 rounded-sm px-3"
                  disabled={page >= pageCount}
                  onClick={() => onPageChange(page + 1)}
                >
                  {label('objects.nextPage', '下一页')}
                  <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function TaskMaintenancePanel({
  label,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
}) {
  const rows = [
    [label('tasks.eventsTitle', '原始事件清理'), label('tasks.eventsBody', '压缩可清理事件、清除过期负载'), label('tasks.eventsScope', '事件维护'), label('statuses.enabled', '已启用')],
    [label('tasks.structureTitle', '结构抽取'), label('tasks.structureBody', '处理实体、断言和关系派生任务'), label('tasks.structureScope', '知识维护'), label('statuses.enabled', '已启用')],
    [label('tasks.chapterTitle', '章节整理'), label('tasks.chapterBody', '升级章节、经历和缺失总结'), label('tasks.chapterScope', '经历维护'), label('statuses.enabled', '已启用')],
    [label('tasks.summaryTitle', '总结生成'), label('tasks.summaryBody', '生成时段总结并清理过期内容'), label('tasks.summaryScope', '总结维护'), label('statuses.enabled', '已启用')],
    [label('tasks.skillsTitle', '工具记忆维护'), label('tasks.skillsBody', '维护工具技能和失败保护状态'), label('tasks.skillsScope', '技能维护'), label('statuses.enabled', '已启用')],
  ];
  return (
    <section className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)]">
      <div className="flex items-center justify-between border-b border-[hsl(var(--memory-divider)/0.58)] px-4 py-3">
        <div>
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{label('tasks.title', '记忆维护任务')}</h2>
          <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{label('tasks.subtitle', '这里只聚合记忆相关任务；完整编辑仍在调度配置里。')}</p>
        </div>
        <Link to="/tasks/schedules" className="inline-flex items-center gap-1 text-sm text-[hsl(var(--memory-accent))]">
          {label('tasks.openSchedules', '打开调度配置')}
          <ArrowUpRight className="h-4 w-4" />
        </Link>
      </div>
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.46)]">
        {rows.map(([name, description, scope, status]) => (
          <div key={name} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[170px_minmax(0,1fr)_140px_92px] md:items-center">
            <div className="font-semibold text-[hsl(var(--memory-title))]">{name}</div>
            <div className="text-[hsl(var(--memory-body))]">{description}</div>
            <div className="truncate text-xs text-[hsl(var(--memory-muted))]">{scope}</div>
            <div className="text-emerald-600">{status}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ManualMaintenancePanel({
  label,
  reconsolidating,
  reconsolidateResult,
  reconsolidateError,
  onReconsolidate,
  onFlushMicrobatches,
  l2ActionLoading,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  reconsolidating: boolean;
  reconsolidateResult: EpisodeReconsolidateResult | null;
  reconsolidateError: string | null;
  onReconsolidate: () => Promise<void>;
  onFlushMicrobatches: () => Promise<void>;
  l2ActionLoading: boolean;
}) {
  return (
    <section className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)]">
      <ActionRow
        title={label('reconsolidateTitle', '整理章节')}
        description={label('reconsolidateBody', '让 Magi 把最近形成的活动片段升级成章节，并给它们起标题。')}
        buttonLabel={label('reconsolidateRunSpecific', '立即整理章节')}
        busy={reconsolidating}
        onClick={() => void onReconsolidate()}
      />
      <ActionRow
        title={label('manual.flushStructureTitle', '处理结构抽取积压')}
        description={label('manual.flushStructureBody', '立即提交当前暂存的结构抽取批次，适合调试抽取延迟。')}
        buttonLabel={label('manual.flushRun', '立即处理')}
        busy={l2ActionLoading}
        onClick={() => void onFlushMicrobatches()}
      />
      {reconsolidateResult ? (
        <div className="border-t border-[hsl(var(--memory-divider)/0.46)] px-4 py-3 text-sm text-[hsl(var(--memory-body))]">
          {label('reconsolidateResult', '升级 {{promoted}} 条 · 标志 {{standouts}} 条 · 新章节 {{summaries}} 条', {
            promoted: reconsolidateResult.promoted,
            standouts: reconsolidateResult.standouts,
            summaries: reconsolidateResult.summaries_generated,
          })}
        </div>
      ) : null}
      {reconsolidateError ? (
        <div className="border-t border-[hsl(var(--memory-divider)/0.46)] px-4 py-3 text-sm text-red-600">{reconsolidateError}</div>
      ) : null}
    </section>
  );
}

function ActionRow({
  title,
  description,
  buttonLabel,
  busy,
  onClick,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-[hsl(var(--memory-divider)/0.46)] px-4 py-4 last:border-b-0 md:flex-row md:items-center md:justify-between">
      <div>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{description}</p>
      </div>
      <Button onClick={onClick} disabled={busy} className="h-9 w-fit rounded-sm px-4">
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
        {buttonLabel}
      </Button>
    </div>
  );
}

function ForgetMaintenancePanel({
  label,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
}) {
  return (
    <section className="space-y-3">
      <div className={MEMORY_INFO_PANEL_CLASS}>
        {label('forgetDrawerHintObjects', '遗忘和删除从具体记录发起：先在「对象明细」里打开一条记录，再在抽屉中查看影响。')}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <LinkPanel to="/memory/events" title={label('forgetBySource', '按来源/事件清理')} body={label('forgetBySourceBodyObjects', '进入原始事件后按来源、时间和内容筛选。')} />
        <LinkPanel to="/memory/knowledge" title={label('forgetByEntity', '按实体处理')} body={label('forgetByEntityBodyObjects', '进入结构知识后查看实体、断言和关系。')} />
        <LinkPanel to="/memory/episodes" title={label('forgetByEpisode', '按经历处理')} body={label('forgetByEpisodeBody', '进入经历详情后处理章节边界和可见性。')} />
      </div>
    </section>
  );
}

function LinkPanel({ to, title, body }: { to: string; title: string; body: string }) {
  return (
    <Link
      to={to}
      className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)] p-4 transition-colors hover:border-[hsl(var(--memory-accent)/0.32)] hover:bg-[hsl(var(--memory-panel-elevated)/0.86)]"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
        <ArrowUpRight className="h-4 w-4 text-[hsl(var(--memory-accent))]" />
      </div>
      <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{body}</p>
    </Link>
  );
}

function DiagnosticsPanel({
  label,
  diagnostics,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  diagnostics: Array<{ id: string; severity: string; title: string; detail: string }>;
}) {
  return (
    <section className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)]">
      <div className="border-b border-[hsl(var(--memory-divider)/0.58)] px-4 py-3">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{label('diagnostics.title', '维护诊断')}</h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{label('diagnostics.subtitle', '把需要运维注意的记忆问题集中在这里。')}</p>
      </div>
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.46)]">
        {diagnostics.map((item) => (
          <div key={item.id} className="flex items-start gap-3 px-4 py-3">
            {item.severity === 'ok' ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" /> : <AlertTriangle className={cn('mt-0.5 h-5 w-5', item.severity === 'danger' ? 'text-red-600' : 'text-amber-600')} />}
            <div className="min-w-0">
              <div className="font-semibold text-[hsl(var(--memory-title))]">{item.title}</div>
              <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{item.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function RecordDrawer({
  record,
  open,
  onOpenChange,
  label,
  actionLoading,
  onReplay,
}: {
  record: LayerRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  actionLoading: boolean;
  onReplay: () => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-[min(92vw,560px)] max-w-[560px] flex-col overflow-y-auto border-[hsl(var(--memory-border)/0.65)] bg-[hsl(var(--memory-panel))] p-0"
      >
        <SheetHeader className="border-b border-[hsl(var(--memory-divider)/0.58)] px-5 py-5">
          <SheetTitle className="text-lg text-[hsl(var(--memory-title))]">{label('drawer.title', '记录详情')}</SheetTitle>
          <SheetDescription className="text-[hsl(var(--memory-body))]">
            {record ? `${record.categoryLabel} · ${record.id}` : label('drawer.empty', '选择一条记录查看详情。')}
          </SheetDescription>
        </SheetHeader>

        {record ? (
          <div className="flex flex-1 flex-col gap-4 px-5 py-4">
            <section>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{record.title}</h2>
                  <p className="mt-1 text-sm leading-6 text-[hsl(var(--memory-body))]">{record.summary || label('drawer.noSummary', '暂无摘要。')}</p>
                </div>
                <span className={cn('shrink-0 rounded-full px-2.5 py-1 text-xs font-medium', getRowStatusClass(record.status))}>{record.status}</span>
              </div>
            </section>

            <DetailGroup title={label('drawer.metadata', '元数据')}>
              <DetailRow label="ID" value={record.id} />
              <DetailRow label={label('fields.type', '类型')} value={record.type} />
              <DetailRow label={label('fields.source', '来源')} value={record.source} />
              <DetailRow label={label('fields.updatedAt', '更新时间')} value={formatTime(record.updatedAt)} />
              <DetailRow label={label('fields.evidenceCount', '证据数')} value={record.evidenceCount ?? '-'} />
            </DetailGroup>

            <DetailGroup title={label('drawer.related', '来源证据')}>
              {record.related && record.related.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {record.related.slice(0, 12).map((item) => (
                    <span key={item} className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.78)] px-2.5 py-1 text-xs text-[hsl(var(--memory-body))]">
                      {item}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-[hsl(var(--memory-muted))]">{label('drawer.noRelated', '没有可直接展示的证据引用。')}</p>
              )}
            </DetailGroup>

            <DetailGroup title={label('drawer.impact', '下游影响')}>
              {record.impact && record.impact.length > 0 ? (
                <div className="grid gap-2 sm:grid-cols-3">
                  {record.impact.map((item) => (
                    <div key={item.label} className="rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.56)] px-3 py-2">
                      <div className="text-xs text-[hsl(var(--memory-muted))]">{item.label}</div>
                      <div className="mt-1 text-base font-semibold text-[hsl(var(--memory-title))]">{item.value}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-[hsl(var(--memory-muted))]">{label('drawer.noImpact', '暂无可计算的下游影响。')}</p>
              )}
            </DetailGroup>

            <div className="mt-auto space-y-3 border-t border-[hsl(var(--memory-divider)/0.58)] pt-4">
              <div>
                <div className="mb-2 text-sm font-semibold text-[hsl(var(--memory-title))]">{label('drawer.safeActions', '安全操作')}</div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <Button variant="outline" className="h-9 rounded-sm" onClick={onReplay} disabled={actionLoading || (record.categoryId !== 'events' && record.categoryId !== 'entities')}>
                    {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                    {label('drawer.actions.reprocess', '重新处理')}
                  </Button>
                  <Button variant="outline" className="h-9 rounded-sm" disabled>
                    <SlidersHorizontal className="mr-2 h-4 w-4" />
                    {label('drawer.actions.invalidate', '标记无效')}
                  </Button>
                  <Button variant="outline" className="h-9 rounded-sm border-red-200 text-red-700 hover:bg-red-50" disabled>
                    <Trash2 className="mr-2 h-4 w-4" />
                    {label('drawer.actions.delete', '删除')}
                  </Button>
                </div>
              </div>
              <Button className="h-10 w-full rounded-sm bg-red-600 text-white hover:bg-red-700" disabled>
                <Trash2 className="mr-2 h-4 w-4" />
                {label('drawer.actions.cascadeForget', '连带遗忘（包含下游）')}
              </Button>
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function DetailGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-elevated)/0.58)] p-3">
      <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3 border-b border-[hsl(var(--memory-divider)/0.36)] py-1.5 text-sm last:border-b-0">
      <div className="text-[hsl(var(--memory-muted))]">{label}</div>
      <div className="min-w-0 break-words text-[hsl(var(--memory-title))]">{value}</div>
    </div>
  );
}

export default MemoryGovernancePage;
