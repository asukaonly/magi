import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, Download, FolderOpen, Info, Loader2, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { SelectField } from '@/components/config-forms/fields';
import { resolveProviderModels, type CrossEncoderConfig, type EmbeddingConfig, type LLMConfig, type LLMProviderRegistry, type LLMScenario } from '@/api/modules/config';
import type { LocalEmbeddingModelInfo } from '@/api/modules/local-embedding';
import { localEmbeddingApi } from '@/api/modules/local-embedding';
import type { LocalRerankerModelInfo } from '@/api/modules/local-reranker';
import { localRerankerApi } from '@/api/modules/local-reranker';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { pickDirectory } from '@/runtime/desktop';
import { cn } from '@/lib/utils';

interface LLMModelSelectionSectionProps {
  registry: LLMProviderRegistry;
  value: LLMConfig;
  quickMode?: boolean;
  surface?: 'onboarding' | 'settings';
  showSectionIntro?: boolean;
  showAdvancedByDefault?: boolean;
  scenarioConcurrency: Record<
    LLMScenario,
    {
      runtimeKey: string | null;
      effectiveMaxConcurrency: number | null;
      overrideMaxConcurrency: number | null;
      defaultMaxConcurrency: number | null;
      sharedScenarios: LLMScenario[];
    }
  >;
  onScenarioProviderChange: (scenario: LLMScenario, providerId: string) => void;
  onScenarioModelChange: (scenario: LLMScenario, model: string) => void;
  onScenarioEmbeddingDimensionChange: (
    scenario: LLMScenario,
    dimension: number | null,
    source?: 'model-sync' | 'manual'
  ) => void;
  onScenarioMaxConcurrencyChange: (scenario: LLMScenario, value: number | null) => void;
  embeddingConfig?: EmbeddingConfig;
  onEmbeddingConfigChange?: (updater: (draft: EmbeddingConfig) => void) => void;
  crossEncoderConfig?: CrossEncoderConfig;
  onCrossEncoderConfigChange?: (updater: (draft: CrossEncoderConfig) => void) => void;
}

const SCENARIOS: LLMScenario[] = ['context_decider', 'core', 'embedding'];
type ModelTab = LLMScenario | 'reranker';
const MODEL_TABS: ModelTab[] = ['context_decider', 'core', 'embedding', 'reranker'];

const compareOptionLabels = (left: { label: string; value: string }, right: { label: string; value: string }) => {
  const labelComparison = left.label.localeCompare(right.label, 'en', { sensitivity: 'base' });
  if (labelComparison !== 0) {
    return labelComparison;
  }
  return left.value.localeCompare(right.value, 'en', { sensitivity: 'base' });
};

export const LLMModelSelectionSection: React.FC<LLMModelSelectionSectionProps> = ({
  registry,
  value,
  quickMode = false,
  surface = 'onboarding',
  showSectionIntro = true,
  showAdvancedByDefault = false,
  scenarioConcurrency,
  onScenarioProviderChange,
  onScenarioModelChange,
  onScenarioEmbeddingDimensionChange,
  onScenarioMaxConcurrencyChange,
  embeddingConfig,
  onEmbeddingConfigChange,
  crossEncoderConfig,
  onCrossEncoderConfigChange,
}) => {
  const { t } = useTranslation('onboarding');
  const { t: tApp } = useTranslation('app');
  const enabledProviders = Object.entries(value.providers).filter(([, provider]) => provider.enabled);
  const isSettingsSurface = surface === 'settings';
  const inputClassName = cn(
    'h-11 w-full rounded-xl border border-border/65 bg-background px-3 text-sm shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
    isSettingsSurface && 'rounded-lg'
  );
  const [expandedAdvanced, setExpandedAdvanced] = useState<Record<LLMScenario, boolean>>(() =>
    Object.fromEntries(SCENARIOS.map((scenario) => [scenario, showAdvancedByDefault])) as Record<LLMScenario, boolean>
  );

  const isLocalEmbeddingMode = embeddingConfig?.mode === 'local';
  const [presetModels, setPresetModels] = useState<LocalEmbeddingModelInfo[]>([]);
  const [downloadingModelId, setDownloadingModelId] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const refreshPresetModels = useCallback(() => {
    localEmbeddingApi.listModels().then(setPresetModels).catch(() => {});
  }, []);

  useEffect(() => {
    if (isLocalEmbeddingMode) {
      refreshPresetModels();
    }
  }, [isLocalEmbeddingMode, refreshPresetModels]);

  // Poll download status while downloading
  useEffect(() => {
    if (!downloadingModelId) return;
    const interval = setInterval(async () => {
      try {
        const status = await localEmbeddingApi.getDownloadStatus(downloadingModelId);
        if (status.status === 'downloading') {
          setDownloadProgress(status.progress_pct ?? null);
        } else if (status.status === 'completed') {
          setDownloadingModelId(null);
          setDownloadProgress(null);
          refreshPresetModels();
        } else if (status.status === 'failed') {
          setDownloadingModelId(null);
          setDownloadProgress(null);
          setDownloadError(status.error ?? tApp('settings.memory.fields.embedding_local_download.downloadFailed'));
          toast.error(status.error ?? tApp('settings.memory.fields.embedding_local_download.downloadFailed'));
        }
      } catch {
        // Ignore polling errors
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [downloadingModelId, refreshPresetModels]);

  const handleDownloadModel = useCallback(async (modelId: string) => {
    setDownloadingModelId(modelId);
    setDownloadProgress(0);
    setDownloadError(null);
    try {
      await localEmbeddingApi.downloadModel(modelId);
    } catch {
      setDownloadingModelId(null);
      setDownloadProgress(null);
    }
  }, []);

  const handleDeleteModel = useCallback(async (modelId: string) => {
    try {
      await localEmbeddingApi.deleteModel(modelId);
      refreshPresetModels();
    } catch {
      // Ignore delete errors
    }
  }, [refreshPresetModels]);

  const handlePickDirectory = useCallback(async () => {
    const dir = await pickDirectory(embeddingConfig?.local.model_dir_path ?? undefined);
    if (dir && onEmbeddingConfigChange) {
      onEmbeddingConfigChange((emb) => {
        emb.local.model_dir_path = dir;
      });
    }
  }, [embeddingConfig?.local.model_dir_path, onEmbeddingConfigChange]);

  // ── Reranker (cross-encoder) model state ──
  const [rerankerModels, setRerankerModels] = useState<LocalRerankerModelInfo[]>([]);
  const [rerankerDownloadingId, setRerankerDownloadingId] = useState<string | null>(null);
  const [rerankerDownloadProgress, setRerankerDownloadProgress] = useState<number | null>(null);
  const [rerankerDownloadError, setRerankerDownloadError] = useState<string | null>(null);

  const refreshRerankerModels = useCallback(() => {
    localRerankerApi.listModels().then(setRerankerModels).catch(() => {});
  }, []);

  useEffect(() => {
    if (crossEncoderConfig) {
      refreshRerankerModels();
    }
  }, [crossEncoderConfig, refreshRerankerModels]);

  useEffect(() => {
    if (!rerankerDownloadingId) return;
    const interval = setInterval(async () => {
      try {
        const status = await localRerankerApi.getDownloadStatus(rerankerDownloadingId);
        if (status.status === 'downloading') {
          setRerankerDownloadProgress(status.progress_pct ?? null);
        } else if (status.status === 'completed') {
          setRerankerDownloadingId(null);
          setRerankerDownloadProgress(null);
          refreshRerankerModels();
        } else if (status.status === 'failed') {
          setRerankerDownloadingId(null);
          setRerankerDownloadProgress(null);
          setRerankerDownloadError(status.error ?? tApp('settings.memory.fields.reranker_download.downloadFailed'));
          toast.error(status.error ?? tApp('settings.memory.fields.reranker_download.downloadFailed'));
        }
      } catch {
        // Ignore polling errors
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [rerankerDownloadingId, refreshRerankerModels, tApp]);

  const handleRerankerDownload = useCallback(async (modelId: string) => {
    setRerankerDownloadingId(modelId);
    setRerankerDownloadProgress(0);
    setRerankerDownloadError(null);
    try {
      await localRerankerApi.downloadModel(modelId);
    } catch {
      setRerankerDownloadingId(null);
      setRerankerDownloadProgress(null);
    }
  }, []);

  const handleRerankerDelete = useCallback(async (modelId: string) => {
    try {
      await localRerankerApi.deleteModel(modelId);
      refreshRerankerModels();
    } catch {
      // Ignore delete errors
    }
  }, [refreshRerankerModels]);

  // Collect all embedding models from all enabled providers
  const allEmbeddingModels = useMemo(() => {
    const models: Array<{
      providerId: string;
      providerName: string;
      modelId: string;
      modelLabel: string;
      dimensions: number[];
    }> = [];
    for (const [providerId, provider] of enabledProviders) {
      const providerModels = resolveProviderModels(registry, providerId, provider).embedding_models.filter(
        (model) => !model.hidden
      );

      for (const model of providerModels) {
        models.push({
          providerId,
          providerName: provider.display_name || providerId,
          modelId: model.id,
          modelLabel: model.label || model.id,
          dimensions: model.dimensions || [],
        });
      }
    }
    return models.sort((left, right) =>
      compareOptionLabels(
        {
          label: `${left.modelLabel} (${left.providerName})`,
          value: `${left.providerId}::${left.modelId}`,
        },
        {
          label: `${right.modelLabel} (${right.providerName})`,
          value: `${right.providerId}::${right.modelId}`,
        }
      )
    );
  }, [enabledProviders, registry.providers]);

  if (enabledProviders.length === 0) {
    return (
      <section
        data-testid="llm-model-selection-section"
        className={cn('space-y-3', isSettingsSurface && 'space-y-3')}
      >
        {showSectionIntro ? (
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-foreground">{t('llm.modelSelection.title')}</h3>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.modelSelection.desc')}</p>
          </div>
        ) : null}
        <div className={cn(
          'rounded-xl border border-border/65 p-4 text-sm text-muted-foreground',
          isSettingsSurface && 'rounded-none border-0 px-0 pb-0 pt-0'
        )}>
          {t('llm.modelSelection.empty')}
        </div>
      </section>
    );
  }

  const renderAdvancedSettings = (scenario: LLMScenario) => {
    const concurrencyState = scenarioConcurrency[scenario];
    const sharedScenarioTitles = concurrencyState.sharedScenarios.map((sharedScenario) =>
      t(`llm.scenarios.${sharedScenario}.title`)
    );

    return (
      <div
        className={cn(
          'mt-3 space-y-3',
          isSettingsSurface ? 'pt-1' : 'border-t border-border/60 pt-3'
        )}
      >
        <button
          type="button"
          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          onClick={() =>
            setExpandedAdvanced((current) => ({
              ...current,
              [scenario]: !current[scenario],
            }))
          }
        >
          {expandedAdvanced[scenario] ? t('llm.hideAdvanced') : t('llm.showAdvanced')}
        </button>

        {expandedAdvanced[scenario] ? (
          <div className="space-y-2">
            <label className="space-y-2">
              <span className="text-sm font-medium">{t('llm.fields.maxConcurrency')}</span>
              <input
                aria-label={t('llm.fields.maxConcurrency')}
                className={inputClassName}
                type="number"
                min={1}
                step={1}
                value={
                  concurrencyState.effectiveMaxConcurrency !== null
                    ? String(concurrencyState.effectiveMaxConcurrency)
                    : ''
                }
                placeholder={t('llm.modelSelection.maxConcurrencyPlaceholder')}
                onChange={(event) => {
                  const nextValue = event.target.value.trim();
                  onScenarioMaxConcurrencyChange(
                    scenario,
                    nextValue ? Number(nextValue) : null
                  );
                }}
              />
            </label>
            <p className="text-xs leading-5 text-muted-foreground">
              {t('llm.modelSelection.maxConcurrencyHelp')}
            </p>
            {sharedScenarioTitles.length > 0 ? (
              <p className="text-xs leading-5 text-muted-foreground">
                {t('llm.modelSelection.sharedConcurrencyHint', {
                  scenarios: sharedScenarioTitles.join(', '),
                })}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  };

  const renderEmbeddingScenarioContent = (scenario: LLMScenario) => {
    const selection = value.selections[scenario];
    const currentEmbeddingModel = allEmbeddingModels.find(
      (m) => m.providerId === selection.provider_id && m.modelId === selection.model
    );
    const activeEmbeddingModel = currentEmbeddingModel || allEmbeddingModels[0];
    const availableDimensions = activeEmbeddingModel?.dimensions || [];
    const selectedDimension =
      availableDimensions.includes(selection.embedding_dimension || -1)
        ? selection.embedding_dimension
        : (availableDimensions[0] ?? null);

    return (
      <>
        {embeddingConfig && onEmbeddingConfigChange ? (
          <label className="space-y-2 mb-3">
            <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_mode.label')}</span>
            <SelectField
              className="w-full"
              triggerClassName={inputClassName}
              value={embeddingConfig.mode}
              allowEmpty={false}
              options={[
                { label: tApp('settings.options.off'), value: 'off' },
                ...(allEmbeddingModels.length > 0 ? [{ label: tApp('settings.options.remote'), value: 'remote' }] : []),
                { label: tApp('settings.options.local'), value: 'local' },
              ]}
              onChange={(val) => onEmbeddingConfigChange((emb) => {
                emb.mode = val as typeof emb.mode;
              })}
            />
          </label>
        ) : null}

        {embeddingConfig?.mode === 'off' ? (
          <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900/50 dark:bg-amber-950/30">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <p className="text-xs leading-5 text-amber-800 dark:text-amber-300">{t('llm.scenarios.embedding.offHint')}</p>
          </div>
        ) : isLocalEmbeddingMode && embeddingConfig && onEmbeddingConfigChange ? (
          <div className="space-y-3">
            <label className="space-y-2">
              <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_model_source.label')}</span>
              <SelectField
                className="w-full"
                triggerClassName={inputClassName}
                value={embeddingConfig.local.model_source}
                allowEmpty={false}
                options={[
                  { label: tApp('settings.memory.options.embedding_local_model_source.managed'), value: 'managed' },
                  { label: tApp('settings.memory.options.embedding_local_model_source.external'), value: 'external' },
                ]}
                onChange={(val) => onEmbeddingConfigChange((emb) => {
                  emb.local.model_source = val as typeof emb.local.model_source;
                })}
              />
            </label>

            {embeddingConfig.local.model_source === 'managed' ? (
              <>
                <label className="space-y-2">
                  <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_managed_model_id.label')}</span>
                  <SelectField
                    className="w-full"
                    triggerClassName={inputClassName}
                    value={embeddingConfig.local.managed_model_id ?? ''}
                    allowEmpty={false}
                    placeholder={tApp('settings.memory.fields.embedding_local_managed_model_id.placeholder')}
                    options={presetModels.map((m) => ({
                      label: `${m.label}${m.recommended ? ` (${tApp('settings.memory.fields.embedding_local_download.recommended')})` : ''} — ${m.dimension}d, ${m.size_mb}MB`,
                      value: m.id,
                    }))}
                    onChange={(val) => onEmbeddingConfigChange((emb) => {
                      emb.local.managed_model_id = val || null;
                    })}
                  />
                </label>

                {embeddingConfig.local.managed_model_id ? (() => {
                  const selectedModel = presetModels.find((m) => m.id === embeddingConfig.local.managed_model_id);
                  if (!selectedModel) return null;
                  const isDownloading = downloadingModelId === selectedModel.id;
                  return (
                    <>
                    <div className="flex items-center gap-2">
                      {selectedModel.downloaded ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDeleteModel(selectedModel.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          {tApp('settings.memory.fields.embedding_local_download.delete')}
                        </Button>
                      ) : isDownloading ? (
                        <Button type="button" variant="outline" size="sm" disabled>
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          {tApp('settings.memory.fields.embedding_local_download.downloading')}
                          {downloadProgress !== null ? ` ${Math.round(downloadProgress)}%` : ''}
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => handleDownloadModel(selectedModel.id)}
                        >
                          <Download className="h-3.5 w-3.5" />
                          {tApp('settings.memory.fields.embedding_local_download.download')}
                        </Button>
                      )}
                      {selectedModel.downloaded && (
                        <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                          <Check className="h-3.5 w-3.5" />
                          {tApp('settings.memory.fields.embedding_local_download.downloaded')}
                        </span>
                      )}
                    </div>
                    {downloadError && !isDownloading && !selectedModel.downloaded && (
                      <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                        {downloadError}
                      </p>
                    )}
                    </>
                  );
                })() : null}
              </>
            ) : (
              <div className="space-y-2">
                <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_model_dir_path.label')}</span>
                <div className="flex gap-2">
                  <input
                    aria-label={tApp('settings.memory.fields.embedding_local_model_dir_path.label')}
                    className={inputClassName}
                    value={embeddingConfig.local.model_dir_path ?? ''}
                    readOnly
                    placeholder={tApp('settings.memory.fields.embedding_local_model_dir_path.placeholder')}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="h-11 shrink-0"
                    onClick={handlePickDirectory}
                  >
                    <FolderOpen className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}

            <label className="space-y-2">
              <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_idle_timeout.label')}</span>
              <input
                aria-label={tApp('settings.memory.fields.embedding_local_idle_timeout.label')}
                className={inputClassName}
                type="number"
                min={1}
                step={1}
                value={String(Math.round(embeddingConfig.local.idle_timeout_seconds / 60))}
                onChange={(event) => {
                  const nextValue = event.target.value.trim();
                  onEmbeddingConfigChange((emb) => {
                    emb.local.idle_timeout_seconds = nextValue ? Number(nextValue) * 60 : 1800;
                  });
                }}
              />
            </label>

            <p className="text-xs leading-5 text-muted-foreground">
              {tApp('settings.memory.fields.embedding_local_managed_cache_path.description')}
            </p>
          </div>
        ) : (
          <>
            {allEmbeddingModels.length > 0 ? (
              <label className="space-y-2">
                <span className="text-sm font-medium">{t('llm.fields.model')}</span>
                <SelectField
                  className="w-full"
                  triggerClassName={inputClassName}
                  value={selection.provider_id && selection.model ? `${selection.provider_id}::${selection.model}` : ''}
                  allowEmpty={false}
                  placeholder={t('llm.modelSelection.selectEmbeddingModel')}
                  searchable
                  searchThreshold={10}
                  searchPlaceholder={t('llm.modelSelection.searchPlaceholder')}
                  noResultsText={t('llm.modelSelection.noSearchResults')}
                  options={allEmbeddingModels.map((m) => ({
                    label: `${m.modelLabel} (${m.providerName})`,
                    value: `${m.providerId}::${m.modelId}`,
                  }))}
                  onChange={(nextValue) => {
                    const [providerId, modelId] = nextValue.split('::');
                    onScenarioProviderChange(scenario, providerId);
                    onScenarioModelChange(scenario, modelId);
                    const matched = allEmbeddingModels.find(
                      (item) => item.providerId === providerId && item.modelId === modelId
                    );
                    onScenarioEmbeddingDimensionChange(
                      scenario,
                      matched?.dimensions?.[0] ?? null,
                      'model-sync'
                    );
                  }}
                />
              </label>
            ) : (
              <div
                className={cn(
                  'flex items-start gap-2 rounded-lg border border-info/40 bg-info/5 px-3 py-2.5 text-sm text-info-foreground',
                  isSettingsSurface && 'rounded-none border-x-0 border-b-0 border-t border-[hsl(var(--settings-subnav-border)/0.72)] bg-transparent px-0 pb-0 pt-4 text-muted-foreground'
                )}
              >
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{t('llm.modelSelection.noEmbeddingModels')}</span>
              </div>
            )}

            {allEmbeddingModels.length > 0 ? (
              <label className="space-y-2 mt-3">
                <span className="text-sm font-medium">{t('llm.fields.embeddingDimension')}</span>
                <SelectField
                  className="w-full"
                  triggerClassName={inputClassName}
                  value={selectedDimension ? String(selectedDimension) : ''}
                  allowEmpty={false}
                  placeholder={t('llm.modelSelection.selectEmbeddingDimension')}
                  options={availableDimensions.map((dimension) => ({
                    label: String(dimension),
                    value: String(dimension),
                  }))}
                  onChange={(nextValue) =>
                    onScenarioEmbeddingDimensionChange(
                      scenario,
                      nextValue ? Number(nextValue) : null,
                      'manual'
                    )
                  }
                />
              </label>
            ) : null}
          </>
        )}

        {embeddingConfig?.mode !== 'off' ? renderAdvancedSettings(scenario) : null}
      </>
    );
  };

  const renderChatScenarioContent = (scenario: LLMScenario) => {
    const selection = value.selections[scenario];
    const provider = value.providers[selection.provider_id];
    const models = provider
      ? resolveProviderModels(registry, selection.provider_id, provider).chat_models.filter((model) => !model.hidden)
      : [];
    const modelOptions = models
      .map((model) => ({
        label: model.label || model.id,
        value: model.id,
      }))
      .sort(compareOptionLabels);

    return (
      <>
        <div className={cn('grid gap-3', quickMode ? 'lg:grid-cols-2' : 'md:grid-cols-2')}>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('llm.fields.provider')}</span>
            <SelectField
              className="w-full"
              triggerClassName={inputClassName}
              value={selection.provider_id}
              allowEmpty={false}
              options={enabledProviders.map(([providerId, enabledProvider]) => ({
                label: enabledProvider.display_name || providerId,
                value: providerId,
              }))}
              onChange={(nextValue) => onScenarioProviderChange(scenario, nextValue)}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium">{t('llm.fields.model')}</span>
            {models.length > 0 ? (
              <SelectField
                className="w-full"
                triggerClassName={inputClassName}
                value={selection.model}
                allowEmpty={false}
                searchable
                searchThreshold={10}
                searchPlaceholder={t('llm.modelSelection.searchPlaceholder')}
                noResultsText={t('llm.modelSelection.noSearchResults')}
                options={modelOptions}
                onChange={(nextValue) => onScenarioModelChange(scenario, nextValue)}
              />
            ) : (
              <input
                aria-label={t('llm.fields.model')}
                className={inputClassName}
                value={selection.model}
                placeholder={t('llm.modelManualPlaceholder')}
                onChange={(event) => onScenarioModelChange(scenario, event.target.value)}
              />
            )}
          </label>
        </div>

        {renderAdvancedSettings(scenario)}

        {scenario === 'core' && !selection.capabilities.vision ? (
          <div
            role="alert"
            className={cn(
              'mt-3 flex items-start gap-2 rounded-lg border border-amber-300/45 bg-amber-50/80 px-3 py-2.5 text-xs text-amber-900 shadow-[0_1px_2px_rgba(120,53,15,0.06)] dark:border-amber-300/30 dark:bg-amber-500/10 dark:text-amber-100',
              isSettingsSurface && 'rounded-md border border-amber-300/40 bg-amber-50/72 px-3 py-2.5 text-amber-900 shadow-none dark:border-amber-300/25 dark:bg-amber-500/10 dark:text-amber-100'
            )}
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{t('llm.warnings.coreVisionMissing')}</span>
          </div>
        ) : null}
      </>
    );
  };

  const renderScenarioContent = (scenario: LLMScenario) => {
    return scenario === 'embedding'
      ? renderEmbeddingScenarioContent(scenario)
      : renderChatScenarioContent(scenario);
  };

  const renderRerankerContent = () => {
    if (!crossEncoderConfig || !onCrossEncoderConfigChange) {
      return (
        <p className="text-sm text-muted-foreground">
          {tApp('settings.memory.fields.reranker_not_available')}
        </p>
      );
    }

    return (
      <div className="space-y-3">
        <label className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium">{tApp('settings.memory.fields.reranker_enabled.label')}</span>
          <Switch
            checked={crossEncoderConfig.enabled}
            onCheckedChange={(checked) => onCrossEncoderConfigChange((ce) => {
              ce.enabled = checked;
            })}
          />
        </label>

        {crossEncoderConfig.enabled ? (
          <>
            <label className="space-y-2">
              <span className="text-sm font-medium">{tApp('settings.memory.fields.reranker_model.label')}</span>
          <SelectField
            className="w-full"
            triggerClassName={inputClassName}
            value={crossEncoderConfig.managed_model_id ?? ''}
            allowEmpty={false}
            placeholder={tApp('settings.memory.fields.reranker_model.placeholder')}
            options={rerankerModels.map((m) => ({
              label: `${m.label}${m.recommended ? ` (${tApp('settings.memory.fields.reranker_download.recommended')})` : ''} — ${m.size_mb}MB, ${m.languages.join('/')}`,
              value: m.id,
            }))}
            onChange={(val) => onCrossEncoderConfigChange((ce) => {
              ce.managed_model_id = val || null;
            })}
          />
        </label>

        {crossEncoderConfig.managed_model_id ? (() => {
          const selectedModel = rerankerModels.find((m) => m.id === crossEncoderConfig.managed_model_id);
          if (!selectedModel) return null;
          const isDownloading = rerankerDownloadingId === selectedModel.id;
          return (
            <>
              <div className="flex items-center gap-2">
                {selectedModel.downloaded ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => handleRerankerDelete(selectedModel.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {tApp('settings.memory.fields.reranker_download.delete')}
                  </Button>
                ) : isDownloading ? (
                  <Button type="button" variant="outline" size="sm" disabled>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {tApp('settings.memory.fields.reranker_download.downloading')}
                    {rerankerDownloadProgress !== null ? ` ${Math.round(rerankerDownloadProgress)}%` : ''}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => handleRerankerDownload(selectedModel.id)}
                  >
                    <Download className="h-3.5 w-3.5" />
                    {tApp('settings.memory.fields.reranker_download.download')}
                  </Button>
                )}
                {selectedModel.downloaded && (
                  <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                    <Check className="h-3.5 w-3.5" />
                    {tApp('settings.memory.fields.reranker_download.downloaded')}
                  </span>
                )}
              </div>
              {rerankerDownloadError && !isDownloading && !selectedModel.downloaded && (
                <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  {rerankerDownloadError}
                </p>
              )}
              {selectedModel.description && (
                <p className="text-xs leading-5 text-muted-foreground">{selectedModel.description}</p>
              )}
            </>
          );
        })() : null}
          </>
        ) : null}
      </div>
    );
  };

  const renderTabContent = (tab: ModelTab) => {
    if (tab === 'reranker') return renderRerankerContent();
    return renderScenarioContent(tab);
  };

  // Determine visible tabs: include reranker only when cross-encoder config is provided
  const visibleTabs: ModelTab[] = crossEncoderConfig
    ? MODEL_TABS
    : SCENARIOS;

  return (
    <section
      data-testid="llm-model-selection-section"
      className="space-y-3"
    >
      {showSectionIntro ? (
        <div className="space-y-1">
          <h3 className="text-base font-semibold text-foreground">{t('llm.modelSelection.title')}</h3>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.modelSelection.desc')}</p>
        </div>
      ) : null}

      <Tabs defaultValue="context_decider">
        <TabsList className="w-full justify-start">
          {visibleTabs.map((tab) => (
            <TabsTrigger key={tab} value={tab}>
              {t(`llm.scenarios.${tab}.title`)}
            </TabsTrigger>
          ))}
        </TabsList>

        {visibleTabs.map((tab) => (
          <TabsContent
            key={tab}
            value={tab}
            data-testid={`llm-scenario-${tab}`}
            className="mt-4 space-y-3 data-[state=inactive]:hidden"
            forceMount
          >
            <p className="text-xs leading-5 text-muted-foreground">{t(`llm.scenarios.${tab}.desc`)}</p>
            {renderTabContent(tab)}
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
};
