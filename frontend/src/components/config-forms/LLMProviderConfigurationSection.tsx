import React, { useEffect, useState } from 'react';
import { Loader2, Plus, X } from 'lucide-react';
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
  onAddProviderModel: (providerId: string, model: string) => void;
  onRemoveProviderModel: (providerId: string, model: string) => void;
  onProviderDefaultModelChange: (providerId: string, model: string) => void;
  onDiscoverProviderModels: (providerId: string) => void;
  providerDiscoveryState: Record<string, { loading: boolean; error: string | null }>;
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
  onAddProviderModel,
  onRemoveProviderModel,
  onProviderDefaultModelChange,
  onDiscoverProviderModels,
  providerDiscoveryState,
}) => {
  const { t } = useTranslation('onboarding');
  const [modelDraft, setModelDraft] = useState('');
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
  const activeDiscoveryState = providerDiscoveryState[activeProviderId] || { loading: false, error: null };
  const workbenchColumnsClassName = quickMode
    ? 'xl:grid-cols-[280px_minmax(0,1fr)]'
    : 'xl:grid-cols-[320px_minmax(0,1fr)]';

  useEffect(() => {
    setModelDraft('');
  }, [activeProviderId]);

  return (
    <section
      data-testid="llm-provider-configuration-section"
      className="space-y-5 rounded-[28px] border border-border/60 bg-card/80 p-4 shadow-sm backdrop-blur-sm sm:p-5 lg:p-6"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1.5">
          <h3 className="text-lg font-semibold text-foreground sm:text-xl">{t('llm.providerConfiguration.title')}</h3>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.providerConfiguration.desc')}</p>
        </div>
        <button
          type="button"
          onClick={onAddCustomProvider}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium text-foreground shadow-sm transition hover:border-primary/40 hover:bg-primary/5"
        >
          <Plus className="h-4 w-4" />
          <span>{t('llm.actions.addCustomProvider')}</span>
        </button>
      </div>

      <div
        data-testid="llm-provider-workbench"
        className={cn(
          'grid gap-0 overflow-hidden rounded-[24px] border border-border/50 bg-muted/20 shadow-inner',
          workbenchColumnsClassName,
          'xl:h-[clamp(440px,58vh,680px)]'
        )}
      >
        <div className="min-h-0 space-y-3 overflow-y-auto p-3 sm:p-4 xl:border-r xl:border-border/40 xl:bg-muted/35">
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
              provider.provider_type === 'custom'
                ? provider.custom_models || []
                : providerMeta?.models?.map((model) => model.label || model.id) || [];

            return (
              <button
                key={providerId}
                type="button"
                onClick={() => onActiveProviderChange(providerId)}
                className={cn(
                  'w-full rounded-2xl border p-4 text-left transition',
                  providerId === activeProviderId
                    ? 'border-primary/70 bg-background shadow-sm ring-1 ring-primary/10'
                    : 'border-border/70 bg-background/70 hover:border-primary/30 hover:bg-background'
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-foreground sm:text-base">
                      {provider.display_name || providerMeta?.display_name || providerId}
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
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
          <div
            data-testid="llm-provider-detail-pane"
            className="min-h-0 overflow-y-auto bg-background p-5 sm:p-6"
          >
            <div className="space-y-5 rounded-[22px] border border-border/60 bg-card p-5 shadow-sm">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1">
                  <h4 className="text-base font-semibold text-foreground sm:text-lg">
                    {activeProvider.display_name || activeProviderMeta?.display_name || activeProviderId}
                  </h4>
                  <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                    {activeProviderMeta?.description || t('llm.providerConfiguration.customProviderHint')}
                  </p>
                </div>

                <label className="flex items-center gap-2 rounded-full border border-border/60 bg-muted/30 px-3 py-2 text-sm text-foreground">
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
                  {t('llm.providerConfiguration.referencedBy')}:{' '}
                  {activeReferences.map((scenario) => t(`llm.scenarios.${scenario}.title`)).join(' / ')}
                </div>
              ) : null}

              <div className="grid gap-4">
                {activeProvider.provider_type === 'custom' ? (
                  <>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
                      <input
                        aria-label={t('llm.fields.displayName')}
                        className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
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
                        className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
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

                    <div className="space-y-3 rounded-2xl border border-border/50 bg-muted/20 p-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                        <label className="flex-1 space-y-2">
                          <span className="text-sm font-medium">{t('llm.fields.modelManualEntry')}</span>
                          <input
                            aria-label={t('llm.fields.modelManualEntry')}
                            className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                            value={modelDraft}
                            onChange={(event) => setModelDraft(event.target.value)}
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => {
                            onAddProviderModel(activeProviderId, modelDraft);
                            setModelDraft('');
                          }}
                          className="inline-flex h-11 items-center justify-center rounded-xl border border-border bg-background px-4 text-sm font-medium text-foreground transition hover:border-primary/40 hover:bg-primary/5"
                        >
                          {t('llm.actions.addModel')}
                        </button>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {(activeProvider.custom_models || []).map((model) => (
                          <span
                            key={model}
                            className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-3 py-1 text-xs text-foreground"
                          >
                            <span>{model}</span>
                            <button
                              type="button"
                              aria-label={`${t('llm.actions.removeModel')} ${model}`}
                              className="text-muted-foreground transition hover:text-foreground"
                              onClick={() => onRemoveProviderModel(activeProviderId, model)}
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </span>
                        ))}
                      </div>

                      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                        <label className="flex-1 space-y-2">
                          <span className="text-sm font-medium">{t('llm.fields.defaultModel')}</span>
                          {activeProvider.custom_models?.length ? (
                            <select
                              aria-label={t('llm.fields.defaultModel')}
                              className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                              value={activeProvider.custom_default_model || ''}
                              onChange={(event) => onProviderDefaultModelChange(activeProviderId, event.target.value)}
                            >
                              {(activeProvider.custom_models || []).map((model) => (
                                <option key={model} value={model}>
                                  {model}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              aria-label={t('llm.fields.defaultModel')}
                              className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                              value={activeProvider.custom_default_model || ''}
                              onChange={(event) => onProviderDefaultModelChange(activeProviderId, event.target.value)}
                            />
                          )}
                        </label>
                        <button
                          type="button"
                          onClick={() => onDiscoverProviderModels(activeProviderId)}
                          disabled={activeDiscoveryState.loading}
                          className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-border bg-background px-4 text-sm font-medium text-foreground transition hover:border-primary/40 hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {activeDiscoveryState.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                          <span>{t('llm.actions.fetchModels')}</span>
                        </button>
                      </div>

                      {activeDiscoveryState.error ? (
                        <p className="text-sm text-destructive">{activeDiscoveryState.error}</p>
                      ) : null}
                    </div>
                  </>
                ) : null}

                <label className="space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
                  <input
                    aria-label={t('llm.fields.apiKey')}
                    className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
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
                    className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                    value={activeProvider.base_url || ''}
                    onChange={(event) =>
                      onProviderChange(activeProviderId, (provider) => {
                        provider.base_url = event.target.value;
                      })
                    }
                  />
                </label>

                {activeProviderMeta?.models?.length ? (
                  <div className="space-y-2 rounded-2xl border border-border/50 bg-muted/20 p-4">
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
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
};
