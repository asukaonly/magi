import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { resolveProviderModels, type CrossEncoderConfig, type EmbeddingConfig, type LLMConfig, type LLMProviderRegistry, type LLMScenario } from '@/api/modules/config';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

import { useManagedEmbeddingModels, useManagedRerankerModels } from './llm-model-download-hooks';
import { LLMChatScenarioPanel } from './LLMChatScenarioPanel';
import { LLMImageGenerationScenarioPanel } from './LLMImageGenerationScenarioPanel';
import { LLMLocalEmbeddingModelPanel } from './LLMLocalEmbeddingModelPanel';
import { LLMRemoteEmbeddingModelSelector } from './LLMRemoteEmbeddingModelSelector';
import { LLMRerankerModelPanel } from './LLMRerankerModelPanel';
import { LLMScenarioAdvancedSettings } from './LLMScenarioAdvancedSettings';
import { isPluginModelSelection, isProviderAllowedForScenario } from './llm-form-state';

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
  memorySummarizerUsesCore: boolean;
  memorySummarizerCanUseCore: boolean;
  onMemorySummarizerInheritanceChange: (checked: boolean) => void;
  embeddingConfig?: EmbeddingConfig;
  onEmbeddingConfigChange?: (updater: (draft: EmbeddingConfig) => void) => void;
  crossEncoderConfig?: CrossEncoderConfig;
  onCrossEncoderConfigChange?: (updater: (draft: CrossEncoderConfig) => void) => void;
}

const BASE_SCENARIOS: LLMScenario[] = ['core', 'embedding', 'image_generation'];
const ADVANCED_SCENARIOS: LLMScenario[] = ['core', 'auxiliary', 'memory_summarizer', 'embedding', 'image_generation'];
const ALL_SCENARIOS: LLMScenario[] = ['auxiliary', 'core', 'memory_summarizer', 'embedding', 'image_generation'];
type ModelTab = LLMScenario | 'reranker';
const ADVANCED_MODEL_TABS: ModelTab[] = ['core', 'auxiliary', 'memory_summarizer', 'embedding', 'image_generation', 'reranker'];
const BASE_MODEL_TABS: ModelTab[] = ['core', 'embedding', 'image_generation', 'reranker'];

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
  memorySummarizerUsesCore,
  memorySummarizerCanUseCore,
  onMemorySummarizerInheritanceChange,
  embeddingConfig,
  onEmbeddingConfigChange,
  crossEncoderConfig,
  onCrossEncoderConfigChange,
}) => {
  const { t } = useTranslation('onboarding');
  const { t: tApp } = useTranslation('app');
  const enabledProviders = Object.entries(value.providers).filter(([, provider]) => provider.enabled);
  const enabledChatProviders = enabledProviders.filter(([, provider]) => provider.services?.chat?.enabled);
  const enabledEmbeddingProviders = enabledProviders.filter(([, provider]) => provider.services?.embedding?.enabled);
  const enabledImageGenerationProviders = enabledProviders.filter(
    ([, provider]) => provider.services?.image_generation?.enabled
  );
  const isSettingsSurface = surface === 'settings';
  const showMemorySummarizer = !quickMode;
  const inputClassName = cn(
    'h-11 w-full rounded-xl border border-border/65 bg-background px-3 text-sm shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
    isSettingsSurface && 'rounded-lg'
  );
  const scenarios = showMemorySummarizer ? ADVANCED_SCENARIOS : BASE_SCENARIOS;
  const modelTabs = showMemorySummarizer ? ADVANCED_MODEL_TABS : BASE_MODEL_TABS;
  const [expandedAdvanced, setExpandedAdvanced] = useState<Record<LLMScenario, boolean>>(() =>
    Object.fromEntries(ALL_SCENARIOS.map((scenario) => [scenario, showAdvancedByDefault])) as Record<LLMScenario, boolean>
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
    for (const [providerId, provider] of enabledEmbeddingProviders) {
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
  }, [enabledEmbeddingProviders, registry.providers]);

  // Collect all image generation models from all enabled providers
  const allImageGenerationModels = useMemo(() => {
    const models: Array<{
      providerId: string;
      providerName: string;
      modelId: string;
      modelLabel: string;
    }> = [];
    for (const [providerId, provider] of enabledImageGenerationProviders) {
      const imageModels = resolveProviderModels(registry, providerId, provider).image_generation_models;
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
  }, [enabledImageGenerationProviders, registry.providers]);

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

  const hasPluginSelection = Object.values(value.selections).some(
    (selection) => isPluginModelSelection(value, selection.provider_id)
  );
  if (enabledProviders.length === 0 && !registry.plugin_providers?.length && !hasPluginSelection) {
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
      disabled={scenario === 'memory_summarizer' && memorySummarizerUsesCore}
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
          <LLMRemoteEmbeddingModelSelector
            scenario={scenario}
            selection={selection}
            embeddingModels={allEmbeddingModels}
            inputClassName={inputClassName}
            isSettingsSurface={isSettingsSurface}
            onScenarioProviderChange={onScenarioProviderChange}
            onScenarioModelChange={onScenarioModelChange}
            onScenarioEmbeddingDimensionChange={onScenarioEmbeddingDimensionChange}
          />
        )}

        {embeddingConfig?.mode !== 'off' ? renderAdvancedSettings(scenario) : null}
      </>
    );
  };

  const renderChatScenarioContent = (scenario: LLMScenario) => {
    const selection = value.selections[scenario];
    if (!selection) return null;
    const scenarioProviders = enabledChatProviders.filter(([, provider]) =>
      isProviderAllowedForScenario(registry, provider, scenario)
    );
    return (
      <LLMChatScenarioPanel
        scenario={scenario}
        selection={selection}
        provider={value.providers[selection.provider_id]}
        enabledProviders={scenarioProviders}
        registry={registry}
        quickMode={quickMode}
        inputClassName={inputClassName}
        isSettingsSurface={isSettingsSurface}
        disabled={scenario === 'memory_summarizer' && memorySummarizerUsesCore}
        advancedSettings={renderAdvancedSettings(scenario)}
        onScenarioProviderChange={onScenarioProviderChange}
        onScenarioModelChange={onScenarioModelChange}
      />
    );
  };

  const renderMemorySummarizerScenarioContent = () => {
    const selection = value.selections.memory_summarizer;
    if (!selection) return null;

    return (
      <div className="space-y-3">
        <label className="flex items-start gap-3 rounded-lg border border-border/65 bg-muted/20 px-4 py-3">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4 rounded border-border text-primary focus:ring-primary/60"
            checked={memorySummarizerUsesCore}
            disabled={!memorySummarizerCanUseCore}
            onChange={(event) => onMemorySummarizerInheritanceChange(event.target.checked)}
            aria-label={t('llm.scenarios.memory_summarizer.inheritLabel')}
          />
          <span className="space-y-1">
            <span className="block text-sm font-medium text-foreground">
              {t('llm.scenarios.memory_summarizer.inheritLabel')}
            </span>
            <span className="block text-xs leading-5 text-muted-foreground">
              {t(
                memorySummarizerCanUseCore
                  ? 'llm.scenarios.memory_summarizer.inheritHelp'
                  : 'llm.scenarios.memory_summarizer.inheritUnavailableHelp'
              )}
            </span>
          </span>
        </label>

        <div className={cn(memorySummarizerUsesCore && 'opacity-60')}>
          {renderChatScenarioContent('memory_summarizer')}
        </div>
      </div>
    );
  };

  const renderImageGenerationScenarioContent = (scenario: LLMScenario) => {
    const selection = value.selections[scenario];
    if (!selection) return null;

    return (
      <LLMImageGenerationScenarioPanel
        scenario={scenario}
        selection={selection}
        enabledProviders={enabledImageGenerationProviders}
        imageGenerationModels={allImageGenerationModels}
        quickMode={quickMode}
        inputClassName={inputClassName}
        onScenarioProviderChange={onScenarioProviderChange}
        onScenarioModelChange={onScenarioModelChange}
      />
    );
  };

  const renderScenarioContent = (scenario: LLMScenario) => {
    if (scenario === 'embedding') return renderEmbeddingScenarioContent(scenario);
    if (scenario === 'image_generation') return renderImageGenerationScenarioContent(scenario);
    if (scenario === 'memory_summarizer') return renderMemorySummarizerScenarioContent();
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
    ? modelTabs
    : scenarios;

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

      <Tabs defaultValue="core">
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
