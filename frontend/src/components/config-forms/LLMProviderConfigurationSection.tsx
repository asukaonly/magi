import React, { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, ChevronDown, Loader2, Plus, Trash2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { LLMProviderApiKeyField } from '@/components/config-forms/LLMProviderApiKeyField';
import { LLMProviderListPane } from '@/components/config-forms/LLMProviderListPane';
import { LLMProviderTestMenu } from '@/components/config-forms/LLMProviderTestMenu';
import { ProviderIcon } from '@/components/config-forms/provider-icons';
import { Switch } from '@/components/ui/switch';
import {
  type LLMModelMetadataOverride,
  type LLMConfig,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
import { cn } from '@/lib/utils';
import {
  buildProviderWorkbenchModels,
  cloneModelOverride,
  isModelOverrideEmpty,
  type ProviderWorkbenchModelItem,
} from '@/components/config-forms/llm-provider-workbench-models';

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
  onAddProviderModel: (providerId: string, model: string, kind: 'chat' | 'embedding' | 'image') => void;
  onRemoveProviderModel: (providerId: string, model: string) => void;
  onProviderDefaultModelChange: (providerId: string, model: string) => void;
  onDiscoverProviderModels: (providerId: string) => void;
  providerDiscoveryState: Record<string, { loading: boolean; error: string | null }>;
  onTestProviderConnection: (providerId: string, model: string) => void;
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
  const [modelDraft, setModelDraft] = useState('');
  const [modelDraftKind, setModelDraftKind] = useState<'chat' | 'embedding' | 'image'>('chat');
  const [modelKindMenuOpen, setModelKindMenuOpen] = useState(false);
  const modelKindMenuRef = useRef<HTMLDivElement | null>(null);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [providerTestModels, setProviderTestModels] = useState<Record<string, string>>({});
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
        .map((providerId, index) => ({ providerId, provider: value.providers[providerId], index }))
        .filter((item): item is { providerId: string; provider: LLMProviderConfig; index: number } => Boolean(item.provider))
        .sort((left, right) => {
          if (left.provider.enabled === right.provider.enabled) {
            return left.index - right.index;
          }
          return left.provider.enabled ? -1 : 1;
        }),
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
  const activeWorkbenchModels = useMemo(
    () => buildProviderWorkbenchModels(registry, activeProviderId, activeProvider),
    [activeProvider, activeProviderId, registry]
  );
  const filteredWorkbenchModels = useMemo(
    () => activeWorkbenchModels.filter((model) => model.kinds.includes(modelDraftKind)),
    [activeWorkbenchModels, modelDraftKind]
  );
  const activeTestableModels = useMemo(
    () =>
      activeWorkbenchModels.filter(
        (model) => model.kinds.includes('chat') && !model.capabilities.embedding && !model.capabilities.image_output
      ),
    [activeWorkbenchModels]
  );
  const activeWorkbenchModel =
    filteredWorkbenchModels.find((model) => model.id === selectedModelId) || filteredWorkbenchModels[0];
  const resolveDefaultTestModel = (providerId: string, models: ProviderWorkbenchModelItem[]): string => {
    if (!models.length) {
      return '';
    }

    const testableModelIds = new Set(models.map((model) => model.id));
    const referencedSelection = Object.values(value.selections).find(
      (selection) => selection.provider_id === providerId && testableModelIds.has(selection.model)
    );

    return referencedSelection?.model || models[0]?.id || '';
  };
  const activeSelectedTestModel = providerTestModels[activeProviderId];
  const resolvedActiveTestModel =
    activeSelectedTestModel && activeTestableModels.some((model) => model.id === activeSelectedTestModel)
      ? activeSelectedTestModel
      : resolveDefaultTestModel(activeProviderId, activeTestableModels);
  const activeModelOverride =
    activeWorkbenchModel && activeProvider?.model_metadata_overrides
      ? activeProvider.model_metadata_overrides[activeWorkbenchModel.id]
      : undefined;
  const workbenchColumnsClassName = quickMode
    ? 'xl:grid-cols-[220px_minmax(0,1fr)]'
    : 'xl:grid-cols-[240px_minmax(0,1fr)]';
  const settingsWorkbenchColumnsClassName = quickMode
    ? 'xl:grid-cols-[250px_minmax(0,1fr)]'
    : 'xl:grid-cols-[280px_minmax(0,1fr)]';

  useEffect(() => {
    setModelDraft('');
    setModelDraftKind('chat');
    setModelKindMenuOpen(false);
    setSelectedModelId('');
    setShowApiKey(false);
  }, [activeProviderId]);

  useEffect(() => {
    if (!filteredWorkbenchModels.length) {
      if (selectedModelId) {
        setSelectedModelId('');
      }
      return;
    }

    if (!filteredWorkbenchModels.some((model) => model.id === selectedModelId)) {
      setSelectedModelId(filteredWorkbenchModels[0].id);
    }
  }, [filteredWorkbenchModels, selectedModelId]);

  useEffect(() => {
    if (!activeProviderId) {
      return;
    }

    if (!activeTestableModels.length) {
      if (providerTestModels[activeProviderId]) {
        setProviderTestModels((prev) => ({
          ...prev,
          [activeProviderId]: '',
        }));
      }
      return;
    }

    const nextModel = resolveDefaultTestModel(activeProviderId, activeTestableModels);
    if (nextModel && providerTestModels[activeProviderId] !== nextModel && !activeSelectedTestModel) {
      setProviderTestModels((prev) => ({
        ...prev,
        [activeProviderId]: nextModel,
      }));
    }
  }, [activeProviderId, activeSelectedTestModel, activeTestableModels, providerTestModels, value.selections]);

  useEffect(() => {
    if (!modelKindMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!modelKindMenuRef.current?.contains(event.target as Node)) {
        setModelKindMenuOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setModelKindMenuOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [modelKindMenuOpen]);

  const updateModelOverride = (modelId: string, updater: (draft: LLMModelMetadataOverride) => void) => {
    onProviderChange(activeProviderId, (provider) => {
      const overrides = { ...(provider.model_metadata_overrides || {}) };
      const nextOverride = cloneModelOverride(overrides[modelId]);
      updater(nextOverride);
      if (isModelOverrideEmpty(nextOverride)) {
        delete overrides[modelId];
      } else {
        overrides[modelId] = nextOverride;
      }
      provider.model_metadata_overrides = overrides;
    });
  };

  return (
    <section
      data-testid="llm-provider-configuration-section"
      className={cn(
        'flex min-h-0 flex-1 flex-col space-y-4',
        isSettingsSurface && 'space-y-0'
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
          'grid min-h-0 flex-1 gap-4 overflow-hidden rounded-[28px] bg-muted/35 p-3 sm:p-4',
          workbenchColumnsClassName,
          'md:min-h-[440px] xl:items-stretch',
          isSettingsSurface &&
            cn(
              'h-full gap-0 rounded-none bg-transparent p-0 sm:p-0 md:h-full',
              settingsWorkbenchColumnsClassName
            )
        )}
      >
        <LLMProviderListPane
          registry={registry}
          providerItems={providerItems}
          activeProviderId={activeProviderId}
          isSettingsSurface={isSettingsSurface}
          onActiveProviderChange={onActiveProviderChange}
          onAddCustomProvider={onAddCustomProvider}
        />

        {activeProvider ? (
          <div
            data-testid="llm-provider-detail-pane"
            className={cn(
              'min-h-0 overflow-y-auto rounded-[24px] bg-background/72 p-5 sm:p-6',
              isSettingsSurface &&
                'bg-transparent p-0 pl-6'
            )}
          >
            <div className={cn('space-y-6', isSettingsSurface && 'space-y-5')}>
              <div className={cn('space-y-3', isSettingsSurface && 'space-y-4 border-b border-[hsl(var(--settings-subnav-border)/0.72)] pb-5')}>
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

                  <div className="flex shrink-0 flex-wrap items-center gap-2.5 lg:justify-end">
                    {activeProvider.provider_type === 'custom' ? (
                      <button
                        type="button"
                        onClick={() => onRemoveCustomProvider(activeProviderId)}
                        className="inline-flex min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-md border border-destructive/18 bg-transparent px-3 py-2.5 text-sm font-medium text-destructive/85 transition hover:bg-destructive/6 hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                        <span>{t('llm.actions.removeProvider')}</span>
                      </button>
                    ) : null}
                    <div className="inline-flex min-w-fit items-center gap-2 whitespace-nowrap rounded-md bg-[hsl(var(--settings-shell-elevated)/0.58)] px-3 py-2 text-[hsl(var(--settings-nav-foreground))]">
                      <span className="whitespace-nowrap text-sm font-medium text-foreground/88">{t('llm.fields.enabled')}</span>
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
                    <LLMProviderTestMenu
                      providerId={activeProviderId}
                      isTesting={activeTestState.loading}
                      testableModels={activeTestableModels}
                      selectedModelId={resolvedActiveTestModel}
                      onSelectedModelChange={(providerId, modelId) =>
                        setProviderTestModels((prev) => ({
                          ...prev,
                          [providerId]: modelId,
                        }))
                      }
                      onTestProviderConnection={onTestProviderConnection}
                    />
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

              <div className="grid gap-4">
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

                    <LLMProviderApiKeyField
                      providerId={activeProviderId}
                      provider={activeProvider}
                      isSettingsSurface={isSettingsSurface}
                      showApiKey={showApiKey}
                      onShowApiKeyChange={setShowApiKey}
                      onProviderChange={onProviderChange}
                    />

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
                        isSettingsSurface &&
                          'space-y-5 rounded-none border-t border-[hsl(var(--settings-subnav-border)/0.72)] bg-transparent p-0 pt-5 shadow-none'
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
                    </div>
                  </>
                ) : (
                  <>
                    <LLMProviderApiKeyField
                      providerId={activeProviderId}
                      provider={activeProvider}
                      isSettingsSurface={isSettingsSurface}
                      showApiKey={showApiKey}
                      onShowApiKeyChange={setShowApiKey}
                      onProviderChange={onProviderChange}
                    />

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

                <div
                  className={cn(
                    'space-y-4 pt-1',
                    isSettingsSurface && 'border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-5'
                  )}
                >
                  <div className="text-sm font-medium text-foreground">{t('llm.providerConfiguration.availableModels')}</div>

                  <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                    <div className="space-y-2 sm:w-fit">
                      <span className="text-sm font-medium">{t('llm.fields.modelKind')}</span>
                      <div className="relative" ref={modelKindMenuRef}>
                        <button
                          type="button"
                          aria-haspopup="listbox"
                          aria-expanded={modelKindMenuOpen}
                          onClick={() => setModelKindMenuOpen((current) => !current)}
                          className={cn(
                            'inline-flex h-11 min-w-[160px] items-center justify-between gap-2 whitespace-nowrap rounded-md bg-[hsl(var(--settings-shell-elevated)/0.58)] px-3.5 text-sm font-medium text-foreground transition hover:bg-[hsl(var(--settings-shell-elevated)/0.82)]',
                            isSettingsSurface && 'border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]'
                          )}
                        >
                          <span>{t(`llm.modelKinds.${modelDraftKind}`)}</span>
                          <ChevronDown className={cn('h-4 w-4 opacity-65 transition', modelKindMenuOpen && 'rotate-180')} />
                        </button>

                        {modelKindMenuOpen ? (
                          <div
                            role="listbox"
                            className="absolute left-0 top-full z-20 mt-2 w-[min(220px,calc(100vw-2rem))] overflow-hidden rounded-[16px] border border-border/70 bg-background py-1.5 shadow-[0_18px_42px_rgba(15,23,42,0.16)]"
                          >
                            {(['chat', 'embedding', 'image'] as const).map((kindValue) => {
                              const isSelected = modelDraftKind === kindValue;
                              return (
                                <button
                                  key={kindValue}
                                  type="button"
                                  role="option"
                                  aria-selected={isSelected}
                                  onClick={() => {
                                    setModelDraftKind(kindValue);
                                    setModelKindMenuOpen(false);
                                  }}
                                  className={cn(
                                    'flex w-full items-center justify-between px-3 py-2.5 text-left text-sm text-foreground transition',
                                    isSelected ? 'bg-muted/80' : 'hover:bg-muted/50'
                                  )}
                                >
                                  <span>{t(`llm.modelKinds.${kindValue}`)}</span>
                                  {isSelected ? <CheckCircle2 className="h-4 w-4 text-primary" /> : null}
                                </button>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    </div>

                    {modelDraftKind !== 'image' ? (
                      <label className="flex-1 space-y-2">
                        <span className="text-sm font-medium">
                          {modelDraftKind === 'embedding'
                            ? t('llm.fields.modelManualEntryEmbedding')
                            : t('llm.fields.modelManualEntryChat')}
                        </span>
                        <input
                          aria-label={t('llm.fields.modelManualEntry')}
                          className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                          placeholder={
                            modelDraftKind === 'embedding'
                              ? t('llm.fields.modelManualEntryEmbeddingPlaceholder')
                              : t('llm.fields.modelManualEntryPlaceholder')
                          }
                          value={modelDraft}
                          onChange={(event) => setModelDraft(event.target.value)}
                        />
                      </label>
                    ) : (
                      <div className="flex-1 space-y-2 self-stretch">
                        <span className="text-sm font-medium opacity-0 select-none" aria-hidden="true">
                          {t('llm.fields.modelManualEntryChat')}
                        </span>
                        <p className="rounded-lg bg-muted/40 px-3 py-2.5 text-xs text-muted-foreground">
                          {t('llm.fields.imageModelsManagedByRegistry')}
                        </p>
                      </div>
                    )}
                    {modelDraftKind !== 'image' ? (
                      <button
                        type="button"
                        onClick={() => {
                          onAddProviderModel(activeProviderId, modelDraft, modelDraftKind);
                          setModelDraft('');
                        }}
                        className={cn(
                          'inline-flex h-11 min-w-fit items-center justify-center whitespace-nowrap rounded-lg bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent',
                          isSettingsSurface && 'rounded-md border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]'
                        )}
                      >
                        {t('llm.actions.addModel')}
                      </button>
                    ) : null}
                    {activeProvider.provider_type === 'custom' && modelDraftKind !== 'image' ? (
                      <button
                        type="button"
                        onClick={() => onDiscoverProviderModels(activeProviderId)}
                        disabled={activeDiscoveryState.loading}
                        className={cn(
                          'inline-flex h-11 min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60',
                          isSettingsSurface && 'rounded-md border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]'
                        )}
                      >
                        {activeDiscoveryState.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                        <span>{t('llm.actions.fetchModels')}</span>
                      </button>
                    ) : null}
                  </div>

                  {activeDiscoveryState.error ? (
                    <p className="text-sm text-destructive">{activeDiscoveryState.error}</p>
                  ) : null}

                  <div
                    className={cn(
                      'grid gap-4',
                      !isSettingsSurface && 'xl:grid-cols-[220px_minmax(0,1fr)]',
                      isSettingsSurface && 'xl:grid-cols-[240px_minmax(0,1fr)]'
                    )}
                  >
                    <div
                      data-testid="llm-provider-model-list-pane"
                      className={cn(
                        'space-y-1.5 rounded-[18px] bg-muted/35 p-2',
                        isSettingsSurface && 'rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.35)] p-2.5'
                      )}
                    >
                      {filteredWorkbenchModels.length ? (
                        filteredWorkbenchModels.map((model) => (
                          <button
                            key={model.id}
                            type="button"
                            onClick={() => setSelectedModelId(model.id)}
                            aria-current={activeWorkbenchModel?.id === model.id ? 'true' : undefined}
                            className={cn(
                              'relative w-full rounded-xl border px-3 py-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45',
                              activeWorkbenchModel?.id === model.id
                                ? 'border-border/70 bg-background text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.06)]'
                                : 'border-transparent text-muted-foreground hover:border-border/45 hover:bg-background/70 hover:text-foreground',
                              isSettingsSurface &&
                                (activeWorkbenchModel?.id === model.id
                                  ? 'rounded-md border-[hsl(var(--settings-subnav-border)/0.95)] bg-background/95 shadow-[0_2px_8px_rgba(15,23,42,0.04)]'
                                  : 'rounded-md hover:bg-background/60')
                            )}
                          >
                            {activeWorkbenchModel?.id === model.id ? (
                              <span
                                aria-hidden="true"
                                className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-[hsl(var(--settings-nav-active-foreground)/0.7)]"
                              />
                            ) : null}
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-medium">{model.label}</div>
                                <div className="truncate text-xs text-muted-foreground">{model.id}</div>
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5">
                                {model.kinds.includes('chat') ? <span className={badgeClassName}>{t('llm.badges.chat')}</span> : null}
                                {model.kinds.includes('embedding') ? <span className={badgeClassName}>{t('llm.badges.embedding')}</span> : null}
                                {model.kinds.includes('image') ? <span className={badgeClassName}>{t('llm.badges.image')}</span> : null}
                              </div>
                            </div>
                          </button>
                        ))
                      ) : (
                        <div className="rounded-lg bg-background/80 px-3 py-3 text-sm text-muted-foreground">
                          {t('llm.providerConfiguration.noEditableModels')}
                        </div>
                      )}
                    </div>

                    <div
                      data-testid="llm-provider-model-editor"
                      className={cn(
                        'space-y-4 rounded-[18px] bg-muted/25 p-4',
                        isSettingsSurface && 'rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.22)]'
                      )}
                    >
                      {activeWorkbenchModel ? (() => {
                        const activeKind: 'chat' | 'embedding' | 'image' =
                          activeWorkbenchModel.kinds.includes('image') &&
                          !activeWorkbenchModel.kinds.includes('chat') &&
                          !activeWorkbenchModel.kinds.includes('embedding')
                            ? 'image'
                            : activeWorkbenchModel.kinds.includes('embedding') &&
                              !activeWorkbenchModel.kinds.includes('chat')
                            ? 'embedding'
                            : 'chat';
                        const dimensionsValue =
                          activeModelOverride?.dimensions ?? activeWorkbenchModel.dimensions;

                        return (
                          <>
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="space-y-1">
                                <div className="text-base font-semibold text-foreground">{activeWorkbenchModel.label}</div>
                                <div className="text-xs text-muted-foreground">
                                  {t('llm.modelFields.modelId')}: {activeWorkbenchModel.id}
                                </div>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className={badgeClassName}>
                                  {activeKind === 'embedding'
                                    ? t('llm.modelKinds.embedding')
                                    : activeKind === 'image'
                                    ? t('llm.modelKinds.image')
                                    : t('llm.modelKinds.chat')}
                                </span>
                                <span className={badgeClassName}>
                                  {activeWorkbenchModel.source === 'manual'
                                    ? t('llm.providerConfiguration.providerKinds.custom')
                                    : t('llm.providerConfiguration.providerKinds.builtin')}
                                </span>
                                <button
                                  type="button"
                                  onClick={() =>
                                    onProviderChange(activeProviderId, (provider) => {
                                      const overrides = { ...(provider.model_metadata_overrides || {}) };
                                      const previous = overrides[activeWorkbenchModel.id];
                                      delete overrides[activeWorkbenchModel.id];
                                      // Preserve embedding-kind marker for manual embedding-only models so they don't
                                      // disappear (manual embedding models live solely in the override map).
                                      if (
                                        previous?.capabilities?.embedding === true &&
                                        activeWorkbenchModel.source === 'manual' &&
                                        !(provider.custom_models || []).includes(activeWorkbenchModel.id)
                                      ) {
                                        overrides[activeWorkbenchModel.id] = {
                                          capabilities: { embedding: true },
                                        };
                                      }
                                      provider.model_metadata_overrides = overrides;
                                    })
                                  }
                                  className="inline-flex h-9 items-center justify-center rounded-md border border-border/70 px-3 text-sm text-foreground transition hover:bg-background/70"
                                >
                                  {t('llm.actions.restoreModelDefaults')}
                                </button>
                                {activeWorkbenchModel.source === 'manual' ? (
                                  <button
                                    type="button"
                                    onClick={() => onRemoveProviderModel(activeProviderId, activeWorkbenchModel.id)}
                                    className="inline-flex h-9 items-center justify-center rounded-md border border-destructive/25 px-3 text-sm text-destructive transition hover:bg-destructive/6"
                                  >
                                    {t('llm.actions.removeModel')}
                                  </button>
                                ) : null}
                              </div>
                            </div>

                            <div className="grid gap-4">
                              <label className="space-y-2">
                                <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
                                <input
                                  aria-label={t('llm.fields.displayName')}
                                  className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                                  value={activeModelOverride?.label ?? activeWorkbenchModel.label}
                                  onChange={(event) =>
                                    updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                      draft.label = event.target.value.trim() || undefined;
                                    })
                                  }
                                />
                              </label>
                            </div>

                            {activeKind === 'chat' ? (
                              <>
                                <div className={cn('grid gap-3', !isSettingsSurface && 'md:grid-cols-2 xl:grid-cols-3')}>
                                  {([
                                    ['vision', t('llm.modelFields.vision')],
                                    ['tool_calling', t('llm.modelFields.toolCalling')],
                                    ['reasoning', t('llm.modelFields.reasoning')],
                                  ] as const).map(([field, label]) => {                                    const checked = Boolean(
                                      activeModelOverride?.capabilities?.[field] ?? activeWorkbenchModel.capabilities[field]
                                    );

                                    return (
                                      <div
                                        key={field}
                                        className="flex items-center justify-between rounded-xl bg-background/80 px-3 py-2.5"
                                      >
                                        <span className="text-sm text-foreground">{label}</span>
                                        <Switch
                                          aria-label={label}
                                          checked={checked}
                                          onCheckedChange={(nextValue) =>
                                            updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                              draft.capabilities = { ...(draft.capabilities || {}), [field]: nextValue };
                                            })
                                          }
                                        />
                                      </div>
                                    );
                                  })}
                                </div>

                                <div className={cn('grid gap-4', !isSettingsSurface && 'lg:grid-cols-3')}>
                                  <label className="space-y-2">
                                    <span className="text-sm font-medium">{t('llm.modelFields.contextWindow')}</span>
                                    <div className="relative">
                                      <input
                                        aria-label={t('llm.modelFields.contextWindow')}
                                        className={cn(fieldClassName, 'pr-8', isSettingsSurface && 'rounded-lg')}
                                        type="number"
                                        min={1}
                                        step={1}
                                        value={((activeModelOverride?.limits?.context_window ?? activeWorkbenchModel.limits.context_window) ?? 0) / 1000 || ''}
                                        onChange={(event) =>
                                          updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                            const v = event.target.value.trim();
                                            draft.limits = { ...(draft.limits || {}), context_window: v ? Number(v) * 1000 : undefined };
                                          })
                                        }
                                      />
                                      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">K</span>
                                    </div>
                                  </label>

                                  <label className="space-y-2">
                                    <span className="text-sm font-medium">{t('llm.modelFields.maxOutputTokens')}</span>
                                    <div className="relative">
                                      <input
                                        aria-label={t('llm.modelFields.maxOutputTokens')}
                                        className={cn(fieldClassName, 'pr-8', isSettingsSurface && 'rounded-lg')}
                                        type="number"
                                        min={1}
                                        step={1}
                                        value={((activeModelOverride?.limits?.max_output_tokens ?? activeWorkbenchModel.limits.max_output_tokens) ?? 0) / 1000 || ''}
                                        onChange={(event) =>
                                          updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                            const v = event.target.value.trim();
                                            draft.limits = { ...(draft.limits || {}), max_output_tokens: v ? Number(v) * 1000 : undefined };
                                          })
                                        }
                                      />
                                      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">K</span>
                                    </div>
                                  </label>

                                  <label className="space-y-2">
                                    <span className="text-sm font-medium">{t('llm.modelFields.maxConcurrency')}</span>
                                    <input
                                      aria-label={t('llm.modelFields.maxConcurrency')}
                                      className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                                      type="number"
                                      min={1}
                                      step={1}
                                      value={activeModelOverride?.limits?.max_concurrency ?? activeWorkbenchModel.limits.max_concurrency ?? ''}
                                      onChange={(event) =>
                                        updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                          const nextValue = event.target.value.trim();
                                          draft.limits = {
                                            ...(draft.limits || {}),
                                            max_concurrency: nextValue ? Number(nextValue) : undefined,
                                          };
                                        })
                                      }
                                    />
                                  </label>
                                </div>
                              </>
                            ) : activeKind === 'embedding' ? (
                              <div className="space-y-4">
                                <div className="space-y-2">
                                  <span className="text-sm font-medium">{t('llm.modelFields.dimensions')}</span>
                                  <div
                                    className={cn(
                                      'flex flex-wrap items-center gap-2 rounded-xl bg-background/80 p-2 ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
                                      isSettingsSurface && 'rounded-lg'
                                    )}
                                  >
                                    {(dimensionsValue || []).map((dimension, index) => (
                                      <span
                                        key={`${dimension}-${index}`}
                                        className="inline-flex items-center gap-1.5 rounded-full bg-muted/80 py-1 pl-3 pr-1 text-sm text-foreground"
                                      >
                                        <span className="tabular-nums">{dimension}</span>
                                        <button
                                          type="button"
                                          aria-label={t('llm.modelFields.dimensionsRemove', { value: dimension })}
                                          onClick={() =>
                                            updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                              draft.capabilities = {
                                                ...(draft.capabilities || {}),
                                                embedding: true,
                                              };
                                              const next = (dimensionsValue || []).filter(
                                                (_value, position) => position !== index
                                              );
                                              draft.dimensions = next.length ? next : null;
                                            })
                                          }
                                          className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition hover:bg-background hover:text-foreground"
                                        >
                                          <XCircle className="h-3.5 w-3.5" />
                                        </button>
                                      </span>
                                    ))}
                                    <input
                                      aria-label={t('llm.modelFields.dimensionsAdd')}
                                      type="number"
                                      min={1}
                                      step={1}
                                      placeholder={t('llm.modelFields.dimensionsAddPlaceholder')}
                                      className="h-8 min-w-[120px] flex-1 bg-transparent px-2 text-sm focus-visible:outline-none"
                                      onKeyDown={(event) => {
                                        if (event.key !== 'Enter' && event.key !== ',') {
                                          return;
                                        }
                                        event.preventDefault();
                                        const target = event.currentTarget;
                                        const raw = target.value.trim();
                                        if (!raw) {
                                          return;
                                        }
                                        const parsed = Math.floor(Number(raw));
                                        if (!Number.isFinite(parsed) || parsed <= 0) {
                                          return;
                                        }
                                        updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                          draft.capabilities = {
                                            ...(draft.capabilities || {}),
                                            embedding: true,
                                          };
                                          const current = dimensionsValue || [];
                                          if (current.includes(parsed)) {
                                            return;
                                          }
                                          draft.dimensions = [...current, parsed];
                                        });
                                        target.value = '';
                                      }}
                                      onBlur={(event) => {
                                        const raw = event.target.value.trim();
                                        if (!raw) {
                                          return;
                                        }
                                        const parsed = Math.floor(Number(raw));
                                        if (!Number.isFinite(parsed) || parsed <= 0) {
                                          event.target.value = '';
                                          return;
                                        }
                                        updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                          draft.capabilities = {
                                            ...(draft.capabilities || {}),
                                            embedding: true,
                                          };
                                          const current = dimensionsValue || [];
                                          if (!current.includes(parsed)) {
                                            draft.dimensions = [...current, parsed];
                                          }
                                        });
                                        event.target.value = '';
                                      }}
                                    />
                                  </div>
                                  <span className="block text-xs text-muted-foreground">
                                    {t('llm.modelFields.dimensionsChipHint')}
                                  </span>
                                </div>

                                <label className="block space-y-2 sm:max-w-xs">
                                  <span className="text-sm font-medium">{t('llm.modelFields.maxConcurrency')}</span>
                                  <input
                                    aria-label={t('llm.modelFields.maxConcurrency')}
                                    className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                                    type="number"
                                    min={1}
                                    step={1}
                                    value={activeModelOverride?.limits?.max_concurrency ?? activeWorkbenchModel.limits.max_concurrency ?? ''}
                                    onChange={(event) =>
                                      updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                        const nextValue = event.target.value.trim();
                                        if (activeKind === 'embedding') {
                                          draft.capabilities = {
                                            ...(draft.capabilities || {}),
                                            embedding: true,
                                          };
                                        }
                                        draft.limits = {
                                          ...(draft.limits || {}),
                                          max_concurrency: nextValue ? Number(nextValue) : undefined,
                                        };
                                      })
                                    }
                                  />
                                </label>
                              </div>
                            ) : (
                              <div className="space-y-3">
                                <p className="rounded-xl bg-background/80 px-3 py-3 text-sm text-muted-foreground">
                                  {t('llm.modelFields.imageRuntimeHint')}
                                </p>
                                <ul className="grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
                                  <li className="rounded-lg bg-background/60 px-3 py-2">
                                    <span className="block text-xs font-medium text-foreground">{t('llm.modelFields.imageSizes')}</span>
                                    <span>1024×1024 / 1024×1536 / 1536×1024 / auto</span>
                                  </li>
                                  <li className="rounded-lg bg-background/60 px-3 py-2">
                                    <span className="block text-xs font-medium text-foreground">{t('llm.modelFields.imageQuality')}</span>
                                    <span>auto / high / medium / low</span>
                                  </li>
                                </ul>
                              </div>
                            )}
                          </>
                        );
                      })() : (
                        <div className="rounded-lg bg-background/80 px-3 py-3 text-sm text-muted-foreground">
                          {t('llm.providerConfiguration.noModelSelected')}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
};
