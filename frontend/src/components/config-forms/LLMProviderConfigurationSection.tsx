import React from 'react';
import { Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { LLMConfig, LLMProviderConfig, LLMProviderRegistry, LLMScenario } from '@/api/modules/config';
import { cn } from '@/lib/utils';

interface LLMProviderConfigurationSectionProps {
  registry: LLMProviderRegistry;
  value: LLMConfig;
  activeProviderId: string;
  quickMode?: boolean;
  scenarioReferences: Record<string, LLMScenario[]>;
  onActiveProviderChange: (providerId: string) => void;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onAddCustomProvider: () => void;
}

const badgeClassName =
  'inline-flex rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground';

export const LLMProviderConfigurationSection: React.FC<LLMProviderConfigurationSectionProps> = ({
  registry,
  value,
  activeProviderId,
  quickMode = false,
  scenarioReferences,
  onActiveProviderChange,
  onProviderChange,
  onAddCustomProvider,
}) => {
  const { t } = useTranslation('onboarding');
  const customProviderIds = Object.entries(value.providers)
    .filter(([, provider]) => provider.provider_type === 'custom')
    .map(([providerId]) => providerId);
  const providerOrder = [
    ...registry.providers.map((provider) => provider.id),
    ...customProviderIds.filter((providerId) => !registry.providers.some((provider) => provider.id === providerId)),
  ];
  const activeProvider = value.providers[activeProviderId] || value.providers[providerOrder[0]];
  const activeProviderMeta =
    activeProvider?.provider_type === 'custom'
      ? undefined
      : registry.providers.find((provider) => provider.id === activeProvider?.provider_type);
  const activeReferences = scenarioReferences[activeProviderId] || [];

  return (
    <section className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-foreground">{t('llm.providerConfiguration.title')}</h3>
          <p className="text-sm text-muted-foreground">{t('llm.providerConfiguration.desc')}</p>
        </div>
        <button
          type="button"
          onClick={onAddCustomProvider}
          className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium text-foreground transition hover:border-primary/40 hover:bg-primary/5"
        >
          <Plus className="h-4 w-4" />
          <span>{t('llm.actions.addCustomProvider')}</span>
        </button>
      </div>

      <div className={cn('grid gap-4', quickMode ? 'xl:grid-cols-1' : 'xl:grid-cols-[320px_minmax(0,1fr)]')}>
        <div className="space-y-3">
          {providerOrder.map((providerId) => {
            const provider = value.providers[providerId];
            if (!provider) {
              return null;
            }
            const providerMeta =
              provider.provider_type === 'custom'
                ? undefined
                : registry.providers.find((item) => item.id === provider.provider_type);
            const modelLabels =
              providerMeta?.models?.map((model) => model.label || model.id) || [];

            return (
              <button
                key={providerId}
                type="button"
                onClick={() => onActiveProviderChange(providerId)}
                className={cn(
                  'w-full rounded-2xl border p-4 text-left transition',
                  providerId === activeProviderId
                    ? 'border-primary bg-primary/5 shadow-sm'
                    : 'border-border bg-card hover:border-primary/30'
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-foreground">
                      {provider.display_name || providerMeta?.display_name || providerId}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {providerMeta?.description || t('llm.providerConfiguration.customProviderHint')}
                    </p>
                  </div>
                  <span className={badgeClassName}>
                    {provider.enabled ? t('llm.badges.enabled') : t('llm.badges.disabled')}
                  </span>
                </div>

                {modelLabels.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {modelLabels.map((label) => (
                      <span key={label} className={badgeClassName}>
                        {label}
                      </span>
                    ))}
                  </div>
                ) : null}
              </button>
            );
          })}
        </div>

        {activeProvider ? (
          <div className="space-y-4 rounded-2xl border border-border bg-card p-5 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <h4 className="text-base font-semibold text-foreground">
                  {activeProvider.display_name || activeProviderMeta?.display_name || activeProviderId}
                </h4>
                <p className="text-sm text-muted-foreground">
                  {activeProviderMeta?.description || t('llm.providerConfiguration.customProviderHint')}
                </p>
              </div>

              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={activeProvider.enabled}
                  disabled={activeReferences.length > 0}
                  onChange={(event) =>
                    onProviderChange(activeProviderId, (provider) => {
                      provider.enabled = event.target.checked;
                    })
                  }
                />
                <span>{t('llm.fields.enabled')}</span>
              </label>
            </div>

            {activeReferences.length > 0 ? (
              <div className="rounded-xl border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                {t('llm.providerConfiguration.referencedBy')}: {activeReferences.map((scenario) => t(`llm.scenarios.${scenario}.title`)).join(' / ')}
              </div>
            ) : null}

            {activeProvider.provider_type === 'custom' ? (
              <>
                <label className="space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
                  <input
                    aria-label={t('llm.fields.displayName')}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                    value={activeProvider.display_name || ''}
                    onChange={(event) =>
                      onProviderChange(activeProviderId, (provider) => {
                        provider.display_name = event.target.value;
                      })
                    }
                  />
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.apiFormat')}</span>
                  <select
                    aria-label={t('llm.fields.apiFormat')}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                    value={activeProvider.api_format || 'openai'}
                    onChange={(event) =>
                      onProviderChange(activeProviderId, (provider) => {
                        provider.api_format = event.target.value as LLMProviderConfig['api_format'];
                      })
                    }
                  >
                    {(registry.custom_provider.fields?.api_format?.options || ['openai', 'anthropic', 'custom']).map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : null}

            <label className="space-y-2">
              <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
              <input
                aria-label={t('llm.fields.apiKey')}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                type="password"
                value={activeProvider.api_key || ''}
                onChange={(event) =>
                  onProviderChange(activeProviderId, (provider) => {
                    provider.api_key = event.target.value;
                  })
                }
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium">{t('llm.fields.baseUrl')}</span>
              <input
                aria-label={t('llm.fields.baseUrl')}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                value={activeProvider.base_url || ''}
                onChange={(event) =>
                  onProviderChange(activeProviderId, (provider) => {
                    provider.base_url = event.target.value;
                  })
                }
              />
            </label>

            {activeProviderMeta?.models?.length ? (
              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground">{t('llm.providerConfiguration.availableModels')}</div>
                <div className="flex flex-wrap gap-2">
                  {activeProviderMeta.models.map((model) => (
                    <span key={model.id} className={badgeClassName}>
                      {model.label || model.id}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
};
