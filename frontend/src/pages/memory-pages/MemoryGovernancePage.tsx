import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
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

type GovernanceTab = 'layers' | 'tasks' | 'manual' | 'forget' | 'diagnostics';
type MemoryLayerId = 'l0' | 'l1' | 'l2' | 'l3' | 'l4';

interface LayerRecord {
  id: string;
  layer: MemoryLayerId;
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
  id: MemoryLayerId;
  label: string;
  description: string;
  count: number;
  status: string;
  tone: 'ok' | 'warn' | 'danger';
  records: LayerRecord[];
}

const formatCount = (value: number): string => new Intl.NumberFormat().format(Math.max(0, value));

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
  const [activeTab, setActiveTab] = useState<GovernanceTab>('layers');
  const [activeLayer, setActiveLayer] = useState<MemoryLayerId>('l2');
  const [selectedRecord, setSelectedRecord] = useState<LayerRecord | null>(null);
  const [reconsolidating, setReconsolidating] = useState(false);
  const [reconsolidateResult, setReconsolidateResult] = useState<EpisodeReconsolidateResult | null>(null);
  const [reconsolidateError, setReconsolidateError] = useState<string | null>(null);

  const memory = useMemory({ initialLoadScope: 'all' });

  const label = (key: string, defaultValue: string, values?: Record<string, unknown>) =>
    t(`memory.governance.${key}`, { defaultValue, ...(values || {}) });

  const layerSummaries = useMemo<LayerSummary[]>(() => {
    const l2EntityEvidence = (entityId: string) => (
      memory.l2Assertions.filter((assertion) => assertion.entity_id === entityId).length +
      memory.l2Relations.filter((relation) => relation.subject_id === entityId || relation.object_id === entityId).length
    );

    const l0Records: LayerRecord[] = memory.l0Sessions.map((session) => ({
      id: session.short_session_id || session.session_id,
      layer: 'l0',
      title: clampText(session.display_title, label('fallbacks.untitledSession', '未命名会话'), 64),
      type: label('recordTypes.session', '会话'),
      source: session.workspace_path ? label('sources.workspace', '工作区') : label('sources.chat', '对话'),
      status: session.status,
      updatedAt: session.last_active_at,
      evidenceCount: session.message_count ?? null,
      summary: session.last_message_preview || session.last_user_message_preview || null,
      impact: [
        { label: label('impact.goals', '目标'), value: session.goal_count },
        { label: label('impact.entities', '实体'), value: session.entity_count },
        { label: label('impact.tactics', '策略'), value: session.tactic_count },
      ],
    }));

    const l1Records: LayerRecord[] = memory.l1Events.map((event) => ({
      id: event.event_id,
      layer: 'l1',
      title: clampText(event.content, event.event_type, 88),
      type: event.event_type,
      source: event.source || label('sources.unknown', '未知来源'),
      status: event.deleted_at ? label('statuses.deleted', '已删除') : event.embedding_status || label('statuses.valid', '有效'),
      updatedAt: event.timestamp || event.created_at,
      evidenceCount: event.embedding_chunk_count ?? null,
      summary: event.content,
      related: [
        event.session_id ? `${label('fields.session', '会话')} ${event.session_id}` : '',
        event.turn_id ? `${label('fields.turn', '回合')} ${event.turn_id}` : '',
      ].filter(Boolean),
      impact: [
        { label: label('impact.importance', '重要度'), value: event.importance_score.toFixed(2) },
        { label: label('impact.cognition', '进入认知'), value: event.cognition_eligible ? label('yes', '是') : label('no', '否') },
      ],
    }));

    const l2EntityRecords: LayerRecord[] = memory.l2Entities.map((entity) => {
      const evidenceCount = l2EntityEvidence(entity.entity_id);
      return {
        id: entity.entity_id,
        layer: 'l2',
        title: `${label('recordTypes.entity', '实体')}：${entity.canonical_name}`,
        type: label('recordTypes.entity', '实体'),
        source: entity.entity_type,
        status: label('statuses.valid', '有效'),
        updatedAt: entity.updated_at,
        evidenceCount,
        summary: entity.aliases?.length ? `${label('fields.aliases', '别名')}：${entity.aliases.join('、')}` : null,
        related: entity.aliases || [],
        impact: [
          { label: label('impact.relations', '关系'), value: memory.l2Relations.filter((item) => item.subject_id === entity.entity_id || item.object_id === entity.entity_id).length },
          { label: label('impact.assertions', '断言'), value: memory.l2Assertions.filter((item) => item.entity_id === entity.entity_id).length },
          { label: label('impact.snapshots', '快照'), value: memory.l2Snapshots.filter((item) => item.entity_id === entity.entity_id).length },
        ],
      };
    });

    const l2AssertionRecords: LayerRecord[] = memory.l2Assertions.map((assertion) => ({
      id: assertion.assertion_id,
      layer: 'l2',
      title: `${label('recordTypes.assertion', '断言')}：${assertion.trait_name}`,
      type: label('recordTypes.assertion', '断言'),
      source: assertion.source_domain,
      status: assertion.validation_state,
      updatedAt: assertion.last_validated_at,
      evidenceCount: assertion.evidence_events.length,
      summary: assertion.trait_value,
      related: assertion.evidence_events,
      impact: [
        { label: label('impact.confidence', '可信度'), value: assertion.confidence_score.toFixed(2) },
        { label: label('impact.volatility', '波动'), value: assertion.volatility_index.toFixed(2) },
      ],
    }));

    const l2RelationRecords: LayerRecord[] = memory.l2Relations.map((relation) => ({
      id: relation.triple_id,
      layer: 'l2',
      title: `${label('recordTypes.relation', '关系')}：${relation.subject_id} ${relation.predicate} ${relation.object_id}`,
      type: label('recordTypes.relation', '关系'),
      source: relation.subject_type,
      status: relation.status,
      updatedAt: relation.updated_at || relation.last_observed_at,
      evidenceCount: relation.evidence_event_ids.length,
      summary: `${relation.subject_type} → ${relation.object_type}`,
      related: relation.evidence_event_ids,
      impact: [
        { label: label('impact.observations', '观察'), value: relation.observation_count },
        { label: label('impact.confidence', '可信度'), value: relation.confidence.toFixed(2) },
      ],
    }));

    const l2SnapshotRecords: LayerRecord[] = memory.l2Snapshots.map((snapshot) => ({
      id: snapshot.snapshot_id,
      layer: 'l2',
      title: `${label('recordTypes.snapshot', '快照')}：${snapshot.entity_id}`,
      type: label('recordTypes.snapshot', '快照'),
      source: snapshot.entity_type,
      status: label('statuses.valid', '有效'),
      updatedAt: snapshot.last_updated_at,
      evidenceCount: snapshot.interaction_count ?? null,
      summary: snapshot.current_mood || null,
      impact: [
        { label: label('impact.engagement', '参与度'), value: snapshot.current_engagement ?? '-' },
        { label: label('impact.stress', '压力'), value: snapshot.current_stress_level ?? '-' },
      ],
    }));

    const l2Records = [...l2EntityRecords, ...l2AssertionRecords, ...l2RelationRecords, ...l2SnapshotRecords];

    const l3Records: LayerRecord[] = memory.l3Summaries.map((summary) => ({
      id: summary.summary_id,
      layer: 'l3',
      title: clampText(summary.content, summary.summary_category, 88),
      type: summary.summary_category,
      source: summary.summary_type,
      status: summary.review_state || label('statuses.generated', '已生成'),
      updatedAt: summary.updated_at || summary.created_at,
      evidenceCount: summary.source_event_count,
      summary: summary.content,
      related: summary.key_topics,
      impact: [
        { label: label('impact.events', '事件'), value: summary.source_event_count },
        { label: label('impact.topics', '主题'), value: summary.key_topics.length },
      ],
    }));

    const l4Records: LayerRecord[] = memory.l4Skills.map((skill) => ({
      id: skill.skill_id,
      layer: 'l4',
      title: skill.skill_name,
      type: skill.skill_category,
      source: label('sources.procedure', '程序记忆'),
      status: skill.circuit_breaker_state,
      updatedAt: skill.last_used_at,
      evidenceCount: skill.total_attempts,
      summary: label('skillSummary', '成功 {{success}} / 失败 {{failure}}', {
        success: skill.success_count,
        failure: skill.failure_count,
      }),
      impact: [
        { label: label('impact.proficiency', '熟练度'), value: skill.proficiency.toFixed(2) },
        { label: label('impact.successRate', '成功率'), value: `${Math.round(skill.success_rate * 100)}%` },
      ],
    }));

    const pendingAssertions = memory.stats.attention?.pending_assertions ?? 0;
    const openBreakers = memory.stats.l4.open_circuit_breakers ?? 0;

    return [
      {
        id: 'l0',
        label: 'L0 工作台',
        description: label('layers.l0Description', '会话、目标、策略等'),
        count: memory.l0Total || memory.stats.l0.active_sessions || l0Records.length,
        status: label('statuses.healthy', '健康'),
        tone: 'ok',
        records: l0Records,
      },
      {
        id: 'l1',
        label: 'L1 原始事件',
        description: label('layers.l1Description', '事件、片段、观察等'),
        count: memory.l1Total || memory.stats.l1.event_count || l1Records.length,
        status: label('statuses.stable', '稳定'),
        tone: 'ok',
        records: l1Records,
      },
      {
        id: 'l2',
        label: 'L2 结构知识',
        description: label('layers.l2Description', '实体、关系、断言等'),
        count: memory.l2EntitiesTotal + memory.l2RelationsTotal + memory.l2AssertionsTotal + memory.l2SnapshotsTotal || l2Records.length,
        status: pendingAssertions > 0 ? label('statuses.pendingCount', '待确认 {{count}}', { count: pendingAssertions }) : label('statuses.healthy', '健康'),
        tone: pendingAssertions > 0 ? 'warn' : 'ok',
        records: l2Records,
      },
      {
        id: 'l3',
        label: 'L3 总结',
        description: label('layers.l3Description', '日/周/月总结'),
        count: memory.l3Total || memory.stats.l3.summary_count || l3Records.length,
        status: label('statuses.generated', '已生成'),
        tone: 'ok',
        records: l3Records,
      },
      {
        id: 'l4',
        label: 'L4 工具记忆',
        description: label('layers.l4Description', '技能、流程、模板等'),
        count: memory.l4Total || memory.stats.l4.skill_count || l4Records.length,
        status: openBreakers > 0 ? label('statuses.breakers', '熔断 {{count}}', { count: openBreakers }) : label('statuses.healthy', '健康'),
        tone: openBreakers > 0 ? 'danger' : 'ok',
        records: l4Records,
      },
    ];
  }, [memory, t]);

  const activeLayerSummary = layerSummaries.find((layer) => layer.id === activeLayer) || layerSummaries[0];
  const activeRecords = activeLayerSummary.records;

  const diagnostics = useMemo(() => {
    const pendingAssertions = memory.stats.attention?.pending_assertions ?? 0;
    const openBreakers = memory.stats.l4.open_circuit_breakers ?? 0;
    const extractSkipped = memory.l2Stats.extract_skipped ?? 0;
    return [
      {
        id: 'pending-assertions',
        severity: pendingAssertions > 0 ? 'warn' : 'ok',
        title: label('diagnostics.pendingAssertions', 'L2 仍有待确认断言'),
        detail: label('diagnostics.pendingAssertionsDetail', '{{count}} 条判断还没有用户确认或拒绝。', { count: pendingAssertions }),
      },
      {
        id: 'l4-breakers',
        severity: openBreakers > 0 ? 'danger' : 'ok',
        title: label('diagnostics.openBreakers', 'L4 存在打开的熔断器'),
        detail: label('diagnostics.openBreakersDetail', '{{count}} 个工具记忆暂时不可用。', { count: openBreakers }),
      },
      {
        id: 'l2-skipped',
        severity: extractSkipped > 0 ? 'warn' : 'ok',
        title: label('diagnostics.skippedExtraction', 'L2 抽取跳过记录'),
        detail: label('diagnostics.skippedExtractionDetail', '{{count}} 条事件被规则跳过。', { count: extractSkipped }),
      },
    ];
  }, [label, memory.l2Stats.extract_skipped, memory.stats.attention?.pending_assertions, memory.stats.l4.open_circuit_breakers]);

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
    if (selectedRecord.layer === 'l1') {
      await memory.replayL2Extraction(selectedRecord.id);
      return;
    }
    if (selectedRecord.layer === 'l2' && selectedRecord.type === label('recordTypes.entity', '实体')) {
      await memory.runL2Reconcile([selectedRecord.id]);
    }
  };

  return (
    <MemoryPageFrame
      title={label('title', '整理')}
      description={label('subtitle', '分层查看、手动整理、遗忘清理和维护诊断。')}
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
    >
      <div className="space-y-4">
        <section className="grid gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)] p-3 md:grid-cols-4">
          <MetricCell icon={<Layers3 className="h-5 w-5" />} label={label('metrics.layerRecords', '分层记录')} value={formatCount(layerSummaries.reduce((sum, layer) => sum + layer.count, 0))} />
          <MetricCell icon={<AlertTriangle className="h-5 w-5" />} label={label('metrics.pending', '待处理')} value={formatCount(memory.stats.attention?.pending_assertions ?? 0)} tone={(memory.stats.attention?.pending_assertions ?? 0) > 0 ? 'warn' : 'default'} />
          <MetricCell icon={<Database className="h-5 w-5" />} label={label('metrics.l1Events', 'L1 事件')} value={formatCount(memory.stats.l1.event_count || memory.l1Total)} />
          <MetricCell icon={<ShieldAlert className="h-5 w-5" />} label={label('metrics.l4Breakers', 'L4 熔断')} value={formatCount(memory.stats.l4.open_circuit_breakers || 0)} tone={(memory.stats.l4.open_circuit_breakers || 0) > 0 ? 'danger' : 'default'} />
        </section>

        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as GovernanceTab)} className="space-y-4">
          <div className="overflow-x-auto pb-1">
            <TabsList className="inline-flex h-auto min-w-full justify-start gap-1 rounded-sm border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.86)] p-1">
              {[
                ['layers', label('tabs.layers', '分层明细')],
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

          <TabsContent value="layers" className="mt-0">
            <LayerWorkspace
              layers={layerSummaries}
              activeLayer={activeLayer}
              activeRecords={activeRecords}
              onSelectLayer={(layer) => {
                setActiveLayer(layer);
                setSelectedRecord(null);
              }}
              onSelectRecord={setSelectedRecord}
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
  onSelectLayer,
  onSelectRecord,
  label,
}: {
  layers: LayerSummary[];
  activeLayer: MemoryLayerId;
  activeRecords: LayerRecord[];
  onSelectLayer: (layer: MemoryLayerId) => void;
  onSelectRecord: (record: LayerRecord) => void;
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
}) {
  const selectedLayer = layers.find((layer) => layer.id === activeLayer) || layers[0];
  return (
    <section className="grid gap-3 lg:grid-cols-[230px_minmax(0,1fr)]">
      <aside className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)] p-2">
        <div className="px-2 pb-2 pt-1 text-xs font-medium text-[hsl(var(--memory-muted))]">
          {label('layers.choose', '选择层级')}
        </div>
        <div className="space-y-1.5">
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

      <div className="min-w-0 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)]">
        <div className="flex flex-col gap-3 border-b border-[hsl(var(--memory-divider)/0.58)] px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{selectedLayer.label}</h2>
            <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
              {label('layers.tableSubtitle', '{{description}}（共 {{count}} 条）', {
                description: selectedLayer.description,
                count: formatCount(selectedLayer.count),
              })}
            </p>
          </div>
          <div className="flex min-w-0 items-center gap-2 rounded-sm border border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-muted))]">
            <Search className="h-4 w-4" />
            <span>{label('layers.searchHint', '点击记录查看详情和影响')}</span>
          </div>
        </div>

        {activeRecords.length === 0 ? (
          <div className="p-4">
            <div className={MEMORY_EMPTY_PANEL_CLASS}>{label('layers.empty', '这一层暂时没有可展示的记录。')}</div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[760px]">
              <div className="grid grid-cols-[minmax(150px,1.1fr)_120px_120px_120px_92px_40px] border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
                <span>ID</span>
                <span>{label('fields.type', '类型')}</span>
                <span>{label('fields.source', '来源')}</span>
                <span>{label('fields.updatedAt', '更新时间')}</span>
                <span>{label('fields.status', '状态')}</span>
                <span />
              </div>
              <div className="divide-y divide-[hsl(var(--memory-divider)/0.46)]">
                {activeRecords.map((record) => (
                  <button
                    key={`${record.layer}:${record.id}`}
                    type="button"
                    aria-label={label('layers.openRecord', '打开记录 {{id}}', { id: record.id })}
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
    ['L1 清理', label('tasks.l1', '压缩可清理事件、清除过期负载'), 'memory-l1-maintenance:global', label('statuses.enabled', '已启用')],
    ['L2 抽取', label('tasks.l2Derive', '处理结构知识派生任务'), 'memory-l2-derive:global', label('statuses.enabled', '已启用')],
    ['L2 章节整理', label('tasks.l2Consolidate', '升级章节、经历和缺失总结'), 'memory-l2-consolidate:global', label('statuses.enabled', '已启用')],
    ['L3 总结', label('tasks.l3', '生成时段总结并清理过期内容'), 'memory-l3-summary:*', label('statuses.enabled', '已启用')],
    ['L4 整理', label('tasks.l4', '维护工具记忆和熔断状态'), 'memory_l4_maintenance', label('statuses.enabled', '已启用')],
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
        {rows.map(([name, description, scheduleId, status]) => (
          <div key={scheduleId} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[170px_minmax(0,1fr)_220px_92px] md:items-center">
            <div className="font-semibold text-[hsl(var(--memory-title))]">{name}</div>
            <div className="text-[hsl(var(--memory-body))]">{description}</div>
            <div className="truncate text-xs text-[hsl(var(--memory-muted))]">{scheduleId}</div>
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
        title={label('manual.flushTitle', '处理 L2 积压')}
        description={label('manual.flushBody', '立即提交当前暂存的 L2 微批次，适合调试抽取延迟。')}
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
        {label('forgetDrawerHint', '遗忘和删除从具体记录发起：先在「分层明细」里打开一条记录，再在抽屉中查看影响。')}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <LinkPanel to="/memory/events" title={label('forgetBySource', '按来源/事件清理')} body={label('forgetBySourceBody', '进入 L1 原始事件后按来源、时间和内容筛选。')} />
        <LinkPanel to="/memory/knowledge" title={label('forgetByEntity', '按实体处理')} body={label('forgetByEntityBody', '进入 L2 结构知识后查看实体、断言和关系。')} />
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
            {record ? `${record.layer.toUpperCase()} · ${record.id}` : label('drawer.empty', '选择一条记录查看详情。')}
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
                  <Button variant="outline" className="h-9 rounded-sm" onClick={onReplay} disabled={actionLoading || (record.layer !== 'l1' && record.type !== label('recordTypes.entity', '实体'))}>
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
