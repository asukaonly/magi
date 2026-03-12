import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Loader2, Plus, PlugZap, X, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Switch } from '@/components/ui/switch';
import type {
  LLMConfig,
  LLMProviderConfig,
  LLMProviderRegistry,
  LLMScenario,
  TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
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
  onTestProviderConnection: (providerId: string) => void;
  providerTestState: Record<
    string,
    {
      loading: boolean;
      error: string | null;
      result: TestLLMProviderConnectionResponse | null;
    }
  >;
}

const badgeClassName =
  'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground';

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

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
  onTestProviderConnection,
  providerTestState,
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
  const providerItems = useMemo(
    () =>
      providerOrder
        .map((providerId) => ({ providerId, provider: value.providers[providerId] }))
        .filter((item): item is { providerId: string; provider: LLMProviderConfig } => Boolean(item.provider)),
    [providerOrder, value.providers]
  );

  const activeProvider = value.providers[activeProviderId] || value.providers[providerOrder[0]];
  const activeProviderMeta =
    activeProvider?.provider_type === 'custom'
      ? undefined
      : registry.providers.find((provider) => provider.id === activeProvider?.provider_type);
  const activeReferences = scenarioReferences[activeProviderId] || [];
  const activeDiscoveryState = providerDiscoveryState[activeProviderId] || { loading: false, error: null };
  const activeTestState = providerTestState[activeProviderId] || { loading: false, error: null, result: null };
  const workbenchColumnsClassName = quickMode
    ? 'xl:grid-cols-[220px_minmax(0,1fr)]'
    : 'xl:grid-cols-[240px_minmax(0,1fr)]';

  useEffect(() => {
    setModelDraft('');
  }, [activeProviderId]);

  return (
    <section data-testid="llm-provider-configuration-section" className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1.5">
          <h3 className="text-lg font-semibold text-foreground sm:text-xl">{t('llm.providerConfiguration.title')}</h3>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.providerConfiguration.desc')}</p>
        </div>
        <button
          type="button"
          onClick={onAddCustomProvider}
          className="inline-flex items-center gap-2 self-start rounded-xl bg-muted px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-accent"
        >
          <Plus className="h-4 w-4" />
          <span>{t('llm.actions.addCustomProvider')}</span>
        </button>
      </div>

      <div
        data-testid="llm-provider-workbench"
        className={cn(
          'grid min-h-0 gap-4 overflow-hidden rounded-[28px] bg-muted/35 p-3 sm:p-4',
          workbenchColumnsClassName,
          'md:h-[clamp(440px,56vh,680px)] xl:items-stretch'
        )}
      >
        <div
          data-testid="llm-provider-list-pane"
          className="min-h-0 space-y-1.5 overflow-y-auto rounded-[24px] bg-background/55 p-2 sm:p-3"
        >
          {providerItems.map(({ providerId, provider }) => {
            const providerMeta =
              provider.provider_type === 'custom'
                ? undefined
                : registry.providers.find((item) => item.id === provider.provider_type);

            return (
              <button
                key={providerId}
                type="button"
                onClick={() => onActiveProviderChange(providerId)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                  providerId === activeProviderId
                    ? 'bg-background text-foreground'
                    : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold tracking-[0.01em] text-foreground sm:text-base">
                    {provider.display_name || providerMeta?.display_name || providerId}
                  </div>
                </div>
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={cn('h-2.5 w-2.5 rounded-full', provider.enabled ? 'bg-emerald-500' : 'bg-border')}
                  />
                  <span className="sr-only">
                    {provider.enabled ? t('llm.badges.enabled') : t('llm.badges.disabled')}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {activeProvider ? (
          <div
            data-testid="llm-provider-detail-pane"
            className="min-h-0 overflow-y-auto rounded-[24px] bg-background/72 p-5 sm:p-6"
          >
            <div className="space-y-6">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={badgeClassName}>
                    {activeProvider.provider_type === 'custom'
                      ? t('llm.providerConfiguration.providerKinds.custom')
                      : t('llm.providerConfiguration.providerKinds.builtin')}
                  </span>
                  {activeReferences.length > 0 ? (
                    <span className={badgeClassName}>
                      {t('llm.providerConfiguration.referencedBy')}:{' '}
                      {activeReferences.map((scenario) => t(`llm.scenarios.${scenario}.title`)).join(' / ')}
                    </span>
                  ) : null}
                </div>

                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-1.5">
                    <h4 className="text-xl font-semibold tracking-[-0.01em] text-foreground">
                      {activeProvider.display_name || activeProviderMeta?.display_name || activeProviderId}
                    </h4>
                    <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                      {activeProviderMeta?.description || t('llm.providerConfiguration.customProviderHint')}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <div className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-2">
                      <span className="text-sm font-medium text-foreground">{t('llm.fields.enabled')}</span>
                      <Switch
                        aria-label={t('llm.fields.enabled')}
                        checked={activeProvider.enabled}
                        disabled={activeReferences.length > 0}
                        onCheckedChange={(checked) =>
                          onProviderChange(activeProviderId, (provider) => {
                            provider.enabled = checked;
                          })
                        }
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => onTestProviderConnection(activeProviderId)}
                      disabled={activeTestState.loading}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-muted px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {activeTestState.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                      <span>
                        {activeTestState.loading
                          ? t('llm.actions.testingConnection')
                          : t('llm.actions.testConnection')}
                      </span>
                    </button>
                  </div>
                </div>
              </div>

              {activeTestState.error ? (
                <div className="flex items-start gap-2 rounded-xl bg-destructive/8 px-3 py-2.5 text-sm text-destructive">
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <div className="space-y-0.5">
                    <div className="font-medium">{t('llm.providerConfiguration.testFailed')}</div>
                    <p>{activeTestState.error}</p>
                  </div>
                </div>
              ) : null}

              {activeTestState.result ? (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-emerald-500/10 px-3 py-2.5 text-sm text-emerald-900 dark:text-emerald-200">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span className="font-medium">{t('llm.providerConfiguration.testSuccess')}</span>
                  <span>
                    {t('llm.providerConfiguration.testSuccessMeta', {
                      model: activeTestState.result.model,
                      latency: activeTestState.result.latency_ms,
                    })}
                  </span>
                  {activeTestState.result.preview ? (
                    <span className="text-emerald-900/80 dark:text-emerald-100/80">
                      {t('llm.providerConfiguration.testPreview', { preview: activeTestState.result.preview })}
                    </span>
                  ) : null}
                </div>
              ) : null}

              <div className="grid gap-4 lg:grid-cols-2">
                {activeProvider.provider_type === 'custom' ? (
                  <>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
                      <input
                        aria-label={t('llm.fields.apiKey')}
                        className={fieldClassName}
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
                        className={fieldClassName}
                        value={activeProvider.base_url || ''}
                        onChange={(event) =>
                          onProviderChange(activeProviderId, (provider) => {
                            provider.base_url = event.target.value;
                          })
                        }
                      />
                    </label>

                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
                      <input
                        aria-label={t('llm.fields.displayName')}
                        className={fieldClassName}
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
                        className={fieldClassName}
                        value={activeProvider.api_format || 'openai'}
                        onChange={(event) =>
                          onProviderChange(activeProviderId, (provider) => {
                            provider.api_format = event.target.value as LLMProviderConfig['api_format'];
                          })
                        }
                      >
                        {(registry.custom_provider.fields?.api_format?.options || ['openai', 'anthropic']).map((option) => (
                          <option key={option} value={option}>
                            {t(`llm.apiFormatOptions.${option}`)}
                          </option>
                        ))}
                      </select>
                    </label>

                    <div className="space-y-4 rounded-[20px] bg-muted/40 p-4 lg:col-span-2">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                        <label className="flex-1 space-y-2">
                          <span className="text-sm font-medium">{t('llm.fields.modelManualEntry')}</span>
                          <input
                            aria-label={t('llm.fields.modelManualEntry')}
                            className={fieldClassName}
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
                          className="inline-flex h-11 items-center justify-center rounded-xl bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent"
                        >
                          {t('llm.actions.addModel')}
                        </button>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {(activeProvider.custom_models || []).map((model) => (
                          <span
                            key={model}
                            className="inline-flex items-center gap-1 rounded-full bg-background px-3 py-1 text-xs text-foreground"
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
                          <select
                            aria-label={t('llm.fields.defaultModel')}
                            className={cn(fieldClassName, 'disabled:cursor-not-allowed disabled:opacity-60')}
                            value={activeProvider.custom_default_model || ''}
                            disabled={!activeProvider.custom_models?.length}
                            onChange={(event) => onProviderDefaultModelChange(activeProviderId, event.target.value)}
                          >
                            {!activeProvider.custom_models?.length ? (
                              <option value="">{t('llm.providerConfiguration.defaultModelEmpty')}</option>
                            ) : null}
                            {(activeProvider.custom_models || []).map((model) => (
                              <option key={model} value={model}>
                                {model}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          type="button"
                          onClick={() => onDiscoverProviderModels(activeProviderId)}
                          disabled={activeDiscoveryState.loading}
                          className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
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

                {activeProvider.provider_type !== 'custom' ? (
                  <>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
                      <input
                        aria-label={t('llm.fields.apiKey')}
                        className={fieldClassName}
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
                        className={fieldClassName}
                        placeholder={activeProviderMeta?.default_base_url || ''}
                        value={activeProvider.base_url || ''}
                        onChange={(event) =>
                          onProviderChange(activeProviderId, (provider) => {
                            provider.base_url = event.target.value;
                          })
                        }
                      />
                    </label>
                  </>
                ) : null}

                {activeProviderMeta?.models?.length ? (
                  <div className="space-y-2 pt-1 lg:col-span-2">
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
