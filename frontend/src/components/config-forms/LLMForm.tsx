import React, { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
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
  isProviderAllowedForScenario,
  llmSignature,
  normalizeLLMConfig,
  resolveProviderActionBaseUrl,
  resolveProviderDefaultModel,
  resolveSelectionDefaultMaxConcurrency,
  validateLLMCustomProviderReadiness,
  type LLMValidationIssue,
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
  onValidationChange?: (issues: LLMValidationIssue[]) => void;
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
    auxiliary: cloneSelection(left),
    core: cloneSelection(right),
    memory_summarizer: cloneSelection(right),
    embedding: cloneSelection(),
    image_generation: cloneSelection(),
  },
  model_runtime_overrides: {},
}) === llmSignature({
  providers: {},
  selections: {
    auxiliary: cloneSelection(right),
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
  onValidationChange,
}) => {
  const { t } = useTranslation('onboarding');
  const formCtx = useContext(FormContext);
  const controlled = value !== undefined && typeof onChange === 'function';
  const [registry, setRegistry] = useState<LLMProviderRegistry | null>(null);
  const [customProviderTemplate, setCustomProviderTemplate] = useState<LLMCustomProviderTemplateData | null>(null);
  const [customProviderDefaults, setCustomProviderDefaults] = useState<LLMProviderConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeProviderId, setActiveProviderId] = useState<string>('');
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
  const memorySummarizerCanUseCore = Boolean(
    registry &&
    isProviderAllowedForScenario(
      registry,
      currentValue.providers[currentValue.selections.core?.provider_id],
      'memory_summarizer'
    )
  );
  const memorySummarizerUsesCore = memorySummarizerCanUseCore && (
    memorySummarizerUsesCoreOverride
    ?? areSelectionsEquivalent(currentValue.selections.memory_summarizer, currentValue.selections.core)
  );
  const validationIssues = useMemo(() => validateLLMCustomProviderReadiness(currentValue), [currentValue]);

  const formatValidationIssue = useCallback((issue: LLMValidationIssue): string => {
    const serviceLabel = t(`llm.providerConfiguration.serviceLabels.${issue.serviceName}`);
    if (issue.code === 'customScenarioModelMissing' && issue.scenario && issue.model) {
      return t('llm.validation.customScenarioModelMissing', {
        provider: issue.providerName,
        scenario: t(`llm.scenarios.${issue.scenario}.title`),
        model: issue.model,
        service: serviceLabel,
      });
    }
    return t('llm.validation.customServiceModelRequired', {
      provider: issue.providerName,
      service: serviceLabel,
    });
  }, [t]);

  useEffect(() => {
    onValidationChange?.(validationIssues);
  }, [onValidationChange, validationIssues]);

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
          setCustomProviderDefaults(template.defaults ? cloneProvider(template.defaults) : null);
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
      setActiveProviderId(Object.keys(normalized.providers)[0] || '');
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
        auxiliary: {
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
    if (checked && !memorySummarizerCanUseCore) {
      return;
    }
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

  const handleSetProvider = (providerId: string, provider: LLMProviderConfig) => {
    updateValue((draft) => {
      draft.providers[providerId] = cloneProvider(provider);
    });
    setActiveProviderId(providerId);
  };

  const clearSelectionReferences = (draft: LLMConfig, providerId: string) => {
    for (const scenario of BUILTIN_SCENARIOS) {
      if (draft.selections[scenario]?.provider_id === providerId) {
        draft.selections[scenario] = cloneSelection();
      }
    }
  };

  const handleRemoveProvider = (providerId: string) => {
    updateValue((draft) => {
      delete draft.providers[providerId];
      clearSelectionReferences(draft, providerId);
    });
    setActiveProviderId((current) => (current === providerId ? '' : current));
  };

  const handleAddProviderModel = (providerId: string, model: string, kind: 'chat' | 'embedding' = 'chat') => {
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
          delete nextCapabilities.image_output;
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

  const handleDiscoverProviderModels = async (providerId: string, providerOverride?: LLMProviderConfig) => {
    if (!registry) {
      return undefined;
    }

    const provider = providerOverride || currentValue.providers[providerId];
    if (!provider) {
      return undefined;
    }

    setProviderDiscoveryState((prev) => ({
      ...prev,
      [providerId]: { loading: true, error: null },
    }));

    try {
      const payload = await configApi.discoverLLMProviderModels({
        provider_type: provider.provider_type,
        base_url: provider.services.chat.base_url || provider.base_url || resolveProviderActionBaseUrl(registry, providerId, provider),
        api_key: provider.services.chat.api_key || provider.api_key,
        api_format: provider.api_format,
      });
      const nextModels = payload?.models || [];

      if (!providerOverride) {
        updateValue((draft) => {
          const draftProvider = cloneProvider(draft.providers[providerId]);
          draftProvider.custom_models = nextModels;
          draftProvider.custom_default_model = payload?.default_model || nextModels[0] || draftProvider.custom_default_model || '';
          draft.providers[providerId] = draftProvider;
        });
      }

      setProviderDiscoveryState((prev) => ({
        ...prev,
        [providerId]: { loading: false, error: null },
      }));
      return nextModels;
    } catch {
      setProviderDiscoveryState((prev) => ({
        ...prev,
        [providerId]: { loading: false, error: t('llm.providerConfiguration.fetchModelsFailed') },
      }));
      return undefined;
    }
  };

  const handleResolveDraftProviderPreview = useCallback(
    async (providerId: string, provider: LLMProviderConfig): Promise<LLMProviderRegistry | null> => {
      if (!customProviderTemplate || !registry) {
        return null;
      }

      const catalog = await configApi.resolveLLMProviderCatalog({
        providers: {
          ...currentValue.providers,
          [providerId]: cloneProvider(provider),
        },
      });

      if (!catalog) {
        return null;
      }

      return buildRegistryFromCatalog(catalog, customProviderTemplate);
    },
    [currentValue.providers, customProviderTemplate, registry]
  );

  const handleTestProviderConnection = async (providerId: string, model: string, providerOverride?: LLMProviderConfig) => {
    if (!registry) {
      return;
    }

    const provider = providerOverride || currentValue.providers[providerId];
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
      const effectiveProvider = cloneProvider(provider);
      effectiveProvider.base_url = resolveProviderActionBaseUrl(registry, providerId, provider);
      effectiveProvider.services.chat.api_key = provider.services.chat.api_key || provider.api_key || '';
      effectiveProvider.services.chat.base_url = provider.services.chat.base_url || effectiveProvider.base_url || '';
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
      {validationIssues.length > 0 ? (
        <div className="space-y-1 rounded-lg border border-amber-300/55 bg-amber-50/75 px-3 py-2.5 text-xs leading-5 text-amber-900 dark:border-amber-300/25 dark:bg-amber-500/10 dark:text-amber-100">
          {validationIssues.slice(0, 3).map((issue, index) => (
            <p key={`${issue.code}-${issue.providerId}-${issue.serviceName}-${index}`} className="flex gap-2">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{formatValidationIssue(issue)}</span>
            </p>
          ))}
        </div>
      ) : null}

      {view !== 'models' ? (
        <LLMProviderConfigurationSection
          registry={registry}
          value={currentValue}
          activeProviderId={activeProviderId}
          quickMode={quickMode}
          surface={surface}
          showSectionIntro={showSectionIntro}
          scenarioReferences={scenarioReferences}
          customProviderDefaults={customProviderDefaults}
          onActiveProviderChange={setActiveProviderId}
          onProviderChange={handleProviderChange}
          onSetProvider={handleSetProvider}
          onRemoveProvider={handleRemoveProvider}
          onAddProviderModel={handleAddProviderModel}
          onRemoveProviderModel={handleRemoveProviderModel}
          onProviderDefaultModelChange={handleProviderDefaultModelChange}
          onDiscoverProviderModels={handleDiscoverProviderModels}
          onResolveDraftProviderPreview={handleResolveDraftProviderPreview}
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
          memorySummarizerCanUseCore={memorySummarizerCanUseCore}
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
