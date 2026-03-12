import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { LLMConfig, LLMProviderRegistry, LLMScenario } from '@/api/modules/config';
import { cn } from '@/lib/utils';

interface LLMModelSelectionSectionProps {
  registry: LLMProviderRegistry;
  value: LLMConfig;
  quickMode?: boolean;
  onScenarioProviderChange: (scenario: LLMScenario, providerId: string) => void;
  onScenarioModelChange: (scenario: LLMScenario, model: string) => void;
}

const SCENARIOS: LLMScenario[] = ['context_decider', 'core'];

export const LLMModelSelectionSection: React.FC<LLMModelSelectionSectionProps> = ({
  registry,
  value,
  quickMode = false,
  onScenarioProviderChange,
  onScenarioModelChange,
}) => {
  const { t } = useTranslation('onboarding');
  const enabledProviders = Object.entries(value.providers).filter(([, provider]) => provider.enabled);

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h3 className="text-lg font-semibold text-foreground">{t('llm.modelSelection.title')}</h3>
        <p className="text-sm text-muted-foreground">{t('llm.modelSelection.desc')}</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {SCENARIOS.map((scenario) => {
          const selection = value.selections[scenario];
          const provider = value.providers[selection.provider_id];
          const isCustomProvider = provider?.provider_type === 'custom';
          const models = isCustomProvider
            ? []
            : registry.providers.find((item) => item.id === provider?.provider_type)?.models || [];

          return (
            <article
              key={scenario}
              data-testid={`llm-scenario-${scenario}`}
              className="space-y-4 rounded-2xl border border-border bg-card p-5 shadow-sm"
            >
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="text-base font-semibold text-foreground">{t(`llm.scenarios.${scenario}.title`)}</h4>
                  <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                    {provider?.display_name || selection.provider_id}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">{t(`llm.scenarios.${scenario}.desc`)}</p>
              </div>

              <div className={cn('grid gap-4', quickMode ? 'md:grid-cols-1' : 'md:grid-cols-2')}>
                <label className="space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.provider')}</span>
                  <select
                    aria-label={t('llm.fields.provider')}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                    value={selection.provider_id}
                    onChange={(event) => onScenarioProviderChange(scenario, event.target.value)}
                  >
                    {enabledProviders.map(([providerId, enabledProvider]) => (
                      <option key={providerId} value={providerId}>
                        {enabledProvider.display_name || providerId}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.model')}</span>
                  {models.length > 0 ? (
                    <select
                      aria-label={t('llm.fields.model')}
                      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                      value={selection.model}
                      onChange={(event) => onScenarioModelChange(scenario, event.target.value)}
                    >
                      {models.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.label || model.id}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      aria-label={t('llm.fields.model')}
                      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                      value={selection.model}
                      placeholder={t('llm.modelManualPlaceholder')}
                      onChange={(event) => onScenarioModelChange(scenario, event.target.value)}
                    />
                  )}
                </label>
              </div>

              <div className="flex flex-wrap gap-2">
                {Object.entries(selection.capabilities)
                  .filter(([, enabled]) => Boolean(enabled))
                  .map(([capability]) => (
                    <span
                      key={capability}
                      className="rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1 text-xs text-primary"
                    >
                      {t(`llm.capabilities.${capability === 'image_output' ? 'imageOutput' : capability}`)}
                    </span>
                  ))}
              </div>

              {scenario === 'core' && !selection.capabilities.vision ? (
                <div className="flex items-start gap-2 rounded-xl border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-900">
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
