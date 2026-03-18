import React, { useContext, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  configApi,
  DEFAULT_LLM_CAPABILITIES,
  DEFAULT_LLM_LIMITS,
  type DiscoverLLMProviderModelsResponse,
  type LLMCapabilities,
  type LLMConfig,
  type LLMLimits,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type LLMSelectionConfig,
  type TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

import { FormContext } from '../onboarding/simple-form';
import { LLMModelSelectionSection } from './LLMModelSelectionSection';
import { LLMProviderConfigurationSection } from './LLMProviderConfigurationSection';

interface LLMFormProps {
  quickMode?: boolean;
  view?: 'all' | 'providers' | 'models';
  value?: LLMConfig;
  onChange?: (nextValue: LLMConfig) => void;
  showAdvancedByDefault?: boolean;
  surface?: 'onboarding' | 'settings';
  showSectionIntro?: boolean;
}

const BUILTIN_SCENARIOS: LLMScenario[] = ['context_decider', 'core', 'embedding'];

interface PendingEmbeddingDimensionChange {
  scenario: LLMScenario;
  previousDimension: number | null;
  nextDimension: number | null;
}

const cloneCapabilities = (value?: Partial<LLMCapabilities>): LLMCapabilities => ({
  ...DEFAULT_LLM_CAPABILITIES,
  ...(value || {}),
});

const cloneLimits = (value?: Partial<LLMLimits>): LLMLimits => ({
  ...DEFAULT_LLM_LIMITS,
  ...(value || {}),
});

const cloneProvider = (value?: Partial<LLMProviderConfig>): LLMProviderConfig => ({
  enabled: Boolean(value?.enabled),
  provider_type: value?.provider_type || 'openai',
  display_name: value?.display_name || '',
  api_key: value?.api_key || '',
  base_url: value?.base_url || '',
  api_format: value?.api_format,
  custom_models: [...(value?.custom_models || [])],
  custom_default_model: value?.custom_default_model || '',
});

const cloneSelection = (value?: Partial<LLMSelectionConfig>): LLMSelectionConfig => ({
  provider_id: value?.provider_id || '',
  model: value?.model || '',
  embedding_dimension: value?.embedding_dimension ?? null,
  capability_override_enabled: Boolean(value?.capability_override_enabled),
  capabilities: cloneCapabilities(value?.capabilities),
  limits: cloneLimits(value?.limits),
  provider_options: { ...(value?.provider_options || {}) },
});

const cloneLLMConfig = (value?: LLMConfig): LLMConfig => ({
  providers: Object.fromEntries(
    Object.entries(value?.providers || {}).map(([providerId, provider]) => [providerId, cloneProvider(provider)])
  ),
  selections: {
    context_decider: cloneSelection(value?.selections?.context_decider),
    core: cloneSelection(value?.selections?.core),
    embedding: cloneSelection(value?.selections?.embedding),
  },
});

const llmSignature = (value: LLMConfig): string => JSON.stringify(value);

const getProviderMeta = (registry: LLMProviderRegistry, providerId?: string) =>
  registry.providers.find((provider) => provider.id === providerId);

const getProviderModels = (registry: LLMProviderRegistry, providerId?: string) =>
  getProviderMeta(registry, providerId)?.chat_models || [];

const getProviderEmbeddingModels = (registry: LLMProviderRegistry, providerId?: string) =>
  getProviderMeta(registry, providerId)?.embedding_models || [];

const getCustomProviderModels = (provider?: LLMProviderConfig): string[] => provider?.custom_models || [];

const resolveProviderActionBaseUrl = (
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig | undefined
): string => {
  const configured = (provider?.base_url || '').trim();
  if (configured) {
    return configured;
  }
  return getProviderMeta(registry, providerId)?.default_base_url || '';
};

const resolveProviderDefaultModel = (
  registry: LLMProviderRegistry,
  provider: LLMProviderConfig | undefined,
  scenario: LLMScenario
): string => {
  if (!provider) {
    return '';
  }
  if (provider.provider_type === 'custom') {
    return provider.custom_default_model || getCustomProviderModels(provider)[0] || '';
  }
  const providerMeta = getProviderMeta(registry, provider.provider_type);
  if (!providerMeta) {
    return '';
  }
  if (scenario === 'embedding') {
    return providerMeta.embedding_models?.[0]?.id || '';
  }
  if (scenario === 'context_decider') {
    return (
      providerMeta.default_classify_model ||
      providerMeta.default_model ||
      providerMeta.chat_models?.[0]?.id ||
      ''
    );
  }
  return providerMeta.default_model || providerMeta.chat_models?.[0]?.id || '';
};

const applySelectionDefaults = (
  selection: LLMSelectionConfig,
  registry: LLMProviderRegistry,
  provider: LLMProviderConfig | undefined,
  scenario?: LLMScenario
) => {
  if (!provider) {
    return;
  }

  // For embedding scenario, only set defaults if provider has embedding models
  if (scenario === 'embedding') {
    const embeddingModels =
      provider.provider_type === 'custom'
        ? []
        : getProviderEmbeddingModels(registry, provider.provider_type);
    if (embeddingModels.length === 0) {
      // No embedding models available, don't set any defaults
      selection.provider_id = '';
      selection.model = '';
      selection.embedding_dimension = null;
      return;
    }

    const preferredModelId =
      selection.model || resolveProviderDefaultModel(registry, provider, scenario);
    // Find matching embedding model or use first available
    const matchedModel = embeddingModels.find((model) => model.id === preferredModelId);
    const fallbackModel = matchedModel || embeddingModels[0];
    if (fallbackModel) {
      selection.model = fallbackModel.id;
      if (!fallbackModel.dimensions.includes(selection.embedding_dimension || -1)) {
        selection.embedding_dimension = fallbackModel.dimensions[0] ?? null;
      }
      if (!selection.capability_override_enabled) {
        selection.capabilities = cloneCapabilities({
          vision: false,
          image_output: false,
          tool_calling: false,
          reasoning: false,
          embedding: true,
        });
        selection.limits = cloneLimits(selection.limits);
        selection.provider_options = { ...(fallbackModel.provider_options_example || {}) };
      }
    }
    return;
  }

  if (provider.provider_type === 'custom') {
    const fallbackModel = selection.model || resolveProviderDefaultModel(registry, provider, scenario || 'core');
    selection.model = fallbackModel;
    if (!selection.capability_override_enabled) {
      selection.capabilities = cloneCapabilities(registry.custom_provider.capabilities);
      selection.limits = cloneLimits(registry.custom_provider.limits);
      selection.provider_options = { ...(registry.custom_provider.provider_options_example || {}) };
    }
    return;
  }

  const models = getProviderModels(registry, provider.provider_type);
  const preferredModelId =
    selection.model || resolveProviderDefaultModel(registry, provider, scenario || 'core');
  const matchedModel = models.find((model) => model.id === preferredModelId);
  const fallbackModel = matchedModel || models[0];
  if (fallbackModel) {
    selection.model = fallbackModel.id;
    selection.embedding_dimension = null;
    if (!selection.capability_override_enabled) {
      selection.capabilities = cloneCapabilities({
        vision: fallbackModel.capabilities.vision,
        image_output: fallbackModel.capabilities.image_output,
        tool_calling: fallbackModel.capabilities.tool_calling,
        reasoning: fallbackModel.capabilities.reasoning,
        embedding: false,
      });
      selection.limits = cloneLimits(fallbackModel.limits);
      selection.provider_options = { ...(fallbackModel.provider_options_example || {}) };
    }
  }
};

const normalizeLLMConfig = (value: LLMConfig, registry: LLMProviderRegistry): LLMConfig => {
  const next = cloneLLMConfig(value);

  for (const providerMeta of registry.providers) {
    if (!next.providers[providerMeta.id]) {
      next.providers[providerMeta.id] = {
        enabled: false,
        provider_type: providerMeta.id as LLMProviderConfig['provider_type'],
        display_name: providerMeta.display_name || providerMeta.id,
        api_key: '',
        base_url: '',
      };
    } else {
      next.providers[providerMeta.id] = {
        ...cloneProvider(next.providers[providerMeta.id]),
        provider_type: providerMeta.id as LLMProviderConfig['provider_type'],
        display_name: next.providers[providerMeta.id].display_name || providerMeta.display_name || providerMeta.id,
      };
    }
  }

  const firstEnabledProviderId = Object.entries(next.providers).find(([, provider]) => provider.enabled)?.[0] || '';
  const firstEnabledEmbeddingProviderId =
    Object.entries(next.providers).find(([, provider]) => {
      if (!provider.enabled || provider.provider_type === 'custom') {
        return false;
      }
      const providerMeta = getProviderMeta(registry, provider.provider_type);
      return Boolean((providerMeta?.embedding_models || []).length);
    })?.[0] || '';

  for (const scenario of BUILTIN_SCENARIOS) {
    const selection = cloneSelection(next.selections[scenario]);
    const hasEnabledSelection =
      Boolean(selection.provider_id) &&
      Boolean(next.providers[selection.provider_id]?.enabled);
    const hasEnabledEmbeddingSelection =
      scenario !== 'embedding'
        ? hasEnabledSelection
        : (hasEnabledSelection &&
            Boolean(
              getProviderEmbeddingModels(
                registry,
                next.providers[selection.provider_id]?.provider_type
              ).length
            ));

    const firstAvailableProviderId =
      scenario === 'embedding' ? firstEnabledEmbeddingProviderId : firstEnabledProviderId;

    if (!firstAvailableProviderId) {
      selection.provider_id = '';
      selection.model = '';
      selection.embedding_dimension = null;
      if (!selection.capability_override_enabled) {
        selection.capabilities = cloneCapabilities(
          scenario === 'embedding'
            ? {
                vision: false,
                image_output: false,
                tool_calling: false,
                reasoning: false,
                embedding: true,
              }
            : undefined
        );
        selection.limits = cloneLimits();
        selection.provider_options = {};
      }
      next.selections[scenario] = selection;
      continue;
    }

    const selectedProvider = hasEnabledEmbeddingSelection
      ? next.providers[selection.provider_id]
      : next.providers[firstAvailableProviderId];

    selection.provider_id = hasEnabledEmbeddingSelection
      ? selection.provider_id
      : firstAvailableProviderId;

    applySelectionDefaults(selection, registry, selectedProvider, scenario);
    next.selections[scenario] = selection;
  }

  return next;
};

const LLMForm: React.FC<LLMFormProps> = ({
  quickMode = false,
  view = 'all',
  value,
  onChange,
  surface = 'onboarding',
  showSectionIntro = true,
}) => {
  const { t } = useTranslation('onboarding');
  const formCtx = useContext(FormContext);
  const controlled = value !== undefined && typeof onChange === 'function';
  const [registry, setRegistry] = useState<LLMProviderRegistry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeProviderId, setActiveProviderId] = useState<string>('openai');
  const [providerDiscoveryState, setProviderDiscoveryState] = useState<Record<string, { loading: boolean; error: string | null }>>({});
  const [providerTestState, setProviderTestState] = useState<
    Record<string, { loading: boolean; error: string | null; result: TestLLMProviderConnectionResponse | null }>
  >({});
  const [pendingEmbeddingDimensionChange, setPendingEmbeddingDimensionChange] =
    useState<PendingEmbeddingDimensionChange | null>(null);

  const currentValue = useMemo(() => {
    if (controlled) {
      return cloneLLMConfig(value);
    }
    return cloneLLMConfig(formCtx?.values?.llm as LLMConfig | undefined);
  }, [controlled, formCtx?.values?.llm, value]);
  const fillAvailableHeight = surface === 'settings' && view === 'providers';

  const updateValue = (updater: (draft: LLMConfig) => void) => {
    const next = cloneLLMConfig(currentValue);
    updater(next);
    if (controlled) {
      onChange?.(next);
      return;
    }
    formCtx?.instance?.setFieldValue?.(['llm'], next);
  };

  useEffect(() => {
    const loadRegistry = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await configApi.getLLMProviders();
        if (response.data) {
          setRegistry(response.data);
        } else {
          setError(t('llm.loadFailed'));
        }
      } catch {
        setError(t('llm.loadFailed'));
      } finally {
        setLoading(false);
      }
    };

    void loadRegistry();
  }, [t]);

  useEffect(() => {
    if (!registry) {
      return;
    }
    const normalized = normalizeLLMConfig(currentValue, registry);
    if (llmSignature(normalized) !== llmSignature(currentValue)) {
      updateValue((draft) => Object.assign(draft, normalized));
    }
    if (!normalized.providers[activeProviderId]) {
      setActiveProviderId(Object.keys(normalized.providers)[0] || 'openai');
    }
  }, [activeProviderId, currentValue, registry]); // eslint-disable-line react-hooks/exhaustive-deps

  const scenarioReferences = useMemo(() => {
    return Object.entries(currentValue.selections).reduce<Record<string, LLMScenario[]>>((acc, [scenario, selection]) => {
      const providerId = selection.provider_id;
      if (!acc[providerId]) {
        acc[providerId] = [];
      }
      acc[providerId].push(scenario as LLMScenario);
      return acc;
    }, {});
  }, [currentValue.selections]);

  const handleScenarioProviderChange = (scenario: LLMScenario, providerId: string) => {
    if (!registry) {
      return;
    }
    updateValue((draft) => {
      const selection = cloneSelection(draft.selections[scenario]);
      selection.provider_id = providerId;
      const provider = draft.providers[providerId];
      selection.model = resolveProviderDefaultModel(registry, provider, scenario);
      applySelectionDefaults(selection, registry, provider, scenario);
      draft.selections[scenario] = selection;
    });
  };

  const handleScenarioModelChange = (scenario: LLMScenario, model: string) => {
    if (!registry) {
      return;
    }
    updateValue((draft) => {
      const selection = cloneSelection(draft.selections[scenario]);
      selection.model = model;
      applySelectionDefaults(selection, registry, draft.providers[selection.provider_id], scenario);
      draft.selections[scenario] = selection;
    });
  };

  const applyScenarioEmbeddingDimensionChange = (scenario: LLMScenario, dimension: number | null) => {
    updateValue((draft) => {
      const selection = cloneSelection(draft.selections[scenario]);
      selection.embedding_dimension = dimension;
      draft.selections[scenario] = selection;
    });
  };

  const handleScenarioEmbeddingDimensionChange = (
    scenario: LLMScenario,
    dimension: number | null,
    source: 'model-sync' | 'manual' = 'manual'
  ) => {
    const currentDimension = currentValue.selections[scenario]?.embedding_dimension ?? null;
    const shouldConfirm =
      surface === 'settings' &&
      scenario === 'embedding' &&
      source === 'manual' &&
      currentDimension !== null &&
      dimension !== null &&
      currentDimension !== dimension;

    if (shouldConfirm) {
      setPendingEmbeddingDimensionChange({
        scenario,
        previousDimension: currentDimension,
        nextDimension: dimension,
      });
      return;
    }

    applyScenarioEmbeddingDimensionChange(scenario, dimension);
  };

  const handleConfirmEmbeddingDimensionChange = () => {
    if (!pendingEmbeddingDimensionChange) {
      return;
    }
    applyScenarioEmbeddingDimensionChange(
      pendingEmbeddingDimensionChange.scenario,
      pendingEmbeddingDimensionChange.nextDimension
    );
    setPendingEmbeddingDimensionChange(null);
  };

  const handleProviderChange = (providerId: string, updater: (provider: LLMProviderConfig) => void) => {
    updateValue((draft) => {
      const provider = cloneProvider(draft.providers[providerId]);
      updater(provider);
      draft.providers[providerId] = provider;
    });
  };

  const handleAddCustomProvider = () => {
    const nextProviderId = `custom_${Date.now()}`;
    updateValue((draft) => {
      draft.providers[nextProviderId] = {
        enabled: true,
        provider_type: 'custom',
        display_name: t('llm.customProviderDefaultName'),
        api_key: '',
        base_url: '',
        api_format: 'openai',
        custom_models: [],
        custom_default_model: '',
      };
    });
    setActiveProviderId(nextProviderId);
  };

  const handleRemoveCustomProvider = (providerId: string) => {
    const provider = currentValue.providers[providerId];
    if (!provider || provider.provider_type !== 'custom') {
      return;
    }

    updateValue((draft) => {
      delete draft.providers[providerId];
    });
    setActiveProviderId('openai');
  };

  const handleAddProviderModel = (providerId: string, model: string) => {
    const trimmedModel = model.trim();
    if (!trimmedModel) {
      return;
    }
    updateValue((draft) => {
      const provider = cloneProvider(draft.providers[providerId]);
      const nextModels = Array.from(new Set([...(provider.custom_models || []), trimmedModel]));
      provider.custom_models = nextModels;
      if (!provider.custom_default_model) {
        provider.custom_default_model = trimmedModel;
      }
      draft.providers[providerId] = provider;
    });
  };

  const handleRemoveProviderModel = (providerId: string, model: string) => {
    updateValue((draft) => {
      const provider = cloneProvider(draft.providers[providerId]);
      const nextModels = (provider.custom_models || []).filter((item) => item !== model);
      provider.custom_models = nextModels;
      if (provider.custom_default_model === model) {
        provider.custom_default_model = nextModels[0] || '';
      }
      draft.providers[providerId] = provider;
    });
  };

  const handleProviderDefaultModelChange = (providerId: string, model: string) => {
    updateValue((draft) => {
      const provider = cloneProvider(draft.providers[providerId]);
      provider.custom_default_model = model;
      draft.providers[providerId] = provider;
    });
  };

  const handleDiscoverProviderModels = async (providerId: string) => {
    const provider = currentValue.providers[providerId];
    if (!provider || provider.provider_type !== 'custom') {
      return;
    }

    setProviderDiscoveryState((prev) => ({
      ...prev,
      [providerId]: { loading: true, error: null },
    }));

    try {
      const response = await configApi.discoverLLMProviderModels({
        provider_type: provider.provider_type,
        base_url: provider.base_url || '',
        api_key: provider.api_key,
        api_format: provider.api_format,
      });
      const payload = response.data as DiscoverLLMProviderModelsResponse | undefined;
      const nextModels = payload?.models || [];

      updateValue((draft) => {
        const draftProvider = cloneProvider(draft.providers[providerId]);
        draftProvider.custom_models = nextModels;
        draftProvider.custom_default_model = payload?.default_model || nextModels[0] || draftProvider.custom_default_model || '';
        draft.providers[providerId] = draftProvider;
      });

      setProviderDiscoveryState((prev) => ({
        ...prev,
        [providerId]: { loading: false, error: null },
      }));
    } catch {
      setProviderDiscoveryState((prev) => ({
        ...prev,
        [providerId]: { loading: false, error: t('llm.providerConfiguration.fetchModelsFailed') },
      }));
    }
  };

  const resolveProviderProbeModel = (providerId: string): string => {
    if (!registry) {
      return '';
    }

    const referencedSelection = BUILTIN_SCENARIOS
      .map((scenario) => currentValue.selections[scenario])
      .find((selection) => selection.provider_id === providerId && selection.model);

    if (referencedSelection?.model) {
      return referencedSelection.model;
    }

    return resolveProviderDefaultModel(registry, currentValue.providers[providerId], 'core');
  };

  const handleTestProviderConnection = async (providerId: string) => {
    if (!registry) {
      return;
    }

    const provider = currentValue.providers[providerId];
    if (!provider) {
      return;
    }

    const model = resolveProviderProbeModel(providerId);
    if (!model) {
      setProviderTestState((prev) => ({
        ...prev,
        [providerId]: {
          loading: false,
          error: t('llm.providerConfiguration.testModelRequired'),
          result: null,
        },
      }));
      return;
    }

    setProviderTestState((prev) => ({
      ...prev,
      [providerId]: { loading: true, error: null, result: null },
    }));

    try {
      const effectiveProvider = {
        ...provider,
        base_url: resolveProviderActionBaseUrl(registry, providerId, provider),
      };
      const response = await configApi.testLLMProviderConnection({
        provider_id: providerId,
        provider: effectiveProvider,
        model,
      });

      setProviderTestState((prev) => ({
        ...prev,
        [providerId]: {
          loading: false,
          error: null,
          result: response.data || null,
        },
      }));
    } catch (error: any) {
      setProviderTestState((prev) => ({
        ...prev,
        [providerId]: {
          loading: false,
          error: error?.message || t('llm.providerConfiguration.testFailed'),
          result: null,
        },
      }));
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[220px] items-center justify-center rounded-2xl border border-dashed border-border bg-muted/20">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        <span className="text-sm text-muted-foreground">{t('llm.loading')}</span>
      </div>
    );
  }

  if (!registry || error) {
    return (
      <div className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <p className="font-medium">{t('llm.loadFailed')}</p>
        <p className="mt-1 text-destructive/80">{t('llm.loadFailedDesc')}</p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'space-y-6',
        quickMode && 'space-y-5',
        fillAvailableHeight && 'flex h-full min-h-0 flex-col'
      )}
    >
      {view !== 'models' ? (
        <LLMProviderConfigurationSection
          registry={registry}
          value={currentValue}
          activeProviderId={activeProviderId}
          quickMode={quickMode}
          surface={surface}
          showSectionIntro={showSectionIntro}
          scenarioReferences={scenarioReferences}
          onActiveProviderChange={setActiveProviderId}
          onProviderChange={handleProviderChange}
          onAddCustomProvider={handleAddCustomProvider}
          onRemoveCustomProvider={handleRemoveCustomProvider}
          onAddProviderModel={handleAddProviderModel}
          onRemoveProviderModel={handleRemoveProviderModel}
          onProviderDefaultModelChange={handleProviderDefaultModelChange}
          onDiscoverProviderModels={handleDiscoverProviderModels}
          providerDiscoveryState={providerDiscoveryState}
          onTestProviderConnection={handleTestProviderConnection}
          providerTestState={providerTestState}
        />
      ) : null}

      {view !== 'providers' ? (
        <LLMModelSelectionSection
          registry={registry}
          value={currentValue}
          quickMode={quickMode}
          surface={surface}
          showSectionIntro={showSectionIntro}
          onScenarioProviderChange={handleScenarioProviderChange}
          onScenarioModelChange={handleScenarioModelChange}
          onScenarioEmbeddingDimensionChange={handleScenarioEmbeddingDimensionChange}
        />
      ) : null}

      <Dialog
        open={Boolean(pendingEmbeddingDimensionChange)}
        onOpenChange={(open) => {
          if (!open) {
            setPendingEmbeddingDimensionChange(null);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              {t('llm.embeddingDimensionConfirm.title')}
            </DialogTitle>
            <DialogDescription>
              {t('llm.embeddingDimensionConfirm.description', {
                current: pendingEmbeddingDimensionChange?.previousDimension ?? '',
                next: pendingEmbeddingDimensionChange?.nextDimension ?? '',
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="px-6 pb-2">
            <div className="rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm leading-6 text-muted-foreground">
              {t('llm.embeddingDimensionConfirm.warning')}
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setPendingEmbeddingDimensionChange(null)}>
              {t('llm.embeddingDimensionConfirm.cancel')}
            </Button>
            <Button type="button" variant="destructive" onClick={handleConfirmEmbeddingDimensionChange}>
              {t('llm.embeddingDimensionConfirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default LLMForm;
