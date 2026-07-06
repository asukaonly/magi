import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Database,
  Layers3,
  ShieldAlert,
} from 'lucide-react';
import { memoryApi, type EpisodeReconsolidateResult } from '@/api/modules/memory';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame from './MemoryPageFrame';
import {
  buildLayerSummaries,
  formatCount,
  RECORD_PAGE_SIZE,
  toFiniteNumber,
  type GovernanceLabelFn,
  type GovernanceTab,
  type LayerRecord,
  type LayerSummary,
  type MaintenanceCategoryId,
} from './governanceModel';
import { LayerWorkspace } from './governance/GovernanceLayerWorkspace';
import { ManualMaintenancePanel, TaskMaintenancePanel, ForgetMaintenancePanel, DiagnosticsPanel } from './governance/GovernanceMaintenancePanels';
import { MetricCell } from './governance/GovernanceMetrics';
import { RecordDrawer } from './governance/GovernanceRecordDrawer';

export const MemoryGovernancePage = () => {
  const { t } = useTranslation('app');
  const [activeTab, setActiveTab] = useState<GovernanceTab>('objects');
  const [activeLayer, setActiveLayer] = useState<MaintenanceCategoryId>('entities');
  const [activePage, setActivePage] = useState(1);
  const [recordSearchQuery, setRecordSearchQuery] = useState('');
  const [selectedRecord, setSelectedRecord] = useState<LayerRecord | null>(null);
  const [reconsolidating, setReconsolidating] = useState(false);
  const [recordActionLoading, setRecordActionLoading] = useState(false);
  const [reconsolidateResult, setReconsolidateResult] = useState<EpisodeReconsolidateResult | null>(null);
  const [reconsolidateError, setReconsolidateError] = useState<string | null>(null);
  const [baseLayerCounts, setBaseLayerCounts] = useState<Partial<Record<MaintenanceCategoryId, number>>>({});
  const skipNextBaseCountUpdate = useRef(false);

  const memory = useMemory({ initialLoadScope: 'all' });

  const label = useCallback<GovernanceLabelFn>(
    (key, defaultValue, values) => t(`memory.governance.${key}`, { defaultValue, ...(values || {}) }),
    [t]
  );

  const layerSummaries = useMemo<LayerSummary[]>(() => buildLayerSummaries(memory, label), [memory, label]);
  const normalizedRecordSearchQuery = recordSearchQuery.trim();
  const isRecordSearchActive = normalizedRecordSearchQuery.length > 0;

  useEffect(() => {
    if (isRecordSearchActive) return;
    if (skipNextBaseCountUpdate.current) {
      skipNextBaseCountUpdate.current = false;
      return;
    }
    setBaseLayerCounts((current) => {
      let changed = false;
      const next = { ...current };
      for (const layer of layerSummaries) {
        if (next[layer.id] !== layer.count) {
          next[layer.id] = layer.count;
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [isRecordSearchActive, layerSummaries]);

  const navigationLayers = useMemo<LayerSummary[]>(
    () => (
      isRecordSearchActive
        ? layerSummaries.map((layer) => ({
            ...layer,
            count: baseLayerCounts[layer.id] ?? layer.count,
          }))
        : layerSummaries
    ),
    [baseLayerCounts, isRecordSearchActive, layerSummaries]
  );

  const activeLayerSummary = layerSummaries.find((layer) => layer.id === activeLayer) || layerSummaries[0];
  const activeRecords = activeLayerSummary.records;
  const activeTotal = activeLayerSummary.count || activeRecords.length;
  const pageCount = Math.max(1, Math.ceil(activeTotal / RECORD_PAGE_SIZE));
  const currentPage = Math.min(activePage, pageCount);
  const visibleRecords = useMemo(() => activeRecords.slice(0, RECORD_PAGE_SIZE), [activeRecords]);
  const displayTotal = activeTotal;
  const displayPage = currentPage;
  const displayPageCount = pageCount;
  const pendingAssertionCount = toFiniteNumber(memory.stats.attention?.pending_assertions);
  const openBreakerCount = toFiniteNumber(memory.stats.l4?.open_circuit_breakers);
  const l1EventCount = toFiniteNumber(memory.stats.l1?.event_count) || memory.l1Total;
  const extractSkippedCount = toFiniteNumber(memory.l2Stats?.extract_skipped);
  const currentPageParams = useCallback(() => ({
    limit: RECORD_PAGE_SIZE,
    offset: (currentPage - 1) * RECORD_PAGE_SIZE,
    ...(isRecordSearchActive ? { query: normalizedRecordSearchQuery } : {}),
  }), [currentPage, isRecordSearchActive, normalizedRecordSearchQuery]);

  const refreshCategory = async (category: MaintenanceCategoryId) => {
    const params = currentPageParams();
    switch (category) {
      case 'sessions':
        await memory.loadL0Sessions(params);
        break;
      case 'events':
        await memory.queryL1Events(params);
        break;
      case 'entities':
        await memory.loadL2Entities(params);
        break;
      case 'assertions':
        await memory.loadL2Assertions(params);
        break;
      case 'relations':
        await memory.loadL2Relations(params);
        break;
      case 'snapshots':
        await memory.loadL2Snapshots(params);
        break;
      case 'summaries':
        await memory.loadL3Summaries(params);
        break;
      case 'skills':
        await memory.loadL4Skills(params);
        break;
    }
  };

  useEffect(() => {
    const params = currentPageParams();
    switch (activeLayer) {
      case 'sessions':
        void memory.loadL0Sessions(params);
        break;
      case 'events':
        void memory.queryL1Events(params);
        break;
      case 'entities':
        void memory.loadL2Entities(params);
        break;
      case 'assertions':
        void memory.loadL2Assertions(params);
        break;
      case 'relations':
        void memory.loadL2Relations(params);
        break;
      case 'snapshots':
        void memory.loadL2Snapshots(params);
        break;
      case 'summaries':
        void memory.loadL3Summaries(params);
        break;
      case 'skills':
        void memory.loadL4Skills(params);
        break;
    }
  }, [
    activeLayer,
    currentPageParams,
    memory.loadL0Sessions,
    memory.queryL1Events,
    memory.loadL2Entities,
    memory.loadL2Assertions,
    memory.loadL2Relations,
    memory.loadL2Snapshots,
    memory.loadL3Summaries,
    memory.loadL4Skills,
  ]);

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

  const handleInvalidateSelected = async () => {
    if (!selectedRecord) return;
    setRecordActionLoading(true);
    try {
      if (selectedRecord.categoryId === 'assertions') {
        await memory.submitAssertionFeedback(selectedRecord.id, 'rejected');
        await refreshCategory('assertions');
        setSelectedRecord(null);
        return;
      }
      if (selectedRecord.categoryId === 'relations') {
        await memoryApi.rejectL2Edge(selectedRecord.id);
        await refreshCategory('relations');
        setSelectedRecord(null);
      }
    } finally {
      setRecordActionLoading(false);
    }
  };

  const handleDeleteSelected = async () => {
    if (!selectedRecord || selectedRecord.categoryId !== 'events') return;
    setRecordActionLoading(true);
    try {
      await memoryApi.deleteL1Event(selectedRecord.id);
      await refreshCategory('events');
      setSelectedRecord(null);
    } finally {
      setRecordActionLoading(false);
    }
  };

  const handleCascadeForgetSelected = async () => {
    if (!selectedRecord || selectedRecord.categoryId !== 'entities') return;
    setRecordActionLoading(true);
    try {
      await memoryApi.forgetEntity(selectedRecord.id, false);
      await refreshCategory('entities');
      setSelectedRecord(null);
    } finally {
      setRecordActionLoading(false);
    }
  };

  return (
    <MemoryPageFrame
      title={label('title', '整理')}
      description={label('objectSubtitle', '按记忆对象查看、整理、遗忘和诊断。')}
      hideHeader
      className="max-w-[1180px]"
      contentClassName="min-h-0 flex-1 overflow-hidden pb-0"
      scrollable={false}
    >
      <div className="flex h-full min-h-0 flex-col gap-4">
        <section className="grid gap-3 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)] p-3 md:grid-cols-4">
          <MetricCell icon={<Layers3 className="h-5 w-5" />} label={label('metrics.objects', '维护对象')} value={formatCount(navigationLayers.reduce((sum, layer) => sum + layer.count, 0))} />
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
              layers={navigationLayers}
              activeLayer={activeLayer}
              activeRecords={activeRecords}
              visibleRecords={visibleRecords}
              page={displayPage}
              pageCount={displayPageCount}
              pageSize={RECORD_PAGE_SIZE}
              totalRecordCount={displayTotal}
              recordSearchQuery={recordSearchQuery}
              onSelectLayer={(layer) => {
                setActiveLayer(layer);
                setActivePage(1);
                if (recordSearchQuery.trim()) skipNextBaseCountUpdate.current = true;
                setRecordSearchQuery('');
                setSelectedRecord(null);
              }}
              onRecordSearchChange={(value) => {
                if (!value.trim() && recordSearchQuery.trim()) skipNextBaseCountUpdate.current = true;
                setRecordSearchQuery(value);
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
        actionLoading={memory.l2ActionLoading || recordActionLoading}
        onReplay={() => void handleReplaySelected()}
        onInvalidate={() => void handleInvalidateSelected()}
        onDelete={() => void handleDeleteSelected()}
        onCascadeForget={() => void handleCascadeForgetSelected()}
      />
    </MemoryPageFrame>
  );
};

export default MemoryGovernancePage;
