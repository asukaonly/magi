import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { memoryApi, type EpisodeReconsolidateResult } from '@/api/modules/memory';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
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
import { RecordDrawer } from './governance/GovernanceRecordDrawer';

export const MemoryGovernancePage = () => {
  const { t } = useTranslation('app');
  const [activeTab, setActiveTab] = useState<GovernanceTab>('objects');
  const [activeLayer, setActiveLayer] = useState<MaintenanceCategoryId>('entities');
  const [activePage, setActivePage] = useState(1);
  const [recordSearchQuery, setRecordSearchQuery] = useState('');
  const [selectedRecord, setSelectedRecord] = useState<LayerRecord | null>(null);
  const [recordLoading, setRecordLoading] = useState(true);
  const [recordLoadError, setRecordLoadError] = useState<string | null>(null);
  const [reconsolidating, setReconsolidating] = useState(false);
  const [recordActionLoading, setRecordActionLoading] = useState(false);
  const [correctionDialogOpen, setCorrectionDialogOpen] = useState(false);
  const [correctionSaved, setCorrectionSaved] = useState(false);
  const [correctionConflict, setCorrectionConflict] = useState(false);
  const [reconsolidateResult, setReconsolidateResult] = useState<EpisodeReconsolidateResult | null>(null);
  const [reconsolidateError, setReconsolidateError] = useState<string | null>(null);
  const [baseLayerCounts, setBaseLayerCounts] = useState<Partial<Record<MaintenanceCategoryId, number>>>({});
  const skipNextBaseCountUpdate = useRef(false);
  const recordRequestId = useRef(0);

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
  const objectCount = navigationLayers.reduce((sum, layer) => sum + layer.count, 0);
  const hasMemoryData = objectCount > 0 || l1EventCount > 0;
  const hasAttentionIssues = pendingAssertionCount > 0 || openBreakerCount > 0;
  const currentPageParams = useCallback(() => ({
    limit: RECORD_PAGE_SIZE,
    offset: (currentPage - 1) * RECORD_PAGE_SIZE,
    ...(isRecordSearchActive ? { query: normalizedRecordSearchQuery } : {}),
  }), [currentPage, isRecordSearchActive, normalizedRecordSearchQuery]);

  const correctionTarget = useMemo<MemoryCorrectionUiTarget | null>(() => {
    if (!selectedRecord?.correction) return null;
    if (selectedRecord.correction.kind === 'assertion') {
      return {
        kind: 'assertion',
        id: selectedRecord.id,
        statement: selectedRecord.title,
        currentValue: selectedRecord.correction.currentValue,
        expectedUpdatedAt: selectedRecord.correction.expectedUpdatedAt,
      };
    }

    const entityOptions = memory.l2Entities.map((entity) => ({
      id: entity.entity_id,
      name: entity.canonical_name,
      type: entity.entity_type,
    }));
    const relationship = selectedRecord.correction.relationship;
    if (!entityOptions.some((entity) => entity.id === relationship.subjectId)) {
      entityOptions.push({ id: relationship.subjectId, name: relationship.subjectName, type: relationship.subjectType });
    }
    if (!entityOptions.some((entity) => entity.id === relationship.objectId)) {
      entityOptions.push({ id: relationship.objectId, name: relationship.objectName, type: relationship.objectType });
    }
    return {
      kind: 'edge',
      id: selectedRecord.id,
      statement: selectedRecord.title,
      expectedUpdatedAt: selectedRecord.correction.expectedUpdatedAt,
      relationship,
      entityOptions,
    };
  }, [memory.l2Entities, selectedRecord]);

  const loadCategoryRecords = useCallback(async (
    category: MaintenanceCategoryId,
    params: ReturnType<typeof currentPageParams>
  ) => {
    const requestId = recordRequestId.current + 1;
    recordRequestId.current = requestId;
    setRecordLoading(true);
    setRecordLoadError(null);

    let loaded: boolean | void = true;
    switch (category) {
      case 'sessions':
        loaded = await memory.loadL0Sessions(params);
        break;
      case 'events':
        loaded = await memory.queryL1Events(params);
        break;
      case 'entities':
        loaded = await memory.loadL2Entities(params);
        break;
      case 'assertions':
        loaded = await memory.loadL2Assertions({ ...params, include_inactive: true });
        break;
      case 'relations':
        loaded = await memory.loadL2Relations({ ...params, include_inactive: true });
        break;
      case 'snapshots':
        loaded = await memory.loadL2Snapshots(params);
        break;
      case 'summaries':
        loaded = await memory.loadL3Summaries(params);
        break;
      case 'skills':
        loaded = await memory.loadL4Skills(params);
        break;
    }

    if (requestId !== recordRequestId.current) return;
    if (loaded === false) {
      setRecordLoadError('load_failed');
    }
    setRecordLoading(false);
  }, [
    memory.loadL0Sessions,
    memory.queryL1Events,
    memory.loadL2Entities,
    memory.loadL2Assertions,
    memory.loadL2Relations,
    memory.loadL2Snapshots,
    memory.loadL3Summaries,
    memory.loadL4Skills,
  ]);

  const refreshCategory = async (category: MaintenanceCategoryId): Promise<boolean> => {
    const params = currentPageParams();
    let loaded: boolean | void = true;
    switch (category) {
      case 'sessions':
        loaded = await memory.loadL0Sessions(params);
        break;
      case 'events':
        loaded = await memory.queryL1Events(params);
        break;
      case 'entities':
        loaded = await memory.loadL2Entities(params);
        break;
      case 'assertions':
        loaded = await memory.loadL2Assertions({ ...params, include_inactive: true });
        break;
      case 'relations':
        loaded = await memory.loadL2Relations({ ...params, include_inactive: true });
        break;
      case 'snapshots':
        loaded = await memory.loadL2Snapshots(params);
        break;
      case 'summaries':
        loaded = await memory.loadL3Summaries(params);
        break;
      case 'skills':
        loaded = await memory.loadL4Skills(params);
        break;
    }
    return loaded !== false;
  };

  useEffect(() => {
    const params = currentPageParams();
    void loadCategoryRecords(activeLayer, params);
  }, [
    activeLayer,
    currentPageParams,
    loadCategoryRecords,
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

  const refreshSelectedCorrectionTarget = async () => {
    if (!selectedRecord) return;
    if (selectedRecord.categoryId === 'assertions' || selectedRecord.categoryId === 'relations') {
      const refreshed = await refreshCategory(selectedRecord.categoryId);
      return refreshed;
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
      title={label('title', '记忆管理')}
      description={label('objectSubtitle', '按记忆对象查看、整理、遗忘和诊断。')}
      hideHeader
      className="max-w-[1280px] px-5 py-5 lg:px-7 lg:py-6"
      contentClassName="min-h-0 flex-1 overflow-hidden pb-0"
      scrollable={false}
    >
      <div className="flex h-full min-h-0 flex-col">
        <h1 className="sr-only">{label('title', '记忆管理')}</h1>
        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as GovernanceTab)} className="flex min-h-0 flex-1 flex-col space-y-5">
          <div className="flex shrink-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0 flex-1 overflow-x-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.72)]">
              <TabsList className="inline-flex h-auto min-w-max justify-start gap-7 bg-transparent p-0">
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
                    className="relative rounded-none bg-transparent px-0 py-2.5 text-sm font-medium text-[hsl(var(--memory-muted))] shadow-none transition-colors duration-200 after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:origin-center after:scale-x-0 after:rounded-sm after:bg-[hsl(var(--memory-accent))] after:transition-transform after:duration-200 hover:text-[hsl(var(--memory-title))] data-[state=active]:bg-transparent data-[state=active]:text-[hsl(var(--memory-title))] data-[state=active]:shadow-none data-[state=active]:after:scale-x-100"
                  >
                    {text}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>

            <div
              data-testid="governance-status-summary"
              className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-2 px-1 text-xs text-[hsl(var(--memory-muted))] lg:justify-end"
            >
              <span className="inline-flex items-center gap-2 font-medium text-[hsl(var(--memory-body))]">
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 rounded-full ${
                    hasAttentionIssues
                      ? 'bg-amber-500'
                      : hasMemoryData
                        ? 'bg-emerald-500'
                        : 'bg-[hsl(var(--memory-muted))]'
                  }`}
                />
                {hasAttentionIssues
                  ? label('status.needsAttention', '需要处理')
                  : hasMemoryData
                    ? label('status.healthy', '运行正常')
                    : label('status.awaitingData', '等待记忆数据')}
              </span>
              <span>{label('status.objects', '{{count}} 个对象', { count: formatCount(objectCount) })}</span>
              <span>{label('status.events', '{{count}} 条原始事件', { count: formatCount(l1EventCount) })}</span>
              {pendingAssertionCount > 0 ? (
                <span className="font-medium text-amber-700 dark:text-amber-400">
                  {label('status.pending', '{{count}} 条待处理', { count: formatCount(pendingAssertionCount) })}
                </span>
              ) : null}
              {openBreakerCount > 0 ? (
                <span className="font-medium text-red-700 dark:text-red-400">
                  {label('status.breakers', '{{count}} 个工具异常', { count: formatCount(openBreakerCount) })}
                </span>
              ) : null}
            </div>
          </div>

          <TabsContent value="objects" className="mt-0 min-h-0 flex-1 overflow-y-auto lg:overflow-hidden">
            <LayerWorkspace
              layers={navigationLayers}
              activeLayer={activeLayer}
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
              loading={recordLoading}
              error={recordLoadError ? label('objects.loadFailedBody', '暂时无法读取这类记录，请稍后重试。') : null}
              onRetry={() => void loadCategoryRecords(activeLayer, currentPageParams())}
              label={label}
            />
          </TabsContent>

          <TabsContent value="tasks" className="mt-0 overflow-y-auto">
            <TaskMaintenancePanel label={label} />
          </TabsContent>

          <TabsContent value="manual" className="mt-0 overflow-y-auto">
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

          <TabsContent value="forget" className="mt-0 overflow-y-auto">
            <ForgetMaintenancePanel label={label} />
          </TabsContent>

          <TabsContent value="diagnostics" className="mt-0 overflow-y-auto">
            <DiagnosticsPanel label={label} diagnostics={diagnostics} />
          </TabsContent>
        </Tabs>
      </div>

      <RecordDrawer
        record={selectedRecord}
        open={selectedRecord !== null && !correctionDialogOpen}
        onOpenChange={(open) => {
          if (!open) setSelectedRecord(null);
        }}
        label={label}
        actionLoading={memory.l2ActionLoading || recordActionLoading}
        correctionTarget={correctionTarget}
        onReplay={() => void handleReplaySelected()}
        onCorrect={() => {
          setCorrectionSaved(false);
          setCorrectionConflict(false);
          setCorrectionDialogOpen(true);
        }}
        onCorrectionReverted={async () => {
          const refreshed = await refreshSelectedCorrectionTarget();
          setSelectedRecord(null);
          toast.success(t('memory.correction.history.revertSuccess', { defaultValue: '已撤销这次修正' }));
          if (refreshed === false) {
            toast.warning(t('memory.correction.refreshFailed', { defaultValue: '修正已撤销，但列表暂时没有刷新。' }));
          }
        }}
        onCorrectionConflict={async () => {
          await refreshSelectedCorrectionTarget();
        }}
        onDelete={() => void handleDeleteSelected()}
        onCascadeForget={() => void handleCascadeForgetSelected()}
      />
      <MemoryCorrectionDialog
        open={correctionDialogOpen}
        target={correctionTarget}
        onOpenChange={(open) => {
          setCorrectionDialogOpen(open);
          if (!open && (correctionSaved || correctionConflict)) {
            setCorrectionSaved(false);
            setCorrectionConflict(false);
            setSelectedRecord(null);
          }
        }}
        onSaved={async () => {
          setCorrectionSaved(true);
          const refreshed = await refreshSelectedCorrectionTarget();
          if (refreshed === false) {
            toast.warning(t('memory.correction.refreshFailed', { defaultValue: '修正已保存，但列表暂时没有刷新。' }));
          }
        }}
        onConflict={async () => {
          setCorrectionConflict(true);
          const refreshed = await refreshSelectedCorrectionTarget();
          if (refreshed === false) {
            toast.warning(t('memory.correction.latestRefreshFailed', {
              defaultValue: '暂时无法读取最新内容，请稍后再试。',
            }));
          }
        }}
      />
    </MemoryPageFrame>
  );
};

export default MemoryGovernancePage;
