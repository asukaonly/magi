import React, { useMemo, useState } from 'react';
import { AlertTriangle, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { resolveProviderModels, type LLMConfig, type LLMProviderRegistry, type LLMScenario } from '@/api/modules/config';
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
}

const SCENARIOS: LLMScenario[] = ['context_decider', 'core', 'embedding'];

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
}) => {
  const { t } = useTranslation('onboarding');
  const enabledProviders = Object.entries(value.providers).filter(([, provider]) => provider.enabled);
  const isSettingsSurface = surface === 'settings';
  const inputClassName = cn(
    'h-11 w-full rounded-xl border border-border/65 bg-background px-3 text-sm shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
    isSettingsSurface && 'rounded-lg'
  );
  const providerBadgeClassName = cn(
    'rounded-full border border-border/60 bg-transparent px-2 py-0.5 text-xs text-muted-foreground',
    isSettingsSurface && 'border-0 bg-[hsl(var(--settings-shell-elevated)/0.58)] px-2.5 py-1 text-[11px] text-[hsl(var(--settings-nav-foreground))]'
  );
  const [expandedAdvanced, setExpandedAdvanced] = useState<Record<LLMScenario, boolean>>(() =>
    Object.fromEntries(SCENARIOS.map((scenario) => [scenario, showAdvancedByDefault])) as Record<LLMScenario, boolean>
  );

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

  return (
    <section
      data-testid="llm-model-selection-section"
      className={cn('space-y-3')}
    >
      {showSectionIntro ? (
        <div className="space-y-1">
          <h3 className="text-base font-semibold text-foreground">{t('llm.modelSelection.title')}</h3>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.modelSelection.desc')}</p>
        </div>
      ) : null}

      <div className="grid gap-3">
        {SCENARIOS.map((scenario, index) => {
          const selection = value.selections[scenario];
          const provider = value.providers[selection.provider_id];
          const isEmbeddingScenario = scenario === 'embedding';

          // For embedding scenario, use cross-provider model selection
          if (isEmbeddingScenario) {
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
              <article
                key={scenario}
                data-testid={`llm-scenario-${scenario}`}
                className={cn(
                  'rounded-xl border border-border/65 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
                  isSettingsSurface &&
                    cn(
                      'rounded-none border-x-0 border-b-0 px-0 pb-0 shadow-none',
                      index === 0
                        ? 'border-t-0 pt-0'
                        : 'border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6'
                    )
                )}
              >
                <div className="space-y-1 mb-4">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-sm font-semibold text-foreground">{t(`llm.scenarios.${scenario}.title`)}</h4>
                    {activeEmbeddingModel && (
                      <span className={providerBadgeClassName}>
                        {activeEmbeddingModel.providerName}
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-5 text-muted-foreground">{t(`llm.scenarios.${scenario}.desc`)}</p>
                </div>

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
                        // First change provider, then model
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

                {renderAdvancedSettings(scenario)}
              </article>
            );
          }

          // For non-embedding scenarios, filter out embedding models
          // Custom providers don't have embedding models in registry, so no need to filter
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
          <article
            key={scenario}
            data-testid={`llm-scenario-${scenario}`}
            className={cn(
              'rounded-xl border border-border/65 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
              isSettingsSurface &&
                cn(
                  'rounded-none border-x-0 border-b-0 px-0 pb-0 shadow-none',
                  index === 0
                    ? 'border-t-0 pt-0'
                    : 'border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6'
                )
            )}
          >
              <div className="space-y-1 mb-4">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="text-sm font-semibold text-foreground">{t(`llm.scenarios.${scenario}.title`)}</h4>
                  <span className={providerBadgeClassName}>
                    {provider?.display_name || selection.provider_id}
                  </span>
                </div>
                <p className="text-xs leading-5 text-muted-foreground">{t(`llm.scenarios.${scenario}.desc`)}</p>
              </div>

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
            </article>
          );
        })}
      </div>
    </section>
  );
};
