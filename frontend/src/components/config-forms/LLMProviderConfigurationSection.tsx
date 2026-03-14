import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Eye, EyeOff, Loader2, Plus, PlugZap, Trash2, X, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { ProviderIcon } from '@/components/config-forms/provider-icons';
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
  surface?: 'onboarding' | 'settings';
  showSectionIntro?: boolean;
  scenarioReferences: Record<string, LLMScenario[]>;
  onActiveProviderChange: (providerId: string) => void;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onAddCustomProvider: () => void;
  onRemoveCustomProvider: (providerId: string) => void;
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
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

export const LLMProviderConfigurationSection: React.FC<LLMProviderConfigurationSectionProps> = ({
  registry,
  value,
  activeProviderId,
  quickMode = false,
  surface = 'onboarding',
  showSectionIntro = true,
  scenarioReferences,
  onActiveProviderChange,
  onProviderChange,
  onAddCustomProvider,
  onRemoveCustomProvider,
  onAddProviderModel,
  onRemoveProviderModel,
  onProviderDefaultModelChange,
  onDiscoverProviderModels,
  providerDiscoveryState,
  onTestProviderConnection,
  providerTestState,
}) => {
  const { t } = useTranslation('onboarding');
  const { t: appT } = useTranslation('app');
  const [modelDraft, setModelDraft] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const isSettingsSurface = surface === 'settings';

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
  const settingsWorkbenchColumnsClassName = quickMode
    ? 'xl:grid-cols-[250px_minmax(0,1fr)]'
    : 'xl:grid-cols-[280px_minmax(0,1fr)]';

  useEffect(() => {
    setModelDraft('');
    setShowApiKey(false);
  }, [activeProviderId]);

  const renderApiKeyField = () => (
    <label className="space-y-2">
      <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
      <div className="relative">
        <input
          aria-label={t('llm.fields.apiKey')}
          className={cn(fieldClassName, 'pr-10', isSettingsSurface && 'rounded-lg')}
          type={showApiKey ? 'text' : 'password'}
          value={activeProvider?.api_key || ''}
          onChange={(event) =>
            onProviderChange(activeProviderId, (provider) => {
              provider.api_key = event.target.value;
            })
          }
        />
        <button
          type="button"
          onClick={() => setShowApiKey((current) => !current)}
          className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent/50 hover:text-foreground"
          aria-label={showApiKey ? appT('settings.hideSensitiveValue') : appT('settings.showSensitiveValue')}
        >
          {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </label>
  );

  return (
    <section
      data-testid="llm-provider-configuration-section"
      className={cn(
        'space-y-4',
        isSettingsSurface && 'flex h-full min-h-0 flex-col space-y-0'
      )}
    >
      {showSectionIntro ? (
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
      ) : null}

      <div
        data-testid="llm-provider-workbench"
        className={cn(
          'grid min-h-0 gap-4 overflow-hidden rounded-[28px] bg-muted/35 p-3 sm:p-4',
          workbenchColumnsClassName,
          'md:h-[clamp(440px,56vh,680px)] xl:items-stretch',
          isSettingsSurface &&
            cn(
              'h-full gap-4 rounded-none bg-transparent p-0 sm:p-0 md:h-full',
              settingsWorkbenchColumnsClassName
            )
        )}
      >
        <div
          data-testid="llm-provider-list-pane"
          className={cn(
            'min-h-0 space-y-1.5 overflow-y-auto rounded-[24px] bg-background/55 p-2 sm:p-3',
            isSettingsSurface &&
              'flex min-h-0 flex-col rounded-2xl border border-border/70 bg-transparent p-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]'
          )}
        >
          <div className={cn('space-y-1.5', isSettingsSurface && 'flex-1 space-y-3 overflow-y-auto pr-1')}>
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
                      ? 'bg-primary/15 text-foreground ring-2 ring-primary/70'
                      : 'text-muted-foreground hover:bg-background/70 hover:text-foreground',
                    isSettingsSurface &&
                      (providerId === activeProviderId
                        ? 'rounded-xl bg-primary/12 shadow-sm ring-2 ring-primary/60'
                        : 'rounded-xl bg-transparent shadow-[0_1px_2px_rgba(15,23,42,0.03)] ring-1 ring-inset ring-border/60')
                  )}
                >
                  <ProviderIcon
                    providerId={provider.provider_type}
                    iconName={providerMeta?.icon || (provider.provider_type === 'custom' ? 'custom' : undefined)}
                    displayName={provider.display_name || providerMeta?.display_name || providerId}
                  />
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

          {isSettingsSurface ? (
            <div className="mt-4 border-t border-border/60 pt-4">
              <button
                type="button"
                onClick={onAddCustomProvider}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-border/70 bg-transparent px-3.5 py-3 text-sm font-medium text-foreground transition hover:bg-accent/40"
              >
                <Plus className="h-4 w-4" />
                <span>{t('llm.actions.addCustomProvider')}</span>
              </button>
            </div>
          ) : null}
        </div>

        {activeProvider ? (
          <div
            data-testid="llm-provider-detail-pane"
            className={cn(
              'min-h-0 overflow-y-auto rounded-[24px] bg-background/72 p-5 sm:p-6',
              isSettingsSurface &&
                'rounded-2xl border border-border/70 bg-transparent p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]'
            )}
          >
            <div className={cn('space-y-6', isSettingsSurface && 'space-y-5')}>
              <div className={cn('space-y-3', isSettingsSurface && 'space-y-4')}>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-2">
                    <div className="flex items-start gap-3">
                      <ProviderIcon
                        providerId={activeProvider.provider_type}
                        iconName={activeProviderMeta?.icon || (activeProvider.provider_type === 'custom' ? 'custom' : undefined)}
                        displayName={activeProvider.display_name || activeProviderMeta?.display_name || activeProviderId}
                        className="mt-0.5"
                      />
                      <div className="space-y-2">
                        <h4 className={cn('text-xl font-semibold tracking-[-0.01em] text-foreground', isSettingsSurface && 'text-lg')}>
                          {activeProvider.display_name || activeProviderMeta?.display_name || activeProviderId}
                        </h4>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={badgeClassName}>
                            {activeProvider.provider_type === 'custom'
                              ? t('llm.providerConfiguration.providerKinds.custom')
                              : t('llm.providerConfiguration.providerKinds.builtin')}
                          </span>
                        </div>
                      </div>
                    </div>
                    {activeReferences.length > 0 ? (
                      <p className="text-xs leading-5 text-muted-foreground">
                        {t('llm.providerConfiguration.referencedBy')}:{' '}
                        {activeReferences.map((scenario) => t(`llm.scenarios.${scenario}.title`)).join(' / ')}
                      </p>
                    ) : null}
                  </div>

                  <div className="flex shrink-0 items-center gap-2 whitespace-nowrap lg:justify-end">
                    {activeProvider.provider_type === 'custom' ? (
                      <button
                        type="button"
                        onClick={() => onRemoveCustomProvider(activeProviderId)}
                        className="inline-flex min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-xl bg-muted/70 px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-accent/60"
                      >
                        <Trash2 className="h-4 w-4" />
                        <span>{t('llm.actions.removeProvider')}</span>
                      </button>
                    ) : null}
                    <div className="inline-flex min-w-fit items-center gap-2 whitespace-nowrap rounded-full bg-muted/70 px-3 py-2">
                      <span className="whitespace-nowrap text-sm font-medium text-foreground">{t('llm.fields.enabled')}</span>
                      <Switch
                        aria-label={t('llm.fields.enabled')}
                        checked={activeProvider.enabled}
                        disabled={surface !== 'onboarding' && activeReferences.length > 0}
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
                      className="inline-flex min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-xl bg-muted/70 px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-accent/60 disabled:cursor-not-allowed disabled:opacity-60"
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

              <div className={cn('grid gap-4', !isSettingsSurface && 'lg:grid-cols-2')}>
                {activeProvider.provider_type === 'custom' ? (
                  <>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
                      <input
                        aria-label={t('llm.fields.displayName')}
                        className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
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
                      <SelectField
                        className="w-full"
                        triggerClassName={cn(
                          'h-11 rounded-xl border-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
                          isSettingsSurface && 'rounded-lg'
                        )}
                        value={activeProvider.api_format || 'openai'}
                        allowEmpty={false}
                        options={(registry.custom_provider.fields?.api_format?.options || ['openai', 'anthropic']).map((option) => ({
                          label: t(`llm.apiFormatOptions.${option}`),
                          value: option,
                        }))}
                        onChange={(nextValue) =>
                          onProviderChange(activeProviderId, (provider) => {
                            provider.api_format = nextValue as LLMProviderConfig['api_format'];
                          })
                        }
                      />
                    </label>

                    {renderApiKeyField()}

                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.baseUrl')}</span>
                      <input
                        aria-label={t('llm.fields.baseUrl')}
                        className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                        value={activeProvider.base_url || ''}
                        onChange={(event) =>
                          onProviderChange(activeProviderId, (provider) => {
                            provider.base_url = event.target.value;
                          })
                        }
                      />
                    </label>

                    <div
                      className={cn(
                        'space-y-4 rounded-[20px] bg-muted/40 p-4',
                        !isSettingsSurface && 'lg:col-span-2',
                        isSettingsSurface &&
                          'rounded-xl border border-border/65 bg-transparent p-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]'
                      )}
                    >
                      <div className="space-y-2">
                        <label className="block space-y-2">
                          <span className="text-sm font-medium">{t('llm.fields.defaultModel')}</span>
                          <SelectField
                            className="w-full"
                            triggerClassName={cn(
                              'h-11 rounded-xl border-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
                              isSettingsSurface && 'rounded-lg',
                              'disabled:cursor-not-allowed disabled:opacity-60'
                            )}
                            value={activeProvider.custom_default_model || ''}
                            disabled={!activeProvider.custom_models?.length}
                            placeholder={t('llm.providerConfiguration.defaultModelEmpty')}
                            allowEmpty={false}
                            options={(activeProvider.custom_models || []).map((model) => ({
                              label: model,
                              value: model,
                            }))}
                            onChange={(nextValue) => onProviderDefaultModelChange(activeProviderId, nextValue)}
                          />
                        </label>
                      </div>

                      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                        <label className="flex-1 space-y-2">
                          <span className="text-sm font-medium">{t('llm.fields.modelManualEntry')}</span>
                          <input
                            aria-label={t('llm.fields.modelManualEntry')}
                            className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                            placeholder={t('llm.fields.modelManualEntryPlaceholder')}
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
                          className="inline-flex h-11 min-w-fit items-center justify-center whitespace-nowrap rounded-lg bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent"
                        >
                          {t('llm.actions.addModel')}
                        </button>
                        <button
                          type="button"
                          onClick={() => onDiscoverProviderModels(activeProviderId)}
                          disabled={activeDiscoveryState.loading}
                          className="inline-flex h-11 min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {activeDiscoveryState.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                          <span>{t('llm.actions.fetchModels')}</span>
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

                      {activeDiscoveryState.error ? (
                        <p className="text-sm text-destructive">{activeDiscoveryState.error}</p>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <>
                    {renderApiKeyField()}

                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.baseUrl')}</span>
                      <input
                        aria-label={t('llm.fields.baseUrl')}
                        className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
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
                )}

                {activeProviderMeta?.models?.length ? (
                  <div className={cn('space-y-2 pt-1', !isSettingsSurface && 'lg:col-span-2')}>
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
