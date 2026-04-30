import React, { useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  configApi,
  type LLMConfig,
  type LLMCustomProviderTemplateData,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
import { cn } from '@/lib/utils';

import { FormContext } from '../onboarding/simple-form';
import {
  applySelectionDefaults,
  buildRegistryFromCatalog,
  buildRuntimeOverrideKey,
  BUILTIN_SCENARIOS,
  cloneLLMConfig,
  cloneProvider,
  cloneSelection,
  llmSignature,
  normalizeLLMConfig,
  resolveProviderActionBaseUrl,
  resolveProviderDefaultModel,
  resolveSelectionDefaultMaxConcurrency,
  type ScenarioConcurrencyState,
} from './llm-form-state';
import { LLMEmbeddingDimensionConfirmDialog } from './LLMEmbeddingDimensionConfirmDialog';
import { LLMModelSelectionSection } from './LLMModelSelectionSection';
import { LLMProviderConfigurationSection } from './LLMProviderConfigurationSection';

interface LLMFormProps {
  quickMode?: boolean;
  view?: 'all' | 'providers' | 'models';
  value?: LLMConfig;
  onChange?: (nextValue: LLMConfig) => void;
  onAutoNormalize?: (nextValue: LLMConfig) => void;
  showAdvancedByDefault?: boolean;
  surface?: 'onboarding' | 'settings';
  showSectionIntro?: boolean;
  embeddingConfig?: import('@/api/modules/config').EmbeddingConfig;
  onEmbeddingConfigChange?: (updater: (draft: import('@/api/modules/config').EmbeddingConfig) => void) => void;
  crossEncoderConfig?: import('@/api/modules/config').CrossEncoderConfig;
  onCrossEncoderConfigChange?: (updater: (draft: import('@/api/modules/config').CrossEncoderConfig) => void) => void;
}

interface PendingEmbeddingDimensionChange {
  scenario: LLMScenario;
  previousDimension: number | null;
  nextDimension: number | null;
}

const areSelectionsEquivalent = (
  left?: import('@/api/modules/config').LLMSelectionConfig,
  right?: import('@/api/modules/config').LLMSelectionConfig
): boolean => llmSignature({
  providers: {},
  selections: {
    context_decider: cloneSelection(left),
    core: cloneSelection(right),
    memory_summarizer: cloneSelection(right),
    embedding: cloneSelection(),
    image_generation: cloneSelection(),
  },
  model_runtime_overrides: {},
}) === llmSignature({
  providers: {},
  selections: {
    context_decider: cloneSelection(right),
    core: cloneSelection(left),
    memory_summarizer: cloneSelection(left),
    embedding: cloneSelection(),
    image_generation: cloneSelection(),
  },
  model_runtime_overrides: {},
});

const LLMForm: React.FC<LLMFormProps> = ({
  quickMode = false,
  view = 'all',
  value,
  onChange,
  onAutoNormalize,
  showAdvancedByDefault = false,
  surface = 'onboarding',
  showSectionIntro = true,
  embeddingConfig,
  onEmbeddingConfigChange,
  crossEncoderConfig,
  onCrossEncoderConfigChange,
}) => {
  const { t } = useTranslation('onboarding');
  const formCtx = useContext(FormContext);
  const controlled = value !== undefined && typeof onChange === 'function';
  const [registry, setRegistry] = useState<LLMProviderRegistry | null>(null);
  const [customProviderTemplate, setCustomProviderTemplate] = useState<LLMCustomProviderTemplateData | null>(null);
  const [customProviderDefaults, setCustomProviderDefaults] = useState<LLMProviderConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeProviderId, setActiveProviderId] = useState<string>('openai');
  const [providerDiscoveryState, setProviderDiscoveryState] = useState<Record<string, { loading: boolean; error: string | null }>>({});
  const [providerTestState, setProviderTestState] = useState<
    Record<string, { loading: boolean; error: string | null; result: TestLLMProviderConnectionResponse | null }>
  >({});
  const [memorySummarizerUsesCoreOverride, setMemorySummarizerUsesCoreOverride] = useState<boolean | null>(null);
  const [pendingEmbeddingDimensionChange, setPendingEmbeddingDimensionChange] =
    useState<PendingEmbeddingDimensionChange | null>(null);
  const pendingEmbeddingDialogTimerRef = useRef<number | null>(null);
  const registryPreviewRequestRef = useRef(0);

  const currentValue = useMemo(() => {
    if (controlled) {
      return cloneLLMConfig(value);
    }
    return cloneLLMConfig(formCtx?.values?.llm as LLMConfig | undefined);
  }, [controlled, formCtx?.values?.llm, value]);
  const initialProvidersRef = useRef(currentValue.providers);
  const fillAvailableHeight = view === 'providers';
  const memorySummarizerUsesCore =
    memorySummarizerUsesCoreOverride
    ?? areSelectionsEquivalent(currentValue.selections.memory_summarizer, currentValue.selections.core);

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
        const [catalog, template] = await Promise.all([
          configApi.resolveLLMProviderCatalog({
            providers: initialProvidersRef.current,
          }),
          configApi.getLLMCustomProviderTemplate(),
        ]);
        if (catalog && template) {
          setCustomProviderTemplate(template);
          setCustomProviderDefaults(cloneProvider(template.defaults));
          setRegistry(buildRegistryFromCatalog(catalog, template));
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
    if (!customProviderTemplate) {
      return;
    }

    const requestId = registryPreviewRequestRef.current + 1;
    registryPreviewRequestRef.current = requestId;
    const timeoutId = window.setTimeout(() => {
      void (async () => {
        try {
          const catalog = await configApi.resolveLLMProviderCatalog({
            providers: currentValue.providers,
          });
          if (registryPreviewRequestRef.current !== requestId || !catalog) {
            return;
          }
          setRegistry(buildRegistryFromCatalog(catalog, customProviderTemplate));
        } catch {
          // Preserve the last successful catalog snapshot while the user edits draft values.
        }
      })();
    }, 120);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [currentValue.providers, customProviderTemplate]);

  useEffect(() => {
    return () => {
      if (pendingEmbeddingDialogTimerRef.current !== null) {
        window.clearTimeout(pendingEmbeddingDialogTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!registry) {
      return;
    }
    const normalized = normalizeLLMConfig(currentValue, registry);
    if (llmSignature(normalized) !== llmSignature(currentValue)) {
      if (controlled && onAutoNormalize) {
        onAutoNormalize(normalized);
        return;
      }
      updateValue((draft) => Object.assign(draft, normalized));
    }
    if (!normalized.providers[activeProviderId]) {
      setActiveProviderId(Object.keys(normalized.providers)[0] || 'openai');
    }
  }, [activeProviderId, controlled, currentValue, onAutoNormalize, registry]);

  useEffect(() => {
    if (!memorySummarizerUsesCore) {
      return;
    }
    if (areSelectionsEquivalent(currentValue.selections.memory_summarizer, currentValue.selections.core)) {
      return;
    }
    updateValue((draft) => {
      draft.selections.memory_summarizer = cloneSelection(draft.selections.core);
    });
  }, [currentValue.selections.core, currentValue.selections.memory_summarizer, memorySummarizerUsesCore]);

  const scenarioReferences = useMemo(() => {
    return Object.entries(currentValue.selections).reduce<Record<string, LLMScenario[]>>((acc, [scenario, selection]) => {
      const providerId = selection?.provider_id;
      if (!providerId) return acc;
      if (!acc[providerId]) {
        acc[providerId] = [];
      }
      acc[providerId].push(scenario as LLMScenario);
      return acc;
    }, {});
  }, [currentValue.selections]);

  const scenarioConcurrency = useMemo<Record<LLMScenario, ScenarioConcurrencyState>>(() => {
    if (!registry) {
      return {
        context_decider: {
          runtimeKey: null,
          effectiveMaxConcurrency: null,
          overrideMaxConcurrency: null,
          defaultMaxConcurrency: null,
          sharedScenarios: [],
        },
        core: {
          runtimeKey: null,
          effectiveMaxConcurrency: null,
          overrideMaxConcurrency: null,
          defaultMaxConcurrency: null,
          sharedScenarios: [],
        },
        embedding: {
          runtimeKey: null,
          effectiveMaxConcurrency: null,
          overrideMaxConcurrency: null,
          defaultMaxConcurrency: null,
          sharedScenarios: [],
        },
        image_generation: {
          runtimeKey: null,
          effectiveMaxConcurrency: null,
          overrideMaxConcurrency: null,
          defaultMaxConcurrency: null,
          sharedScenarios: [],
        },
        memory_summarizer: {
          runtimeKey: null,
          effectiveMaxConcurrency: null,
          overrideMaxConcurrency: null,
          defaultMaxConcurrency: null,
          sharedScenarios: [],
        },
      };
    }

    const entries = BUILTIN_SCENARIOS.map((scenario) => {
      const selection = currentValue.selections[scenario];
      if (!selection?.provider_id) {
        return {
          scenario,
          runtimeKey: null,
          overrideMaxConcurrency: null,
          defaultMaxConcurrency: null,
        };
      }
      const provider = currentValue.providers[selection.provider_id];
      const runtimeKey = buildRuntimeOverrideKey({
        registry,
        providerId: selection.provider_id,
        provider,
        model: selection.model,
        scenario,
      });
      const overrideMaxConcurrency =
        runtimeKey ? currentValue.model_runtime_overrides?.[runtimeKey]?.max_concurrency ?? null : null;
      const defaultMaxConcurrency = resolveSelectionDefaultMaxConcurrency({
        registry,
        providerId: selection.provider_id,
        provider,
        model: selection.model,
        scenario,
      });
      return {
        scenario,
        runtimeKey,
        overrideMaxConcurrency,
        defaultMaxConcurrency,
      };
    });

    return Object.fromEntries(
      entries.map((entry) => [
        entry.scenario,
        {
          runtimeKey: entry.runtimeKey,
          overrideMaxConcurrency: entry.overrideMaxConcurrency,
          defaultMaxConcurrency: entry.defaultMaxConcurrency,
          effectiveMaxConcurrency: entry.overrideMaxConcurrency ?? entry.defaultMaxConcurrency,
          sharedScenarios: entries
            .filter((candidate) => candidate.scenario !== entry.scenario && candidate.runtimeKey === entry.runtimeKey)
            .map((candidate) => candidate.scenario),
        },
      ])
    ) as Record<LLMScenario, ScenarioConcurrencyState>;
  }, [
    currentValue.model_runtime_overrides,
    currentValue.providers,
    currentValue.selections,
    registry,
  ]);

  const handleScenarioProviderChange = (scenario: LLMScenario, providerId: string) => {
    if (!registry) {
      return;
    }
    updateValue((draft) => {
      const selection = cloneSelection(draft.selections[scenario]);
      selection.provider_id = providerId;
      const provider = draft.providers[providerId];
      selection.model = resolveProviderDefaultModel(registry, providerId, provider, scenario);
      applySelectionDefaults(selection, registry, providerId, provider, scenario);
      draft.selections[scenario] = selection;
      if (scenario === 'core' && memorySummarizerUsesCore) {
        draft.selections.memory_summarizer = cloneSelection(selection);
      }
    });
  };

  const handleScenarioModelChange = (scenario: LLMScenario, model: string) => {
    if (!registry) {
      return;
    }
    updateValue((draft) => {
      const selection = cloneSelection(draft.selections[scenario]);
      selection.model = model;
      applySelectionDefaults(
        selection,
        registry,
        selection.provider_id,
        draft.providers[selection.provider_id],
        scenario
      );
      draft.selections[scenario] = selection;
      if (scenario === 'core' && memorySummarizerUsesCore) {
        draft.selections.memory_summarizer = cloneSelection(selection);
      }
    });
  };

  const handleMemorySummarizerInheritanceChange = (checked: boolean) => {
    setMemorySummarizerUsesCoreOverride(checked);
    if (!checked) {
      return;
    }
    updateValue((draft) => {
      draft.selections.memory_summarizer = cloneSelection(draft.selections.core);
    });
  };

  const handleScenarioMaxConcurrencyChange = (scenario: LLMScenario, value: number | null) => {
    if (!registry) {
      return;
    }

    updateValue((draft) => {
      const selection = cloneSelection(draft.selections[scenario]);
      const provider = draft.providers[selection.provider_id];
      const runtimeKey = buildRuntimeOverrideKey({
        registry,
        providerId: selection.provider_id,
        provider,
        model: selection.model,
        scenario,
      });
      if (!runtimeKey) {
        return;
      }

      if (value === null || Number.isNaN(value)) {
        delete draft.model_runtime_overrides[runtimeKey];
        return;
      }

      draft.model_runtime_overrides[runtimeKey] = {
        max_concurrency: Math.max(1, Math.floor(value)),
      };
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
      if (pendingEmbeddingDialogTimerRef.current !== null) {
        window.clearTimeout(pendingEmbeddingDialogTimerRef.current);
      }
      pendingEmbeddingDialogTimerRef.current = window.setTimeout(() => {
        setPendingEmbeddingDimensionChange({
          scenario,
          previousDimension: currentDimension,
          nextDimension: dimension,
        });
        pendingEmbeddingDialogTimerRef.current = null;
      }, 0);
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
    const defaultProvider = customProviderDefaults
      ? cloneProvider(customProviderDefaults)
      : {
          enabled: true,
          provider_type: 'custom' as const,
          display_name: '',
          api_key: '',
          base_url: '',
          api_format: 'openai' as const,
          custom_models: [],
          custom_default_model: '',
          model_metadata_overrides: {},
        };
    updateValue((draft) => {
      draft.providers[nextProviderId] = {
        ...defaultProvider,
        display_name: defaultProvider.display_name || t('llm.customProviderDefaultName'),
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

  const handleAddProviderModel = (providerId: string, model: string, kind: 'chat' | 'embedding' | 'image' = 'chat') => {
    if (kind === 'image') {
      // Image generation models are predefined by the provider registry and not
      // user-extensible from the workbench yet, so ignore the request.
      return;
    }
    const trimmedModel = model.trim();
    if (!trimmedModel) {
      return;
    }
    updateValue((draft) => {
      const provider = cloneProvider(draft.providers[providerId]);
      if (kind === 'embedding') {
        // Manual embedding models live solely in the override map so the resolver routes
        // them to embedding_models without flagging the chat list.
        const overrides = { ...(provider.model_metadata_overrides || {}) };
        const existing = overrides[trimmedModel];
        const alreadyChat = (provider.custom_models || []).includes(trimmedModel);
        if (alreadyChat) {
          provider.custom_models = (provider.custom_models || []).filter((item) => item !== trimmedModel);
          if (provider.custom_default_model === trimmedModel) {
            provider.custom_default_model = (provider.custom_models || [])[0] || '';
          }
        }
        overrides[trimmedModel] = {
          ...(existing || {}),
          capabilities: { ...(existing?.capabilities || {}), embedding: true },
          limits: { ...(existing?.limits || {}) },
        };
        provider.model_metadata_overrides = overrides;
      } else {
        const nextModels = Array.from(new Set([...(provider.custom_models || []), trimmedModel]));
        provider.custom_models = nextModels;
        if (!provider.custom_default_model) {
          provider.custom_default_model = trimmedModel;
        }
        // Drop any embedding-kind override left over from a previous embedding-kind add.
        if (provider.model_metadata_overrides?.[trimmedModel]?.capabilities?.embedding === true) {
          const overrides = { ...(provider.model_metadata_overrides || {}) };
          const existing = overrides[trimmedModel];
          const nextCapabilities = { ...(existing?.capabilities || {}) };
          delete nextCapabilities.embedding;
          overrides[trimmedModel] = {
            ...(existing || {}),
            capabilities: nextCapabilities,
          };
          provider.model_metadata_overrides = overrides;
        }
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
      if (provider.model_metadata_overrides?.[model]) {
        const nextOverrides = { ...(provider.model_metadata_overrides || {}) };
        delete nextOverrides[model];
        provider.model_metadata_overrides = nextOverrides;
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
      const payload = await configApi.discoverLLMProviderModels({
        provider_type: provider.provider_type,
        base_url: provider.base_url || '',
        api_key: provider.api_key,
        api_format: provider.api_format,
      });
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

  const handleTestProviderConnection = async (providerId: string, model: string) => {
    if (!registry) {
      return;
    }

    const provider = currentValue.providers[providerId];
    if (!provider) {
      return;
    }

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
      const result = await configApi.testLLMProviderConnection({
        provider_id: providerId,
        provider: effectiveProvider,
        model,
      });

      setProviderTestState((prev) => ({
        ...prev,
        [providerId]: {
          loading: false,
          error: null,
          result: result || null,
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
          showAdvancedByDefault={showAdvancedByDefault}
          scenarioConcurrency={scenarioConcurrency}
          onScenarioProviderChange={handleScenarioProviderChange}
          onScenarioModelChange={handleScenarioModelChange}
          onScenarioEmbeddingDimensionChange={handleScenarioEmbeddingDimensionChange}
          onScenarioMaxConcurrencyChange={handleScenarioMaxConcurrencyChange}
          memorySummarizerUsesCore={memorySummarizerUsesCore}
          onMemorySummarizerInheritanceChange={handleMemorySummarizerInheritanceChange}
          embeddingConfig={embeddingConfig}
          onEmbeddingConfigChange={onEmbeddingConfigChange}
          crossEncoderConfig={crossEncoderConfig}
          onCrossEncoderConfigChange={onCrossEncoderConfigChange}
        />
      ) : null}

      <LLMEmbeddingDimensionConfirmDialog
        open={Boolean(pendingEmbeddingDimensionChange)}
        previousDimension={pendingEmbeddingDimensionChange?.previousDimension ?? null}
        nextDimension={pendingEmbeddingDimensionChange?.nextDimension ?? null}
        onCancel={() => setPendingEmbeddingDimensionChange(null)}
        onConfirm={handleConfirmEmbeddingDimensionChange}
      />
    </div>
  );
};

export default LLMForm;
