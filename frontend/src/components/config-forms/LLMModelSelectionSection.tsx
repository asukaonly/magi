import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

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

const SCENARIOS: LLMScenario[] = ['context_decider', 'core'];

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
    'h-11 w-full rounded-2xl border border-input/80 bg-background/90 px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
    isSettingsSurface && 'rounded-lg border-border/60 bg-background'
  );

  if (enabledProviders.length === 0) {
    return (
      <section
        data-testid="llm-model-selection-section"
        className={cn('space-y-4 border-t border-border/50 pt-6', isSettingsSurface && 'space-y-3 border-t-0 pt-0')}
      >
        {showSectionIntro ? (
          <div className="space-y-1">
            <h3 className="text-lg font-semibold text-foreground">{t('llm.modelSelection.title')}</h3>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.modelSelection.desc')}</p>
          </div>
        ) : null}
        <div className={cn('rounded-[24px] border border-border/60 bg-muted/35 p-5 text-sm text-muted-foreground', isSettingsSurface && 'rounded-xl bg-muted/20 p-4')}>
          {t('llm.modelSelection.empty')}
        </div>
      </section>
    );
  }

  return (
    <section
      data-testid="llm-model-selection-section"
      className={cn('space-y-4 border-t border-border/50 pt-6', isSettingsSurface && 'space-y-3 border-t-0 pt-0')}
    >
      {showSectionIntro ? (
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-foreground">{t('llm.modelSelection.title')}</h3>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.modelSelection.desc')}</p>
        </div>
      ) : null}

      <div className={cn('grid gap-4 xl:grid-cols-2', isSettingsSurface && 'gap-3 xl:grid-cols-1')}>
        {SCENARIOS.map((scenario) => {
          const selection = value.selections[scenario];
          const provider = value.providers[selection.provider_id];
          const isCustomProvider = provider?.provider_type === 'custom';
          const models = isCustomProvider
            ? (provider?.custom_models || []).map((model) => ({ id: model, label: model }))
            : registry.providers.find((item) => item.id === provider?.provider_type)?.models || [];

          return (
            <article
              key={scenario}
              data-testid={`llm-scenario-${scenario}`}
              className={cn(
                'space-y-4 rounded-[24px] border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)/0.98),hsl(var(--muted)/0.9))] p-5 shadow-[0_16px_34px_-28px_hsl(var(--foreground)/0.14)] dark:bg-[linear-gradient(180deg,hsl(var(--card)/0.98),hsl(var(--background)/0.92))] dark:shadow-[0_20px_36px_-28px_rgba(0,0,0,0.62)]',
                isSettingsSurface && 'rounded-xl border-border/55 bg-muted/18 p-4 shadow-none dark:bg-muted/10'
              )}
            >
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-3">
                  <h4 className={cn('text-base font-semibold text-foreground', isSettingsSurface && 'text-sm')}>{t(`llm.scenarios.${scenario}.title`)}</h4>
                  <span className={cn('rounded-full border border-border/60 bg-background/80 px-2.5 py-1 text-xs text-muted-foreground', isSettingsSurface && 'border-0 bg-muted px-2 py-0.5')}>
                    {provider?.display_name || selection.provider_id}
                  </span>
                </div>
                <p className={cn('text-sm text-muted-foreground', isSettingsSurface && 'text-xs leading-5')}>{t(`llm.scenarios.${scenario}.desc`)}</p>
              </div>

              <div className={cn('grid gap-4', quickMode ? 'lg:grid-cols-2' : 'md:grid-cols-2')}>
                <label className="space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.provider')}</span>
                  <select
                    aria-label={t('llm.fields.provider')}
                    className={inputClassName}
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
                      className={inputClassName}
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
                      className={inputClassName}
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
                      className={cn('rounded-full border border-primary/20 bg-background/85 px-2.5 py-1 text-xs text-primary', isSettingsSurface && 'border-0 bg-muted text-muted-foreground')}
                    >
                      {t(`llm.capabilities.${capability === 'image_output' ? 'imageOutput' : capability}`)}
                    </span>
                  ))}
              </div>

              {scenario === 'core' && !selection.capabilities.vision ? (
                <div className={cn('flex items-start gap-2 rounded-xl border border-amber-400/45 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200', isSettingsSurface && 'border-amber-300/35 bg-amber-500/8 text-xs')}>
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
