import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, AlertTriangle, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { resolveProviderModels, type CrossEncoderConfig, type EmbeddingConfig, type LLMConfig, type LLMProviderRegistry, type LLMScenario } from '@/api/modules/config';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

import { useManagedEmbeddingModels, useManagedRerankerModels } from './llm-model-download-hooks';
import { LLMLocalEmbeddingModelPanel } from './LLMLocalEmbeddingModelPanel';
import { LLMRerankerModelPanel } from './LLMRerankerModelPanel';
import { LLMScenarioAdvancedSettings } from './LLMScenarioAdvancedSettings';

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

const SCENARIOS: LLMScenario[] = ['context_decider', 'core', 'embedding', 'image_generation'];
type ModelTab = LLMScenario | 'reranker';
const MODEL_TABS: ModelTab[] = ['context_decider', 'core', 'embedding', 'image_generation', 'reranker'];

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
  const {
    presetModels,
    downloadingModelId,
    downloadProgress,
    downloadError,
    handleDownloadModel,
    handleDeleteModel,
    handlePickDirectory,
  } = useManagedEmbeddingModels({
    enabled: isLocalEmbeddingMode,
    modelDirPath: embeddingConfig?.local.model_dir_path,
    downloadFailedMessage: tApp('settings.memory.fields.embedding_local_download.downloadFailed'),
    onEmbeddingConfigChange,
  });
  const {
    rerankerModels,
    rerankerDownloadingId,
    rerankerDownloadProgress,
    rerankerDownloadError,
    handleRerankerDownload,
    handleRerankerDelete,
  } = useManagedRerankerModels({
    enabled: Boolean(crossEncoderConfig),
    downloadFailedMessage: tApp('settings.memory.fields.reranker_download.downloadFailed'),
  });

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

  // Collect all image generation models from all enabled providers
  const allImageGenerationModels = useMemo(() => {
    const models: Array<{
      providerId: string;
      providerName: string;
      modelId: string;
      modelLabel: string;
    }> = [];
    for (const [providerId, provider] of enabledProviders) {
      const providerMeta = registry.providers.find((p) => p.id === providerId);
      const imageModels = providerMeta?.image_generation_models ?? [];
      for (const model of imageModels) {
        models.push({
          providerId,
          providerName: provider.display_name || providerId,
          modelId: model.id,
          modelLabel: model.label || model.id,
        });
      }
    }
    return models.sort((left, right) =>
      compareOptionLabels(
        { label: `${left.modelLabel} (${left.providerName})`, value: `${left.providerId}::${left.modelId}` },
        { label: `${right.modelLabel} (${right.providerName})`, value: `${right.providerId}::${right.modelId}` }
      )
    );
  }, [enabledProviders, registry.providers]);

  // Auto-correct: if mode is 'remote' but no remote embedding models are available, switch to 'off'
  useEffect(() => {
    if (
      embeddingConfig?.mode === 'remote' &&
      allEmbeddingModels.length === 0 &&
      onEmbeddingConfigChange
    ) {
      onEmbeddingConfigChange((emb) => {
        emb.mode = 'off';
      });
    }
  }, [embeddingConfig?.mode, allEmbeddingModels.length, onEmbeddingConfigChange]);

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

  const renderAdvancedSettings = (scenario: LLMScenario) => (
    <LLMScenarioAdvancedSettings
      scenario={scenario}
      concurrencyState={scenarioConcurrency[scenario]}
      expanded={expandedAdvanced[scenario]}
      isSettingsSurface={isSettingsSurface}
      inputClassName={inputClassName}
      onToggle={() =>
        setExpandedAdvanced((current) => ({
          ...current,
          [scenario]: !current[scenario],
        }))
      }
      onMaxConcurrencyChange={onScenarioMaxConcurrencyChange}
    />
  );

  const renderEmbeddingScenarioContent = (scenario: LLMScenario) => {
    const selection = value.selections[scenario];
    if (!selection) return null;
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
          <LLMLocalEmbeddingModelPanel
            embeddingConfig={embeddingConfig}
            onEmbeddingConfigChange={onEmbeddingConfigChange}
            inputClassName={inputClassName}
            presetModels={presetModels}
            downloadingModelId={downloadingModelId}
            downloadProgress={downloadProgress}
            downloadError={downloadError}
            onDownloadModel={handleDownloadModel}
            onDeleteModel={handleDeleteModel}
            onPickDirectory={handlePickDirectory}
          />
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
    if (!selection) return null;
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

  const renderImageGenerationScenarioContent = (scenario: LLMScenario) => {
    const selection = value.selections[scenario];
    if (!selection) return null;

    return (
      <>
        <div className={cn('grid gap-3', quickMode ? 'lg:grid-cols-2' : 'md:grid-cols-2')}>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('llm.fields.provider')}</span>
            <SelectField
              className="w-full"
              triggerClassName={inputClassName}
              value={selection?.provider_id || ''}
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
            {(() => {
              const providerImageModels = allImageGenerationModels.filter(
                (m) => m.providerId === (selection?.provider_id || '')
              );
              if (providerImageModels.length > 0) {
                return (
                  <SelectField
                    className="w-full"
                    triggerClassName={inputClassName}
                    value={selection?.model || ''}
                    allowEmpty={false}
                    searchable
                    searchThreshold={10}
                    searchPlaceholder={t('llm.modelSelection.searchPlaceholder')}
                    noResultsText={t('llm.modelSelection.noSearchResults')}
                    options={providerImageModels.map((m) => ({
                      label: m.modelLabel,
                      value: m.modelId,
                    }))}
                    onChange={(nextValue) => onScenarioModelChange(scenario, nextValue)}
                  />
                );
              }
              return (
                <input
                  aria-label={t('llm.fields.model')}
                  className={inputClassName}
                  value={selection?.model || ''}
                  placeholder={t('llm.imageGenerationModelPlaceholder')}
                  onChange={(event) => onScenarioModelChange(scenario, event.target.value)}
                />
              );
            })()}
          </label>
        </div>

        {(!selection?.provider_id || !selection?.model) ? (
          <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900/50 dark:bg-amber-950/30">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <p className="text-xs leading-5 text-amber-800 dark:text-amber-300">{t('llm.scenarios.image_generation.notConfiguredHint')}</p>
          </div>
        ) : null}
      </>
    );
  };

  const renderScenarioContent = (scenario: LLMScenario) => {
    if (scenario === 'embedding') return renderEmbeddingScenarioContent(scenario);
    if (scenario === 'image_generation') return renderImageGenerationScenarioContent(scenario);
    return renderChatScenarioContent(scenario);
  };

  const renderTabContent = (tab: ModelTab) => {
    if (tab === 'reranker') {
      return (
        <LLMRerankerModelPanel
          crossEncoderConfig={crossEncoderConfig}
          onCrossEncoderConfigChange={onCrossEncoderConfigChange}
          inputClassName={inputClassName}
          rerankerModels={rerankerModels}
          rerankerDownloadingId={rerankerDownloadingId}
          rerankerDownloadProgress={rerankerDownloadProgress}
          rerankerDownloadError={rerankerDownloadError}
          onRerankerDownload={handleRerankerDownload}
          onRerankerDelete={handleRerankerDelete}
        />
      );
    }
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
            <TabsTrigger key={tab} value={tab} className="gap-1">
              {t(`llm.scenarios.${tab}.title`)}
              {tab === 'embedding' && embeddingConfig?.mode === 'off' && (
                <AlertCircle className="h-3.5 w-3.5 text-destructive" />
              )}
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
