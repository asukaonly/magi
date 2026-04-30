import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import type { SystemConfig } from '@/api/modules/config';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
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
  bordered = true,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  bordered?: boolean;
}) {
  return (
    <label className={[
      'grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start',
      bordered ? 'border-b border-[hsl(var(--settings-subnav-border)/0.6)]' : '',
    ].join(' ').trim()}>
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
            bordered={false}
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
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
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
      </MemoryGroup>

      <MemoryGroup>
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
      </MemoryGroup>

      <MemoryGroup>
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
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
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
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
