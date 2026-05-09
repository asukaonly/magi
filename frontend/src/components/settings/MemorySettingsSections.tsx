import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, RefreshCw, RotateCcw, Trash2, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import type { VectorLayerId } from '@/api/modules/config';
import type { SystemConfig } from '@/api/modules/config';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import type { EmbeddingVectorStatus } from '@/api/modules/memory';
import memoryApi from '@/api/modules/memory';
import { ClearMemoryDialog } from '@/components/memory/ClearMemoryDialog';
import { LabeledSelectField, NumberField } from '@/components/settings/form-fields';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { pickDirectory } from '@/runtime/desktop';
import type { MemoryToggleFieldId } from '@/types/settings';

interface MemorySettingsSectionProps {
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  updateMemoryToggle: (field: MemoryToggleFieldId, checked: boolean) => void;
  hasEmbeddingModel: boolean;
}

function MemorySectionShell({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={className ?? 'space-y-8'}>{children}</div>;
}

function MemoryGroup({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div>{children}</div>
    </section>
  );
}

function MemorySwitchRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled = false,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="space-y-1">
        <div className="text-sm font-medium text-foreground">{label}</div>
        <div className="text-xs leading-6 text-muted-foreground">{description}</div>
      </div>
      <div className="flex justify-start sm:justify-end">
        <Switch checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} aria-label={label} />
      </div>
    </label>
  );
}

function DependencyNotice({
  title,
  description,
  cta,
  onRestore,
}: {
  title: string;
  description: string;
  cta: string;
  onRestore: () => void;
}) {
  return (
    <div className="border-l-2 border-[hsl(var(--settings-nav-active)/0.52)] pl-4">
      <div className="text-sm font-semibold text-foreground">{title}</div>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
      <Button type="button" variant="ghost" size="sm" className="mt-2 h-8 px-0 text-sm" onClick={onRestore}>
        {cta}
      </Button>
    </div>
  );
}

function VectorMaintenancePanel() {
  const { t } = useTranslation('app');
  const [status, setStatus] = useState<EmbeddingVectorStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const latestJob = status?.latest_job ?? null;
  const jobActive = Boolean(latestJob && !latestJob.terminal);
  const progressPercent = useMemo(() => {
    if (!latestJob) {
      return 0;
    }
    if (latestJob.total_items <= 0) {
      return latestJob.terminal ? 100 : 0;
    }
    return Math.min(100, Math.round((latestJob.processed_items / latestJob.total_items) * 100));
  }, [latestJob]);

  const refreshStatus = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    try {
      setStatus(await memoryApi.getEmbeddingVectorStatus());
    } catch {
      if (!silent) {
        toast.error(t('settings.memory.vector.statusFailed'));
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, [t]);

  useEffect(() => {
    void refreshStatus(true);
  }, [refreshStatus]);

  useEffect(() => {
    if (!jobActive) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      void refreshStatus(true);
    }, 2500);
    return () => window.clearInterval(interval);
  }, [jobActive, refreshStatus]);

  const handleStartRebuild = async () => {
    setRebuilding(true);
    try {
      const job = await memoryApi.startEmbeddingRebuild();
      setStatus((current) => current ? { ...current, latest_job: job } : current);
      await refreshStatus(true);
      toast.success(t('settings.memory.vector.rebuildStarted'));
    } catch {
      toast.error(t('settings.memory.vector.rebuildFailed'));
    } finally {
      setRebuilding(false);
    }
  };

  const handleCancelRebuild = async () => {
    if (!latestJob) {
      return;
    }
    try {
      const job = await memoryApi.cancelEmbeddingRebuild(latestJob.job_id);
      setStatus((current) => current ? { ...current, latest_job: job } : current);
      toast.success(t('settings.memory.vector.cancelRequested'));
    } catch {
      toast.error(t('settings.memory.vector.cancelFailed'));
    }
  };

  const readyEntries = Object.entries(status?.ready_counts ?? {}) as Array<[VectorLayerId, number]>;
  const activeLabel = latestJob?.active_layer ? t(`settings.memory.vector.layers.${latestJob.active_layer}`) : '';

  return (
    <div className="py-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="text-sm font-medium text-foreground">{t('settings.memory.vector.title')}</div>
          <p className="max-w-3xl text-xs leading-6 text-muted-foreground">
            {t('settings.memory.vector.description')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void refreshStatus()}
            disabled={loading}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('settings.memory.vector.refresh')}
          </Button>
          {jobActive ? (
            <Button type="button" variant="outline" size="sm" onClick={() => void handleCancelRebuild()}>
              <XCircle className="mr-2 h-4 w-4" />
              {t('settings.memory.vector.cancel')}
            </Button>
          ) : (
            <Button type="button" variant="outline" size="sm" onClick={() => void handleStartRebuild()} disabled={rebuilding}>
              <RotateCcw className="mr-2 h-4 w-4" />
              {t('settings.memory.vector.rebuild')}
            </Button>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {readyEntries.map(([layer, count]) => (
          <div key={layer} className="rounded-md border border-border/70 px-3 py-2">
            <div className="text-xs text-muted-foreground">{t(`settings.memory.vector.layers.${layer}`)}</div>
            <div className="mt-1 text-sm font-semibold text-foreground">{count}</div>
          </div>
        ))}
      </div>

      {latestJob ? (
        <div className="mt-3 space-y-2 text-xs leading-6 text-muted-foreground">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>{t(`settings.memory.vector.status.${latestJob.status}`)}</span>
            {activeLabel ? <span>{t('settings.memory.vector.activeLayer', { layer: activeLabel })}</span> : null}
            <span>{t('settings.memory.vector.progress', {
              processed: latestJob.processed_items,
              total: latestJob.total_items,
              percent: progressPercent,
            })}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-[hsl(var(--settings-nav-active))] transition-all"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          {latestJob.error ? <p className="text-destructive">{latestJob.error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function MemoryGeneralSettingsSection({
  draftConfig,
  patchDraftConfig,
}: Omit<MemorySettingsSectionProps, 'updateMemoryToggle' | 'hasEmbeddingModel'>) {
  const { t } = useTranslation('app');
  const [pickingMemoryStoragePath, setPickingMemoryStoragePath] = useState(false);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const memoryStoragePath = draftConfig.memory.db_path ?? '';
  const historyBehaviorOptions = [
    { value: 'delete', label: t('settings.memory.options.history_behavior.delete') },
    { value: 'archive', label: t('settings.memory.options.history_behavior.archive') },
  ];
  const rerankerConfig = {
    ...DEFAULT_SYSTEM_CONFIG.memory.reranker,
    ...draftConfig.memory.reranker,
    cross_encoder: {
      ...DEFAULT_SYSTEM_CONFIG.memory.reranker.cross_encoder,
      ...draftConfig.memory.reranker?.cross_encoder,
    },
  };
  const queryExpansionConfig = {
    ...DEFAULT_SYSTEM_CONFIG.memory.query_expansion,
    ...draftConfig.memory.query_expansion,
  };

  const handlePickMemoryStoragePath = async () => {
    setPickingMemoryStoragePath(true);
    try {
      const selectedPath = await pickDirectory(memoryStoragePath || null);
      if (!selectedPath) {
        return;
      }
      patchDraftConfig((draft) => {
        draft.memory.db_path = selectedPath;
      });
    } finally {
      setPickingMemoryStoragePath(false);
    }
  };

  const handleClearConfirm = useCallback(async () => {
    setClearing(true);
    try {
      const result = await memoryApi.clearAll();
      toast.success(t('settings.memoryCleared', { count: result.results?.l0?.count ?? 0 }));
      setClearDialogOpen(false);
    } catch {
      toast.error(t('settings.memoryClearFailed'));
    } finally {
      setClearing(false);
    }
  }, [t]);

  return (
    <MemorySectionShell className="space-y-0">
      <MemoryGroup>
        <div className="py-2">
          <div className="space-y-2">
            <label className="space-y-2" htmlFor="memory-storage-path">
              <span className="text-sm font-medium text-foreground">
                {t('settings.memory.fields.db_path.label')}
              </span>
              <Input
                id="memory-storage-path"
                aria-label={t('settings.memory.fields.db_path.label')}
                readOnly
                value={memoryStoragePath}
                placeholder={t('settings.memory.fields.db_path.placeholder')}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  void handlePickMemoryStoragePath();
                }}
                disabled={pickingMemoryStoragePath}
              >
                <FolderOpen className="mr-2 h-4 w-4" />
                {t('settings.actions.chooseDirectory')}
              </Button>
            </div>
          </div>
          <div className="mt-2 space-y-1">
            <p className="text-xs leading-6 text-muted-foreground">{t('settings.memory.fields.db_path.description')}</p>
            <p className="text-xs leading-6 text-amber-600 dark:text-amber-300">{t('settings.memory.fields.db_path.runtimeHint')}</p>
          </div>
        </div>
      </MemoryGroup>

      <MemoryGroup>
        <div className="grid gap-6 py-2 lg:grid-cols-2">
          <div>
            <NumberField
              label={t('settings.memory.fields.retention_days.label')}
              value={draftConfig.memory.retention_days}
              min={1}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.memory.retention_days = value;
              })}
            />
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              {t('settings.memory.fields.retention_days.description')}
            </p>
          </div>
          <div>
            <LabeledSelectField
              label={t('settings.memory.fields.history_behavior.label')}
              ariaLabel={t('settings.memory.fields.history_behavior.label')}
              value={draftConfig.memory.history_behavior}
              options={historyBehaviorOptions}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.memory.history_behavior = value as 'delete' | 'archive';
              })}
            />
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              {t('settings.memory.fields.history_behavior.description')}
            </p>
          </div>
        </div>
      </MemoryGroup>

      <MemoryGroup>
        <div className="py-2">
          <MemorySwitchRow
            label={t('settings.memory.fields.query_expansion_enabled.label')}
            description={t('settings.memory.fields.query_expansion_enabled.description')}
            checked={queryExpansionConfig.enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.memory.query_expansion ??= { ...DEFAULT_SYSTEM_CONFIG.memory.query_expansion };
              draft.memory.query_expansion.enabled = checked;
            })}
          />

          <MemorySwitchRow
            label={t('settings.memory.fields.cross_encoder_enabled.label')}
            description={t('settings.memory.fields.cross_encoder_enabled.description')}
            checked={rerankerConfig.cross_encoder.enabled}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.memory.reranker.cross_encoder ??= { ...DEFAULT_SYSTEM_CONFIG.memory.reranker.cross_encoder };
              draft.memory.reranker.cross_encoder.enabled = checked;
            })}
          />

          {rerankerConfig.cross_encoder.enabled ? (
            <div className="pt-3 pb-2">
              <NumberField
                label={t('settings.memory.fields.reranker_top_k.label')}
                value={rerankerConfig.top_k}
                min={1}
                onChange={(value) => patchDraftConfig((draft) => {
                  draft.memory.reranker.top_k = value;
                })}
              />
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {t('settings.memory.fields.cross_encoder_model_hint')}
              </p>
            </div>
          ) : null}
        </div>
      </MemoryGroup>

      <MemoryGroup>
        <VectorMaintenancePanel />
      </MemoryGroup>

      {/* Danger zone — clear all memory */}
      <MemoryGroup>
        <div className="py-2">
          <div className="space-y-1">
            <div className="text-sm font-medium text-destructive">
              {t('settings.memory.dangerZone.title')}
            </div>
            <div className="text-xs leading-6 text-muted-foreground">
              {t('settings.memory.dangerZone.description')}
            </div>
          </div>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="mt-3"
            onClick={() => setClearDialogOpen(true)}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            {t('settings.memory.dangerZone.clearButton')}
          </Button>
        </div>
      </MemoryGroup>

      <ClearMemoryDialog
        open={clearDialogOpen}
        onOpenChange={setClearDialogOpen}
        clearing={clearing}
        onConfirm={handleClearConfirm}
      />
    </MemorySectionShell>
  );
}

export function MemoryWorkbenchSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
}: Pick<MemorySettingsSectionProps, 'draftConfig' | 'patchDraftConfig' | 'updateMemoryToggle'>) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      <MemoryGroup>
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l0.label')}
          description={t('settings.memory.fields.enable_l0.description')}
          checked={draftConfig.memory.l0.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l0', checked)}
        />
        <div className="py-3">
          <NumberField
            label={t('settings.memory.fields.l0_checkpoint_interval_seconds.label')}
            value={draftConfig.memory.l0.checkpoint_interval_seconds}
            min={1}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l0.checkpoint_interval_seconds = value;
            })}
          />
        </div>
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemoryEventsSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
  hasEmbeddingModel,
}: MemorySettingsSectionProps) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      <MemoryGroup>
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l1.label')}
          description={t('settings.memory.fields.enable_l1.description')}
          checked={draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l1', checked)}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l1_vectorization.label')}
          description={
            hasEmbeddingModel
              ? t('settings.memory.fields.enable_l1_vectorization.description')
              : t('settings.memory.fields.enable_l1_vectorization.description_disabled')
          }
          checked={draftConfig.memory.l1.vectors_enabled ?? false}
          disabled={!draftConfig.memory.l1.enabled || !hasEmbeddingModel}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l1.vectors_enabled = checked;
          })}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemoryKnowledgeSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
  hasEmbeddingModel,
}: Pick<MemorySettingsSectionProps, 'draftConfig' | 'patchDraftConfig' | 'updateMemoryToggle' | 'hasEmbeddingModel'>) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      {!draftConfig.memory.l1.enabled ? (
        <DependencyNotice
          title={t('settings.memory.form.l1DependencyTitle')}
          description={t('settings.memory.form.l1DependencyDescription')}
          cta={t('settings.memory.form.restoreL1')}
          onRestore={() => updateMemoryToggle('l1', true)}
        />
      ) : null}

      <MemoryGroup>
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l2.label')}
          description={t('settings.memory.fields.enable_l2.description')}
          checked={draftConfig.memory.l2.enabled}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l2', checked)}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l2_vectorization.label')}
          description={
            hasEmbeddingModel
              ? t('settings.memory.fields.enable_l2_vectorization.description')
              : t('settings.memory.fields.enable_l2_vectorization.description_disabled')
          }
          checked={draftConfig.memory.l2.vectors_enabled ?? false}
          disabled={!draftConfig.memory.l2.enabled || !hasEmbeddingModel}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l2.vectors_enabled = checked;
          })}
        />
        <div className="py-3">
          <NumberField
            label={t('settings.memory.fields.l2_batch_flush_interval_seconds.label')}
            value={draftConfig.memory.l2.batch_flush_interval_seconds}
            min={30}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l2.batch_flush_interval_seconds = value;
            })}
          />
          <p className="mt-2 text-xs leading-6 text-muted-foreground">
            {t('settings.memory.fields.l2_batch_flush_interval_seconds.description')}
          </p>
        </div>
      </MemoryGroup>

      <MemoryGroup>
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l2_conflict_arbitration.label')}
          description={t('settings.memory.fields.enable_l2_conflict_arbitration.description')}
          checked={draftConfig.memory.l2.conflict_arbitration_enabled ?? true}
          disabled={!draftConfig.memory.l2.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l2.conflict_arbitration_enabled = checked;
          })}
        />
        <div className="py-3">
          <NumberField
            label={t('settings.memory.fields.l2_conflict_arbitration_min_confidence.label')}
            value={draftConfig.memory.l2.conflict_arbitration_min_confidence}
            min={0}
            max={1}
            step={0.05}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l2.conflict_arbitration_min_confidence = value;
            })}
          />
          <p className="mt-2 text-xs leading-6 text-muted-foreground">
            {t('settings.memory.fields.l2_conflict_arbitration_min_confidence.description')}
          </p>
        </div>
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemoryReflectionSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
  hasEmbeddingModel,
}: MemorySettingsSectionProps) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      {!draftConfig.memory.l1.enabled ? (
        <DependencyNotice
          title={t('settings.memory.form.l1DependencyTitle')}
          description={t('settings.memory.form.l1DependencyDescription')}
          cta={t('settings.memory.form.restoreL1')}
          onRestore={() => updateMemoryToggle('l1', true)}
        />
      ) : null}

      <MemoryGroup>
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l3.label')}
          description={t('settings.memory.fields.enable_l3.description')}
          checked={draftConfig.memory.l3.enabled}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l3', checked)}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l3_llm_summary.label')}
          description={t('settings.memory.fields.enable_l3_llm_summary.description')}
          checked={draftConfig.memory.l3.llm_summary_enabled ?? false}
          disabled={!draftConfig.memory.l3.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l3.llm_summary_enabled = checked;
          })}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l3_vectorization.label')}
          description={
            hasEmbeddingModel
              ? t('settings.memory.fields.enable_l3_vectorization.description')
              : t('settings.memory.fields.enable_l3_vectorization.description_disabled')
          }
          checked={draftConfig.memory.l3.vectors_enabled ?? false}
          disabled={!draftConfig.memory.l3.enabled || !hasEmbeddingModel}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l3.vectors_enabled = checked;
          })}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemorySkillsSettingsSection({
  draftConfig,
  updateMemoryToggle,
}: Pick<MemorySettingsSectionProps, 'draftConfig' | 'updateMemoryToggle'>) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      {!draftConfig.memory.l1.enabled ? (
        <DependencyNotice
          title={t('settings.memory.form.l1DependencyTitle')}
          description={t('settings.memory.form.l1DependencyDescription')}
          cta={t('settings.memory.form.restoreL1')}
          onRestore={() => updateMemoryToggle('l1', true)}
        />
      ) : null}

      <MemoryGroup>
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l4.label')}
          description={t('settings.memory.fields.enable_l4.description')}
          checked={draftConfig.memory.l4.enabled}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l4', checked)}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}
