import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen } from 'lucide-react';

import type { SystemConfig } from '@/api/modules/config';
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

const MANAGED_RERANKER_MODELS_PATH = '~/.magi/cache/models/rerank';
const MEMORY_RERANKER_LAYER_ORDER = ['L1', 'L3', 'L4'] as const;

function MemorySectionShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="space-y-8">{children}</div>;
}

function MemoryGroup({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="space-y-2">{children}</div>
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
    <label className="grid gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
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

function MemoryMetricRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 last:border-b-0">
      <div className="text-xs tracking-[0.02em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-medium text-foreground">{value}</div>
      {hint ? <div className="mt-1 text-xs leading-6 text-muted-foreground">{hint}</div> : null}
    </div>
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
  hasEmbeddingModel,
}: Omit<MemorySettingsSectionProps, 'updateMemoryToggle'>) {
  const { t } = useTranslation('app');
  const embeddingSelection = draftConfig.llm?.selections?.embedding;
  const [pickingMemoryStoragePath, setPickingMemoryStoragePath] = useState(false);
  const memoryStoragePath = draftConfig.memory.db_path ?? '';
  const rerankerConfig = draftConfig.memory.reranker;
  const managedModelPath = rerankerConfig.local?.managed_model_id?.trim()
    ? `${MANAGED_RERANKER_MODELS_PATH}/${rerankerConfig.local.managed_model_id.trim()}`
    : `${MANAGED_RERANKER_MODELS_PATH}/<managed_model_id>`;

  const patchReranker = (updater: (draft: SystemConfig['memory']['reranker']) => void) => {
    patchDraftConfig((draft) => {
      updater(draft.memory.reranker);
    });
  };

  const updateRerankerLayer = (layer: (typeof MEMORY_RERANKER_LAYER_ORDER)[number], enabled: boolean) => {
    patchReranker((reranker) => {
      const nextLayers = enabled
        ? [...reranker.layers, layer]
        : reranker.layers.filter((item) => item !== layer);
      reranker.layers = MEMORY_RERANKER_LAYER_ORDER.filter((item) => nextLayers.includes(item));
    });
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

  return (
    <MemorySectionShell>
      <MemoryGroup>
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
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
          <p className="mt-2 text-xs leading-6 text-muted-foreground">{t('settings.memory.fields.db_path.description')}</p>
        </div>
      </MemoryGroup>

      <MemoryGroup>
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
            <MemorySwitchRow
              label={t('settings.memory.fields.reranker_enabled.label')}
              description={t('settings.memory.fields.reranker_enabled.description')}
              checked={rerankerConfig.enabled}
              onCheckedChange={(checked) => patchReranker((reranker) => {
                reranker.enabled = checked;
              })}
            />

            {rerankerConfig.enabled ? (
              <div className="grid gap-6 py-4 lg:grid-cols-2">
                <div className="space-y-4">
                  <LabeledSelectField
                    label={t('settings.memory.fields.reranker_backend.label')}
                    ariaLabel={t('settings.memory.fields.reranker_backend.label')}
                    value={rerankerConfig.backend}
                    options={[
                      {
                        label: t('settings.memory.options.reranker_backend.heuristic'),
                        value: 'heuristic',
                      },
                      {
                        label: t('settings.memory.options.reranker_backend.llm'),
                        value: 'llm',
                      },
                    ]}
                    onChange={(value) => patchReranker((reranker) => {
                      reranker.backend = value as typeof reranker.backend;
                    })}
                  />

                  <div className="grid gap-4 sm:grid-cols-2">
                    <NumberField
                      label={t('settings.memory.fields.reranker_top_k.label')}
                      value={rerankerConfig.top_k}
                      min={1}
                      onChange={(value) => patchReranker((reranker) => {
                        reranker.top_k = value;
                      })}
                    />
                    <NumberField
                      label={t('settings.memory.fields.reranker_timeout_seconds.label')}
                      value={rerankerConfig.timeout_seconds}
                      min={0.1}
                      step={0.1}
                      onChange={(value) => patchReranker((reranker) => {
                        reranker.timeout_seconds = value;
                      })}
                    />
                  </div>

                  <NumberField
                    label={t('settings.memory.fields.reranker_candidate_max_chars.label')}
                    value={rerankerConfig.candidate_max_chars}
                    min={50}
                    onChange={(value) => patchReranker((reranker) => {
                      reranker.candidate_max_chars = value;
                    })}
                  />
                </div>

                <div className="space-y-4">
                  <div className="rounded-md border border-[hsl(var(--settings-subnav-border)/0.6)] px-4 py-3">
                    <div className="text-sm font-medium text-foreground">
                      {t('settings.memory.fields.reranker_layers.label')}
                    </div>
                    <div className="mt-3 space-y-2">
                      <MemorySwitchRow
                        label={t('settings.memory.fields.reranker_layers.l1.label')}
                        description={t('settings.memory.fields.reranker_layers.l1.description')}
                        checked={rerankerConfig.layers.includes('L1')}
                        onCheckedChange={(checked) => updateRerankerLayer('L1', checked)}
                      />
                      <MemorySwitchRow
                        label={t('settings.memory.fields.reranker_layers.l3.label')}
                        description={t('settings.memory.fields.reranker_layers.l3.description')}
                        checked={rerankerConfig.layers.includes('L3')}
                        onCheckedChange={(checked) => updateRerankerLayer('L3', checked)}
                      />
                      <MemorySwitchRow
                        label={t('settings.memory.fields.reranker_layers.l4.label')}
                        description={t('settings.memory.fields.reranker_layers.l4.description')}
                        checked={rerankerConfig.layers.includes('L4')}
                        onCheckedChange={(checked) => updateRerankerLayer('L4', checked)}
                      />
                    </div>
                  </div>

                  {rerankerConfig.backend === 'llm' ? (
                    <LabeledSelectField
                      label={t('settings.memory.fields.reranker_mode.label')}
                      ariaLabel={t('settings.memory.fields.reranker_mode.label')}
                      value={rerankerConfig.mode}
                      options={[
                        { label: t('settings.options.local'), value: 'local' },
                        { label: t('settings.options.remote'), value: 'remote' },
                      ]}
                      onChange={(value) => patchReranker((reranker) => {
                        reranker.mode = value as typeof reranker.mode;
                      })}
                    />
                  ) : null}
                </div>
              </div>
            ) : null}

            {rerankerConfig.enabled && rerankerConfig.backend === 'llm' && rerankerConfig.mode === 'local' ? (
              <div className="grid gap-6 border-t border-[hsl(var(--settings-subnav-border)/0.6)] py-4 lg:grid-cols-2">
                <div className="space-y-4">
                  <LabeledSelectField
                    label={t('settings.memory.fields.reranker_local_model_source.label')}
                    ariaLabel={t('settings.memory.fields.reranker_local_model_source.label')}
                    value={rerankerConfig.local.model_source}
                    options={[
                      {
                        label: t('settings.memory.options.reranker_local_model_source.managed'),
                        value: 'managed',
                      },
                      {
                        label: t('settings.memory.options.reranker_local_model_source.external'),
                        value: 'external',
                      },
                    ]}
                    onChange={(value) => patchReranker((reranker) => {
                      reranker.local.model_source = value as typeof reranker.local.model_source;
                    })}
                  />

                  {rerankerConfig.local.model_source === 'managed' ? (
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-foreground">
                        {t('settings.memory.fields.reranker_local_managed_model_id.label')}
                      </span>
                      <Input
                        aria-label={t('settings.memory.fields.reranker_local_managed_model_id.label')}
                        value={rerankerConfig.local.managed_model_id ?? ''}
                        onChange={(event) => patchReranker((reranker) => {
                          reranker.local.managed_model_id = event.target.value || null;
                        })}
                        placeholder={t('settings.memory.fields.reranker_local_managed_model_id.placeholder')}
                      />
                    </label>
                  ) : (
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-foreground">
                        {t('settings.memory.fields.reranker_local_model_file_path.label')}
                      </span>
                      <Input
                        aria-label={t('settings.memory.fields.reranker_local_model_file_path.label')}
                        value={rerankerConfig.local.model_file_path ?? ''}
                        onChange={(event) => patchReranker((reranker) => {
                          reranker.local.model_file_path = event.target.value || null;
                        })}
                        placeholder={t('settings.memory.fields.reranker_local_model_file_path.placeholder')}
                      />
                    </label>
                  )}

                  <NumberField
                    label={t('settings.memory.fields.reranker_local_max_context_tokens.label')}
                    value={rerankerConfig.local.max_context_tokens}
                    min={1}
                    onChange={(value) => patchReranker((reranker) => {
                      reranker.local.max_context_tokens = value;
                    })}
                  />
                </div>

                <div className="space-y-3">
                  <MemoryMetricRow
                    label={t('settings.memory.fields.reranker_local_managed_cache_path.label')}
                    value={MANAGED_RERANKER_MODELS_PATH}
                    hint={t('settings.memory.fields.reranker_local_managed_cache_path.description')}
                  />
                  {rerankerConfig.local.model_source === 'managed' ? (
                    <MemoryMetricRow
                      label={t('settings.memory.fields.reranker_local_managed_model_path.label')}
                      value={managedModelPath}
                    />
                  ) : null}
                </div>
              </div>
            ) : null}

            {rerankerConfig.enabled && rerankerConfig.backend === 'llm' && rerankerConfig.mode === 'remote' ? (
              <div className="grid gap-6 border-t border-[hsl(var(--settings-subnav-border)/0.6)] py-4 lg:grid-cols-2">
                <label className="space-y-2">
                  <span className="text-sm font-medium text-foreground">
                    {t('settings.memory.fields.reranker_remote_provider_id.label')}
                  </span>
                  <Input
                    aria-label={t('settings.memory.fields.reranker_remote_provider_id.label')}
                    value={rerankerConfig.remote.provider_id}
                    onChange={(event) => patchReranker((reranker) => {
                      reranker.remote.provider_id = event.target.value;
                    })}
                    placeholder={t('settings.memory.fields.reranker_remote_provider_id.placeholder')}
                  />
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-medium text-foreground">
                    {t('settings.memory.fields.reranker_remote_model.label')}
                  </span>
                  <Input
                    aria-label={t('settings.memory.fields.reranker_remote_model.label')}
                    value={rerankerConfig.remote.model}
                    onChange={(event) => patchReranker((reranker) => {
                      reranker.remote.model = event.target.value;
                    })}
                    placeholder={t('settings.memory.fields.reranker_remote_model.placeholder')}
                  />
                </label>
              </div>
            ) : null}
          </div>

          {hasEmbeddingModel ? (
            <div>
              <MemoryMetricRow
                label={t('settings.fields.provider')}
                value={embeddingSelection.provider_id || '-'}
              />
              <MemoryMetricRow
                label={t('settings.fields.model')}
                value={embeddingSelection.model || '-'}
              />
              <MemoryMetricRow
                label={t('settings.memory.fields.db_path.label')}
                value={memoryStoragePath || '-'}
                hint={t('settings.memory.fields.db_path.summary_hint')}
              />
              <MemoryMetricRow
                label={t('settings.memory.fields.reranker_enabled.label')}
                value={
                  rerankerConfig.enabled
                    ? t(`settings.memory.options.reranker_backend.${rerankerConfig.backend}`)
                    : t('settings.memory.options.reranker_disabled')
                }
                hint={t('settings.memory.fields.reranker_local_managed_cache_path.description')}
              />
              <MemoryMetricRow
                label={t('settings.memory.fields.reranker_local_managed_cache_path.label')}
                value={MANAGED_RERANKER_MODELS_PATH}
              />
            </div>
          ) : (
            <div className="text-sm leading-7 text-muted-foreground">
              {t('settings.memory.sections.general.embeddingModelEmpty')}
            </div>
          )}
        </MemoryGroup>
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
        <MemorySwitchRow
          label={t('settings.memory.fields.runtime_replay_include_l0_only.label')}
          description={t('settings.memory.fields.runtime_replay_include_l0_only.description')}
          checked={draftConfig.memory.l0.runtime_replay_include_l0_only ?? false}
          disabled={!draftConfig.memory.l0.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l0.runtime_replay_include_l0_only = checked;
          })}
        />
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
        <div className="grid gap-6 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 lg:grid-cols-2">
          <NumberField
            label={t('settings.memory.fields.retention_days.label')}
            value={draftConfig.memory.l1.retention_days}
            min={1}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l1.retention_days = value;
            })}
          />
        </div>
      </MemoryGroup>

      <MemoryGroup>
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_t1_importance.label')}
          description={t('settings.memory.fields.enable_t1_importance.description')}
          checked={draftConfig.memory.l1.t1_importance_enabled ?? false}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l1.t1_importance_enabled = checked;
          })}
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
          label={t('settings.memory.fields.enable_l2_llm_extraction.label')}
          description={t('settings.memory.fields.enable_l2_llm_extraction.description')}
          checked={draftConfig.memory.l2.llm_extraction_enabled ?? false}
          disabled={!draftConfig.memory.l2.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l2.llm_extraction_enabled = checked;
          })}
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
  patchDraftConfig,
  updateMemoryToggle,
}: Pick<MemorySettingsSectionProps, 'draftConfig' | 'patchDraftConfig' | 'updateMemoryToggle'>) {
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
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l4_skill_extraction.label')}
          description={t('settings.memory.fields.enable_l4_skill_extraction.description')}
          checked={draftConfig.memory.l4.skill_extraction_enabled ?? false}
          disabled={!draftConfig.memory.l4.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l4.skill_extraction_enabled = checked;
          })}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}
