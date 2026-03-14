import React, { useMemo } from 'react';
import { AlertTriangle, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import type { LLMConfig, LLMProviderRegistry, LLMScenario } from '@/api/modules/config';
import { cn } from '@/lib/utils';

interface LLMModelSelectionSectionProps {
  registry: LLMProviderRegistry;
  value: LLMConfig;
  quickMode?: boolean;
  surface?: 'onboarding' | 'settings';
  showSectionIntro?: boolean;
  onScenarioProviderChange: (scenario: LLMScenario, providerId: string) => void;
  onScenarioModelChange: (scenario: LLMScenario, model: string) => void;
}

const SCENARIOS: LLMScenario[] = ['context_decider', 'core', 'embedding'];

export const LLMModelSelectionSection: React.FC<LLMModelSelectionSectionProps> = ({
  registry,
  value,
  quickMode = false,
  surface = 'onboarding',
  showSectionIntro = true,
  onScenarioProviderChange,
  onScenarioModelChange,
}) => {
  const { t } = useTranslation('onboarding');
  const enabledProviders = Object.entries(value.providers).filter(([, provider]) => provider.enabled);
  const isSettingsSurface = surface === 'settings';
  const inputClassName = cn(
    'h-11 w-full rounded-xl border border-border/65 bg-background px-3 text-sm shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
    isSettingsSurface && 'rounded-lg'
  );

  // Collect all embedding models from all enabled providers
  const allEmbeddingModels = useMemo(() => {
    const models: Array<{ providerId: string; providerName: string; modelId: string; modelLabel: string }> = [];
    for (const [providerId, provider] of enabledProviders) {
      const isCustomProvider = provider.provider_type === 'custom';
      const providerMeta = isCustomProvider
        ? undefined
        : registry.providers.find((item) => item.id === provider.provider_type);

      const providerModels = isCustomProvider
        ? [] // Custom providers don't have embedding models in registry
        : providerMeta?.models || [];

      for (const model of providerModels) {
        if (model.capabilities?.embedding) {
          models.push({
            providerId,
            providerName: provider.display_name || providerMeta?.display_name || providerId,
            modelId: model.id,
            modelLabel: model.label || model.id,
          });
        }
      }
    }
    return models;
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
        <div className="rounded-xl border border-border/65 p-4 text-sm text-muted-foreground">
          {t('llm.modelSelection.empty')}
        </div>
      </section>
    );
  }

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
        {SCENARIOS.map((scenario) => {
          const selection = value.selections[scenario];
          const provider = value.providers[selection.provider_id];
          const isCustomProvider = provider?.provider_type === 'custom';
          const isEmbeddingScenario = scenario === 'embedding';

          // For embedding scenario, use cross-provider model selection
          if (isEmbeddingScenario) {
            const currentEmbeddingModel = allEmbeddingModels.find(
              (m) => m.providerId === selection.provider_id && m.modelId === selection.model
            );

            return (
              <article
                key={scenario}
                data-testid={`llm-scenario-${scenario}`}
                className="rounded-xl border border-border/65 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
              >
                <div className="space-y-1 mb-4">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-sm font-semibold text-foreground">{t(`llm.scenarios.${scenario}.title`)}</h4>
                    {currentEmbeddingModel && (
                      <span className="rounded-full border border-border/60 bg-transparent px-2 py-0.5 text-xs text-muted-foreground">
                        {currentEmbeddingModel.providerName}
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
                      options={allEmbeddingModels.map((m) => ({
                        label: `${m.modelLabel} (${m.providerName})`,
                        value: `${m.providerId}::${m.modelId}`,
                      }))}
                      onChange={(nextValue) => {
                        const [providerId, modelId] = nextValue.split('::');
                        // First change provider, then model
                        onScenarioProviderChange(scenario, providerId);
                        onScenarioModelChange(scenario, modelId);
                      }}
                    />
                  </label>
                ) : (
                  <div className="flex items-start gap-2 rounded-lg border border-info/40 bg-info/5 px-3 py-2.5 text-sm text-info-foreground">
                    <Info className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{t('llm.modelSelection.noEmbeddingModels')}</span>
                  </div>
                )}
              </article>
            );
          }

          // For non-embedding scenarios, filter out embedding models
          // Custom providers don't have embedding models in registry, so no need to filter
          const models = isCustomProvider
            ? (provider?.custom_models || []).map((model) => ({ id: model, label: model }))
            : (registry.providers.find((item) => item.id === provider?.provider_type)?.models || []).filter(
                (model) => !model.capabilities?.embedding
              );

          return (
            <article
              key={scenario}
              data-testid={`llm-scenario-${scenario}`}
              className="rounded-xl border border-border/65 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
            >
              <div className="space-y-1 mb-4">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="text-sm font-semibold text-foreground">{t(`llm.scenarios.${scenario}.title`)}</h4>
                  <span className="rounded-full border border-border/60 bg-transparent px-2 py-0.5 text-xs text-muted-foreground">
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
                      options={models.map((model) => ({
                        label: model.label || model.id,
                        value: model.id,
                      }))}
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

              {scenario === 'core' && !selection.capabilities.vision ? (
                <div className="flex items-start gap-2 rounded-lg border border-amber-300/35 bg-transparent px-3 py-2 text-xs text-amber-800 dark:text-amber-200 mt-3">
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
