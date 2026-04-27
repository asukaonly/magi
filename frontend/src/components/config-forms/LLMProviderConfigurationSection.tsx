import React, { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, ChevronDown, Eye, EyeOff, Loader2, Plus, PlugZap, Search, Trash2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { ProviderIcon } from '@/components/config-forms/provider-icons';
import { Switch } from '@/components/ui/switch';
import {
  resolveProviderModels,
  type LLMModelMetadataOverride,
  type LLMConfig,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type TestLLMProviderConnectionResponse,
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
  onAddProviderModel: (providerId: string, model: string, kind: 'chat' | 'embedding') => void;
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

interface ProviderWorkbenchModelItem {
  id: string;
  label: string;
  source: 'builtin' | 'manual';
  capabilities: {
    vision: boolean;
    image_output: boolean;
    tool_calling: boolean;
    reasoning: boolean;
    embedding: boolean;
  };
  limits: {
    context_window?: number | null;
    max_output_tokens?: number | null;
    max_concurrency?: number | null;
  };
  kinds: Array<'chat' | 'embedding'>;
  dimensions: number[];
}

const buildProviderWorkbenchModels = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig | undefined
): ProviderWorkbenchModelItem[] => {
  if (!provider) {
    return [];
  }

  const resolved = resolveProviderModels(registry, providerId, provider);
  const models = new Map<string, ProviderWorkbenchModelItem>();

  for (const model of resolved.chat_models) {
    models.set(model.id, {
      id: model.id,
      label: model.label || model.id,
      source: model.source,
      capabilities: {
        vision: model.capabilities.vision,
        image_output: model.capabilities.image_output,
        tool_calling: model.capabilities.tool_calling,
        reasoning: model.capabilities.reasoning,
        embedding: false,
      },
      limits: model.limits || {},
      kinds: ['chat'],
      dimensions: [],
    });
  }

  for (const model of resolved.embedding_models) {
    const existing = models.get(model.id);
    if (existing) {
      existing.kinds = Array.from(new Set([...existing.kinds, 'embedding']));
      existing.capabilities = model.capabilities;
      existing.limits = model.limits || {};
      existing.dimensions = [...(model.dimensions || [])];
      continue;
    }

    models.set(model.id, {
      id: model.id,
      label: model.label || model.id,
      source: model.source,
      capabilities: model.capabilities,
      limits: model.limits || {},
      kinds: ['embedding'],
      dimensions: [...(model.dimensions || [])],
    });
  }

  return Array.from(models.values()).sort((left, right) => {
    if (left.source !== right.source) {
      return left.source === 'builtin' ? -1 : 1;
    }
    return left.label.localeCompare(right.label, 'en');
  });
};

const cloneModelOverride = (value?: LLMModelMetadataOverride): LLMModelMetadataOverride => ({
  ...(value || {}),
  capabilities: { ...(value?.capabilities || {}) },
  limits: { ...(value?.limits || {}) },
  input_modalities:
    value?.input_modalities === null ? null : value?.input_modalities ? [...value.input_modalities] : undefined,
  output_modalities:
    value?.output_modalities === null ? null : value?.output_modalities ? [...value.output_modalities] : undefined,
  provider_options_example:
    value?.provider_options_example === null
      ? null
      : value?.provider_options_example
        ? { ...value.provider_options_example }
        : undefined,
  dimensions:
    value?.dimensions === null ? null : value?.dimensions ? [...value.dimensions] : undefined,
});

const isModelOverrideEmpty = (value: LLMModelMetadataOverride): boolean => {
  const capabilities = Object.values(value.capabilities || {}).every((item) => item === null || item === undefined);
  const limits = Object.values(value.limits || {}).every((item) => item === null || item === undefined);

  return !value.label &&
    capabilities &&
    limits &&
    (value.input_modalities === undefined || value.input_modalities === null) &&
    (value.output_modalities === undefined || value.output_modalities === null) &&
    (value.provider_options_example === undefined || value.provider_options_example === null) &&
    (value.dimensions === undefined || value.dimensions === null) &&
    !value.source_note;
};

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
  const [modelDraftKind, setModelDraftKind] = useState<'chat' | 'embedding'>('chat');
  const [selectedModelId, setSelectedModelId] = useState('');
  const [providerTestModels, setProviderTestModels] = useState<Record<string, string>>({});
  const [providerTestMenuOpen, setProviderTestMenuOpen] = useState(false);
  const [providerTestQuery, setProviderTestQuery] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const providerTestMenuRef = useRef<HTMLDivElement | null>(null);
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
  const activeTestableModels = useMemo(
    () =>
      activeWorkbenchModels.filter(
        (model) => model.kinds.includes('chat') && !model.capabilities.embedding && !model.capabilities.image_output
      ),
    [activeWorkbenchModels]
  );
  const activeWorkbenchModel = activeWorkbenchModels.find((model) => model.id === selectedModelId) || activeWorkbenchModels[0];
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
  const normalizedProviderTestQuery = providerTestQuery.trim().toLowerCase();
  const filteredActiveTestableModels = normalizedProviderTestQuery
    ? activeTestableModels.filter((model) => {
        const label = model.label.toLowerCase();
        const value = model.id.toLowerCase();
        return label.includes(normalizedProviderTestQuery) || value.includes(normalizedProviderTestQuery);
      })
    : activeTestableModels;
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
    setSelectedModelId('');
    setProviderTestMenuOpen(false);
    setProviderTestQuery('');
    setShowApiKey(false);
  }, [activeProviderId]);

  useEffect(() => {
    if (!providerTestMenuOpen && providerTestQuery) {
      setProviderTestQuery('');
    }
  }, [providerTestMenuOpen, providerTestQuery]);

  useEffect(() => {
    if (!activeWorkbenchModels.length) {
      if (selectedModelId) {
        setSelectedModelId('');
      }
      return;
    }

    if (!activeWorkbenchModels.some((model) => model.id === selectedModelId)) {
      setSelectedModelId(activeWorkbenchModels[0].id);
    }
  }, [activeWorkbenchModels, selectedModelId]);

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
    if (!providerTestMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!providerTestMenuRef.current?.contains(event.target as Node)) {
        setProviderTestMenuOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setProviderTestMenuOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [providerTestMenuOpen]);

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
        <div
          data-testid="llm-provider-list-pane"
          className={cn(
            'min-h-0 space-y-1.5 overflow-y-auto rounded-[24px] bg-background/55 p-2 sm:p-3',
            isSettingsSurface &&
              'flex min-h-0 flex-col border-r border-[hsl(var(--settings-subnav-border)/0.72)] bg-transparent p-0 pr-5'
          )}
        >
          <div className={cn('space-y-1.5', isSettingsSurface && 'flex-1 space-y-1 overflow-y-auto pr-1')}>
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
                  aria-current={providerId === activeProviderId ? 'page' : undefined}
                  className={cn(
                    'relative flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left transition ring-1 ring-inset focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                    providerId === activeProviderId
                      ? 'bg-primary/15 text-foreground ring-primary/70'
                      : 'text-muted-foreground ring-transparent hover:bg-background/70 hover:text-foreground hover:ring-border/50',
                    isSettingsSurface &&
                      (providerId === activeProviderId
                        ? 'rounded-md bg-[hsl(var(--settings-nav-active)/0.56)] ring-0 shadow-none'
                        : 'rounded-md bg-transparent ring-0 shadow-none hover:bg-[hsl(var(--settings-shell-elevated)/0.4)]')
                  )}
                >
                  {isSettingsSurface && providerId === activeProviderId ? (
                    <span
                      aria-hidden="true"
                      className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-[hsl(var(--settings-nav-active-foreground)/0.65)]"
                    />
                  ) : null}
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
                      className={cn(
                        'h-2.5 w-2.5 rounded-full',
                        providerId === activeProviderId
                          ? provider.enabled
                            ? 'bg-[hsl(var(--settings-nav-active-foreground)/0.9)]'
                            : 'bg-[hsl(var(--settings-nav-foreground)/0.45)]'
                          : provider.enabled
                            ? 'bg-emerald-500'
                            : 'bg-border'
                      )}
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
            <div className="mt-4 border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-4 pr-1">
              <button
                type="button"
                onClick={onAddCustomProvider}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-[hsl(var(--settings-subnav-border)/0.9)] bg-transparent px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-[hsl(var(--settings-shell-elevated)/0.4)]"
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
                    <div className="relative" ref={providerTestMenuRef}>
                      <button
                        type="button"
                        aria-haspopup="dialog"
                        aria-expanded={providerTestMenuOpen}
                        aria-controls={providerTestMenuOpen ? `provider-test-menu-${activeProviderId}` : undefined}
                        onClick={() => {
                          if (activeTestState.loading || !activeTestableModels.length) {
                            return;
                          }
                          setProviderTestMenuOpen((current) => !current);
                        }}
                        disabled={activeTestState.loading || !activeTestableModels.length}
                        className="inline-flex min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-md bg-[hsl(var(--settings-shell-elevated)/0.58)] px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-[hsl(var(--settings-shell-elevated)/0.82)] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {activeTestState.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                        <span>
                          {activeTestState.loading
                            ? t('llm.actions.testingConnection')
                            : t('llm.actions.testConnection')}
                        </span>
                        {!activeTestState.loading ? <ChevronDown className="h-4 w-4 opacity-65" /> : null}
                      </button>

                      {providerTestMenuOpen ? (
                        <div
                          id={`provider-test-menu-${activeProviderId}`}
                          data-testid="llm-provider-test-model-menu"
                          className="absolute right-0 top-full z-20 mt-2 w-[min(320px,calc(100vw-2rem))] overflow-hidden rounded-[20px] border border-border/70 bg-background shadow-[0_18px_42px_rgba(15,23,42,0.16)]"
                        >
                          <div className="border-b border-border/60 px-3 py-3">
                            <label className="relative block">
                              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                              <input
                                aria-label={t('llm.providerConfiguration.testModelLabel')}
                                autoFocus
                                value={providerTestQuery}
                                onChange={(event) => setProviderTestQuery(event.target.value)}
                                placeholder={t('llm.providerConfiguration.testModelSearchPlaceholder')}
                                className="h-11 w-full rounded-xl bg-background px-10 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
                              />
                            </label>
                          </div>

                          <div className="max-h-80 overflow-y-auto px-2 py-2">
                            {filteredActiveTestableModels.length ? (
                              filteredActiveTestableModels.map((model) => {
                                const isSelected = model.id === resolvedActiveTestModel;
                                return (
                                  <button
                                    key={model.id}
                                    type="button"
                                    onClick={() => {
                                      setProviderTestModels((prev) => ({
                                        ...prev,
                                        [activeProviderId]: model.id,
                                      }));
                                      setProviderTestMenuOpen(false);
                                      setProviderTestQuery('');
                                      onTestProviderConnection(activeProviderId, model.id);
                                    }}
                                    className={cn(
                                      'flex w-full items-center justify-between rounded-2xl px-3 py-3 text-left text-base text-foreground transition',
                                      isSelected
                                        ? 'bg-muted/80 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.18)]'
                                        : 'hover:bg-muted/50'
                                    )}
                                  >
                                    <span className="truncate">{model.label}</span>
                                    <span className="ml-3 shrink-0 text-xs text-muted-foreground">{model.id}</span>
                                  </button>
                                );
                              })
                            ) : (
                              <div className="px-3 py-4 text-sm text-muted-foreground">
                                {t('llm.fields.noSearchResults')}
                              </div>
                            )}
                          </div>
                        </div>
                      ) : null}
                    </div>
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

                <div
                  className={cn(
                    'space-y-4 pt-1',
                    isSettingsSurface && 'border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-5'
                  )}
                >
                  <div className="text-sm font-medium text-foreground">{t('llm.providerConfiguration.availableModels')}</div>

                  <div className="flex flex-col gap-3">
                    <div
                      role="tablist"
                      aria-label={t('llm.fields.modelKind')}
                      className="inline-flex w-fit items-center gap-1 rounded-lg bg-muted/55 p-1"
                    >
                      {([
                        ['chat', t('llm.modelKinds.chat')],
                        ['embedding', t('llm.modelKinds.embedding')],
                      ] as const).map(([kindValue, kindLabel]) => (
                        <button
                          key={kindValue}
                          type="button"
                          role="tab"
                          aria-selected={modelDraftKind === kindValue}
                          onClick={() => setModelDraftKind(kindValue)}
                          className={cn(
                            'inline-flex h-8 items-center justify-center rounded-md px-3 text-xs font-medium transition',
                            modelDraftKind === kindValue
                              ? 'bg-background text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.06)]'
                              : 'text-muted-foreground hover:text-foreground'
                          )}
                        >
                          {kindLabel}
                        </button>
                      ))}
                    </div>

                    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                      <label className="flex-1 space-y-2">
                        <span className="text-sm font-medium">{t('llm.fields.modelManualEntry')}</span>
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
                      {activeProvider.provider_type === 'custom' ? (
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
                      {activeWorkbenchModels.length ? (
                        activeWorkbenchModels.map((model) => (
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
                        const activeKind: 'chat' | 'embedding' =
                          activeWorkbenchModel.kinds.includes('embedding') &&
                          !activeWorkbenchModel.kinds.includes('chat')
                            ? 'embedding'
                            : 'chat';
                        const dimensionsValue =
                          activeModelOverride?.dimensions ?? activeWorkbenchModel.dimensions;
                        const dimensionsText = (dimensionsValue || []).join(', ');
                        const parseDimensions = (raw: string): number[] | undefined => {
                          const trimmed = raw.trim();
                          if (!trimmed) {
                            return undefined;
                          }
                          const parts = trimmed
                            .split(/[\s,]+/)
                            .map((part) => part.trim())
                            .filter(Boolean)
                            .map((part) => Number(part))
                            .filter((value) => Number.isFinite(value) && value > 0)
                            .map((value) => Math.floor(value));
                          return parts.length ? parts : undefined;
                        };

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
                                    ['image_output', t('llm.modelFields.imageOutput')],
                                  ] as const).map(([field, label]) => {
                                    const checked = Boolean(
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
                            ) : (
                              <div className={cn('grid gap-4', !isSettingsSurface && 'lg:grid-cols-2')}>
                                <label className="space-y-2">
                                  <span className="text-sm font-medium">{t('llm.modelFields.dimensions')}</span>
                                  <input
                                    aria-label={t('llm.modelFields.dimensions')}
                                    className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                                    placeholder={t('llm.modelFields.dimensionsPlaceholder')}
                                    defaultValue={dimensionsText}
                                    key={`${activeWorkbenchModel.id}-${dimensionsText}`}
                                    onBlur={(event) =>
                                      updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                        // Preserve embedding kind for manual models when persisting overrides.
                                        if (activeKind === 'embedding') {
                                          draft.capabilities = {
                                            ...(draft.capabilities || {}),
                                            embedding: true,
                                          };
                                        }
                                        draft.dimensions = parseDimensions(event.target.value);
                                      })
                                    }
                                  />
                                  <span className="block text-xs text-muted-foreground">
                                    {t('llm.modelFields.dimensionsHint')}
                                  </span>
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
