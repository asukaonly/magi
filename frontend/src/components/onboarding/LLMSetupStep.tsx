import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, ArrowLeft, ChevronDown, ChevronRight, Eye, EyeOff, Info, Loader2 } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useTranslation } from 'react-i18next';

import {
  configApi,
  type ApiFormat,
  type LLMConfig,
  type LLMCustomProviderTemplateData,
  type LLMProvider,
  type LLMProviderConfig,
  type LLMProviderMeta,
  type LLMProviderRegistry,
  type LLMScenario,
  type TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
import { SelectField } from '@/components/config-forms/fields';
import { LLMProviderTestStatus } from '@/components/config-forms/LLMProviderTestStatus';
import { ProviderIcon } from '@/components/config-forms/provider-icons';
import {
  applySelectionDefaults,
  buildRegistryFromCatalog,
  cloneLLMConfig,
  cloneProvider,
  cloneSelection,
  isProviderAllowedForScenario,
  resolveProviderDefaultModel,
} from '@/components/config-forms/llm-form-state';
import { cn } from '@/lib/utils';
import { getMemoryModelStatus } from './memoryModelStatus';
import {
  ONBOARDING_FIELD_CLASS,
  ONBOARDING_SELECTED_SURFACE_CLASS,
} from './onboardingStyles';

export interface LLMSetupStepProps {
  value: LLMConfig;
  onChange: (next: LLMConfig) => void;
  onValid?: (valid: boolean) => void;
  connectionTestState: LLMConnectionTestState;
  onTestConnection: (force?: boolean) => Promise<boolean>;
  onConnectionConfigPendingChange?: (pending: boolean) => void;
}

export interface LLMConnectionTestState {
  loading: boolean;
  error: string | null;
  result: TestLLMProviderConnectionResponse | null;
}

type QuickProviderCard = {
  id: string;
  providerType: LLMProvider | 'custom';
  title: string;
  iconName?: string;
  meta?: LLMProviderMeta;
};

const QUICK_PROVIDER_PRIORITY = [
  'openai',
  'anthropic',
  'gemini',
  'deepseek',
  'dashscope',
  'glm',
  'kimi',
  'grok',
  'minimax',
];

const fieldClassName =
  cn('h-10 w-full px-3 text-sm', ONBOARDING_FIELD_CLASS);

const secretFieldButtonClassName =
  'absolute inset-y-0 right-2 inline-flex items-center justify-center text-muted-foreground transition hover:text-foreground';

const PROVIDER_TRANSITION_EASE = [0.22, 1, 0.36, 1] as const;

function providerRequiresApiKey(provider: LLMProviderConfig): boolean {
  return provider.provider_type !== 'custom' || (provider.api_format || 'openai') !== 'openai';
}

function isValidConfig(value: LLMConfig): boolean {
  const coreProviderId = value.selections?.core?.provider_id || '';
  const provider = value.providers?.[coreProviderId];
  if (!provider?.enabled || !provider.services?.chat?.enabled) {
    return false;
  }

  const hasCore = Boolean(value.selections?.core?.model);
  const hasContextDecider = Boolean(value.selections?.context_decider?.model);
  if (!hasCore || !hasContextDecider) {
    return false;
  }

  if (provider.provider_type === 'custom') {
    const hasBaseUrl = Boolean((provider.base_url || provider.services.chat.base_url || '').trim());
    const hasApiKey = Boolean((provider.api_key || provider.services.chat.api_key || '').trim());
    return hasBaseUrl && (!providerRequiresApiKey(provider) || hasApiKey);
  }

  return Boolean((provider.api_key || provider.services.chat.api_key || '').trim());
}

function cloneServiceConnection(
  value?: Partial<LLMProviderConfig['services']['chat']>,
  defaultEnabled = true
): LLMProviderConfig['services']['chat'] {
  return {
    enabled: value?.enabled ?? defaultEnabled,
    api_key: value?.api_key || '',
    base_url: value?.base_url || '',
  };
}

function cloneImageService(
  value?: Partial<LLMProviderConfig['services']['image_generation']>
): LLMProviderConfig['services']['image_generation'] {
  return {
    ...cloneServiceConnection(value, false),
    timeout: value?.timeout ?? 180,
    native_protocol: value?.native_protocol ?? null,
  };
}

function cloneTtsService(
  value?: Partial<LLMProviderConfig['services']['tts']>
): LLMProviderConfig['services']['tts'] {
  return {
    ...cloneServiceConnection(value, false),
    model: value?.model || '',
    voice: value?.voice || '',
    response_format: value?.response_format || '',
  };
}

function getProviderType(meta: LLMProviderMeta): LLMProvider {
  return (meta.provider_type || meta.id) as LLMProvider;
}

function normalizeEndpointBaseUrl(value?: string | null): string {
  return String(value || '').trim().replace(/\/+$/, '').toLowerCase();
}

function getPlanDefaultBaseUrl(
  plan: NonNullable<LLMProviderMeta['plans']>[number] | undefined,
  fallbackBaseUrl = ''
): string {
  return plan?.default_base_url || plan?.endpoints?.[0]?.base_url || fallbackBaseUrl;
}

function getPlanEndpointValue(
  plan: NonNullable<LLMProviderMeta['plans']>[number] | undefined,
  baseUrl?: string | null
): string {
  const normalizedBaseUrl = normalizeEndpointBaseUrl(baseUrl);
  if (!plan?.endpoints?.length || !normalizedBaseUrl) {
    return '';
  }
  return plan.endpoints.find((endpoint) => normalizeEndpointBaseUrl(endpoint.base_url) === normalizedBaseUrl)?.id || '';
}

function createProviderFromMeta(meta: LLMProviderMeta, existing?: LLMProviderConfig): LLMProviderConfig {
  const providerType = getProviderType(meta);
  const apiKey = existing?.api_key || existing?.services?.chat?.api_key || '';
  const baseUrl = existing?.base_url || meta.default_base_url || '';

  return cloneProvider({
    enabled: true,
    provider_type: providerType,
    display_name: existing?.display_name || meta.display_name || meta.id,
    provider_plan: existing?.provider_plan || meta.provider_plan || null,
    api_key: apiKey,
    base_url: baseUrl,
    services: {
      chat: { enabled: true, api_key: apiKey, base_url: existing?.services?.chat?.base_url || '' },
      embedding: {
        enabled: existing?.services?.embedding?.enabled ?? Boolean(meta.resolved_embedding_models?.length),
        api_key: existing?.services?.embedding?.api_key || '',
        base_url: existing?.services?.embedding?.base_url || '',
      },
      image_generation: cloneImageService(existing?.services?.image_generation),
      tts: cloneTtsService(existing?.services?.tts),
    },
    api_format: existing?.api_format || meta.api_format || 'openai',
    custom_models: existing?.custom_models || [],
    custom_default_model: existing?.custom_default_model || '',
    model_metadata_overrides: existing?.model_metadata_overrides || {},
  });
}

function createCustomProvider(
  displayName: string,
  defaults?: LLMProviderConfig | null,
  existing?: LLMProviderConfig
): LLMProviderConfig {
  const source = existing || defaults || undefined;
  const apiKey = source?.api_key || source?.services?.chat?.api_key || '';
  const baseUrl = source?.base_url || source?.services?.chat?.base_url || '';

  return cloneProvider({
    enabled: true,
    provider_type: 'custom',
    display_name: source?.display_name || displayName,
    provider_plan: source?.provider_plan || null,
    api_key: apiKey,
    base_url: baseUrl,
    services: {
      chat: { enabled: true, api_key: apiKey, base_url: source?.services?.chat?.base_url || '' },
      embedding: cloneServiceConnection(source?.services?.embedding, false),
      image_generation: cloneImageService(source?.services?.image_generation),
      tts: cloneTtsService(source?.services?.tts),
    },
    api_format: source?.api_format || 'openai',
    custom_models: source?.custom_models || [],
    custom_default_model: source?.custom_default_model || source?.custom_models?.[0] || '',
    model_metadata_overrides: source?.model_metadata_overrides || {},
  });
}

function buildSelection(
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig,
  scenario: LLMScenario,
  model: string
) {
  const selection = cloneSelection({ provider_id: providerId, model });
  applySelectionDefaults(selection, registry, providerId, provider, scenario);
  if (model && !selection.model) {
    selection.model = model;
  }
  return selection;
}

function resolveScenarioModel(
  registry: LLMProviderRegistry,
  providerId: string,
  provider: LLMProviderConfig,
  scenario: LLMScenario,
  explicitModel?: string
): string {
  if (explicitModel !== undefined) {
    return explicitModel;
  }

  return resolveProviderDefaultModel(registry, providerId, provider, scenario);
}

function withCustomModels(provider: LLMProviderConfig, coreModel: string, contextModel: string): LLMProviderConfig {
  if (provider.provider_type !== 'custom') {
    return provider;
  }

  const models = Array.from(new Set([coreModel, contextModel].map((item) => item.trim()).filter(Boolean)));
  return cloneProvider({
    ...provider,
    custom_models: models,
    custom_default_model: coreModel.trim() || models[0] || '',
  });
}

function buildNextConfig(
  value: LLMConfig,
  registry: LLMProviderRegistry,
  providerId: string,
  providerInput: LLMProviderConfig,
  overrides: Partial<Record<'core' | 'context_decider' | 'embedding', string>> = {}
): LLMConfig {
  const currentCore = value.selections?.core?.provider_id === providerId ? value.selections.core.model : undefined;
  const currentContext =
    value.selections?.context_decider?.provider_id === providerId ? value.selections.context_decider.model : undefined;

  const coreModel = resolveScenarioModel(
    registry,
    providerId,
    providerInput,
    'core',
    overrides.core ?? currentCore
  );
  const contextModel = resolveScenarioModel(
    registry,
    providerId,
    providerInput,
    'context_decider',
    overrides.context_decider ?? currentContext
  );
  const provider = withCustomModels(providerInput, coreModel, contextModel || coreModel);
  const embeddingModel = resolveScenarioModel(
    registry,
    providerId,
    provider,
    'embedding',
    overrides.embedding
  );

  const next = cloneLLMConfig(value);
  next.providers = { [providerId]: provider };
  next.selections.core = buildSelection(registry, providerId, provider, 'core', coreModel);
  next.selections.context_decider = buildSelection(
    registry,
    providerId,
    provider,
    'context_decider',
    contextModel || coreModel
  );
  next.selections.memory_summarizer = isProviderAllowedForScenario(
    registry,
    provider,
    'memory_summarizer'
  )
    ? cloneSelection(next.selections.core)
    : cloneSelection();
  next.selections.embedding =
    embeddingModel && provider.services.embedding.enabled
      ? buildSelection(registry, providerId, provider, 'embedding', embeddingModel)
      : cloneSelection();
  next.selections.image_generation = cloneSelection();
  next.model_runtime_overrides = { ...(value.model_runtime_overrides || {}) };
  return next;
}

function findExistingProviderByType(value: LLMConfig, providerType: LLMProvider | 'custom') {
  return Object.entries(value.providers || {}).find(([, provider]) => provider.provider_type === providerType);
}

function getActiveProviderId(value: LLMConfig): string {
  return value.selections?.core?.provider_id || Object.keys(value.providers || {})[0] || '';
}

export function LLMSetupStep({
  value,
  onChange,
  onValid,
  connectionTestState,
  onTestConnection,
  onConnectionConfigPendingChange,
}: LLMSetupStepProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  const [registry, setRegistry] = useState<LLMProviderRegistry | null>(null);
  const [customTemplate, setCustomTemplate] = useState<LLMCustomProviderTemplateData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [catalogResolutionPending, setCatalogResolutionPending] = useState(false);
  const [catalogResolutionError, setCatalogResolutionError] = useState(false);
  const catalogResolutionRequestIdRef = useRef(0);
  const activeProviderId = getActiveProviderId(value);
  const activeProvider = activeProviderId ? value.providers?.[activeProviderId] : undefined;
  const [providerChooserOpen, setProviderChooserOpen] = useState(() => !activeProviderId);
  const shouldReduceMotion = useReducedMotion();
  const activeProviderMeta = activeProvider?.provider_type === 'custom'
    ? undefined
    : registry?.providers.find((provider) => provider.id === activeProvider?.provider_type);
  const activeProviderPlans = activeProviderMeta?.plans || [];
  const activeProviderPlan = activeProviderPlans.find((plan) => plan.id === activeProvider?.provider_plan);
  const activeProviderPlanEndpoints = activeProviderPlan?.endpoints || [];
  const selectedCardId = activeProvider?.provider_type === 'custom'
    ? 'custom'
    : activeProvider?.provider_type || '';
  const currentCoreModel = value.selections?.core?.model || '';
  const currentContextModel = value.selections?.context_decider?.model || '';
  useEffect(() => {
    return () => {
      catalogResolutionRequestIdRef.current += 1;
      onConnectionConfigPendingChange?.(false);
    };
  }, [onConnectionConfigPendingChange]);

  useEffect(() => {
    onValid?.(isValidConfig(value) && !catalogResolutionPending);
  }, [catalogResolutionPending, value, onValid]);

  useEffect(() => {
    let cancelled = false;

    const loadRegistry = async () => {
      try {
        setLoading(true);
        setError(null);
        const [catalog, template] = await Promise.all([
          configApi.resolveLLMProviderCatalog({ providers: value.providers || {} }),
          configApi.getLLMCustomProviderTemplate(),
        ]);
        if (cancelled) {
          return;
        }
        setCustomTemplate(template);
        setRegistry(buildRegistryFromCatalog(catalog, template));
      } catch {
        if (!cancelled) {
          setError(t('llm.loadFailed'));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadRegistry();
    return () => {
      cancelled = true;
    };
  }, []);

  const providerCards = useMemo<QuickProviderCard[]>(() => {
    if (!registry) {
      return [];
    }

    const builtInCards = registry.providers
      .filter((provider) => provider.source !== 'custom')
      .filter((provider) => provider.id === (provider.provider_type || provider.id))
      .sort((left, right) => {
        const leftIndex = QUICK_PROVIDER_PRIORITY.indexOf(left.id);
        const rightIndex = QUICK_PROVIDER_PRIORITY.indexOf(right.id);
        const normalizedLeft = leftIndex === -1 ? QUICK_PROVIDER_PRIORITY.length : leftIndex;
        const normalizedRight = rightIndex === -1 ? QUICK_PROVIDER_PRIORITY.length : rightIndex;
        if (normalizedLeft !== normalizedRight) {
          return normalizedLeft - normalizedRight;
        }
        return (left.display_name || left.id).localeCompare(right.display_name || right.id);
      })
      .map((provider) => ({
        id: provider.id,
        providerType: getProviderType(provider),
        title: t(`llm.providers.${provider.id}.name`, { defaultValue: provider.display_name || provider.id }),
        iconName: provider.icon,
        meta: provider,
      }));

    return [
      ...builtInCards,
      {
        id: 'custom',
        providerType: 'custom',
        title: t('llmSetup.customRelayTitle'),
        iconName: 'custom',
      },
    ];
  }, [registry, t]);

  const activeProviderCard = providerCards.find(
    (card) => selectedCardId === card.id || selectedCardId === card.providerType,
  );
  const activeProviderTitle = activeProvider?.provider_type === 'custom'
    ? activeProvider.display_name || activeProviderCard?.title || t('llmSetup.selectedProvider')
    : activeProviderCard?.title || activeProvider?.display_name || t('llmSetup.selectedProvider');

  const commitProvider = (
    providerId: string,
    provider: LLMProviderConfig,
    overrides?: Partial<Record<'core' | 'context_decider' | 'embedding', string>>
  ) => {
    if (!registry) {
      return;
    }
    catalogResolutionRequestIdRef.current += 1;
    setCatalogResolutionPending(false);
    onConnectionConfigPendingChange?.(false);
    setCatalogResolutionError(false);
    onChange(buildNextConfig(value, registry, providerId, provider, overrides));
  };

  const commitProviderWithResolvedRegistry = async (
    providerId: string,
    provider: LLMProviderConfig,
    overrides?: Partial<Record<'core' | 'context_decider' | 'embedding', string>>
  ) => {
    if (!registry) {
      return;
    }

    const requestId = ++catalogResolutionRequestIdRef.current;
    setCatalogResolutionError(false);
    if (!customTemplate) {
      onChange(buildNextConfig(value, registry, providerId, provider, overrides));
      return;
    }

    setCatalogResolutionPending(true);
    onConnectionConfigPendingChange?.(true);
    try {
      const catalog = await configApi.resolveLLMProviderCatalog({ providers: { [providerId]: provider } });
      if (requestId !== catalogResolutionRequestIdRef.current) {
        return;
      }
      const nextRegistry = buildRegistryFromCatalog(catalog, customTemplate);
      setRegistry(nextRegistry);
      onChange(buildNextConfig(value, nextRegistry, providerId, provider, overrides));
    } catch {
      if (requestId === catalogResolutionRequestIdRef.current) {
        setCatalogResolutionError(true);
      }
    } finally {
      if (requestId === catalogResolutionRequestIdRef.current) {
        setCatalogResolutionPending(false);
        onConnectionConfigPendingChange?.(false);
      }
    }
  };

  const handleSelectCard = (card: QuickProviderCard) => {
    if (!registry) {
      return;
    }

    if (card.providerType === 'custom') {
      const existing = findExistingProviderByType(value, 'custom');
      const providerId = existing?.[0] || 'custom';
      const provider = createCustomProvider(
        t('llmSetup.customRelayTitle'),
        customTemplate?.defaults,
        existing?.[1]
      );
      commitProvider(providerId, provider);
      setProviderChooserOpen(false);
      return;
    }

    if (!card.meta) {
      return;
    }
    const existing = findExistingProviderByType(value, card.providerType);
    const providerId = existing?.[0] || card.meta.id;
    const provider = createProviderFromMeta(card.meta, existing?.[1]);
    commitProvider(providerId, provider);
    setProviderChooserOpen(false);
  };

  const updateActiveProvider = (
    updater: (draft: LLMProviderConfig) => void,
    overrides?: Partial<Record<'core' | 'context_decider' | 'embedding', string>>
  ) => {
    if (!activeProviderId || !activeProvider) {
      return;
    }
    const nextProvider = cloneProvider(activeProvider);
    updater(nextProvider);
    commitProvider(activeProviderId, nextProvider, overrides);
  };

  const handleActiveProviderPlanChange = (planId: string) => {
    if (!activeProviderId || !activeProvider) {
      return;
    }
    const selectedPlan = activeProviderPlans.find((plan) => plan.id === planId);
    const defaultBaseUrl = getPlanDefaultBaseUrl(selectedPlan, activeProviderMeta?.default_base_url || '');
    const nextProvider = cloneProvider(activeProvider);
    nextProvider.provider_plan = planId || null;
    nextProvider.base_url = defaultBaseUrl;
    nextProvider.services.chat.base_url = '';
    nextProvider.services.embedding.base_url = '';
    nextProvider.services.image_generation.base_url = '';
    if (!planId) {
      nextProvider.services.embedding.enabled = Boolean(activeProviderMeta?.resolved_embedding_models?.length);
      nextProvider.services.image_generation.enabled = false;
    } else {
      if (selectedPlan?.embedding_models !== undefined && selectedPlan.embedding_models !== null) {
        nextProvider.services.embedding.enabled = selectedPlan.embedding_models.length > 0;
      }
      if (selectedPlan?.image_generation_models !== undefined && selectedPlan.image_generation_models !== null) {
        nextProvider.services.image_generation.enabled = selectedPlan.image_generation_models.length > 0;
      }
    }
    void commitProviderWithResolvedRegistry(activeProviderId, nextProvider, {
      core: selectedPlan?.default_model || undefined,
      context_decider: selectedPlan?.default_classify_model || selectedPlan?.default_model || undefined,
      embedding: nextProvider.services.embedding.enabled ? undefined : '',
    });
  };

  const handleActiveProviderPlanEndpointChange = (endpointId: string) => {
    if (!activeProviderId || !activeProvider || !activeProviderPlan) {
      return;
    }
    const selectedEndpoint = activeProviderPlan.endpoints?.find((endpoint) => endpoint.id === endpointId);
    if (!selectedEndpoint) {
      return;
    }
    updateActiveProvider((provider) => {
      provider.base_url = selectedEndpoint.base_url;
      provider.services.chat.base_url = '';
      provider.services.embedding.base_url = '';
      provider.services.image_generation.base_url = '';
    });
  };

  const memoryModelStatus = getMemoryModelStatus(value);
  const memoryModelMissingTitleKey = activeProvider?.provider_plan
    ? 'llmSetup.memoryModelPlanMissingTitle'
    : 'llmSetup.memoryModelMissingTitle';
  const memoryModelMissingBodyKey = activeProvider?.provider_plan
    ? 'llmSetup.memoryModelPlanMissingBody'
    : 'llmSetup.memoryModelMissingBody';

  const renderSecretInput = () => (
    <div className="relative">
      <input
        data-testid="llm-setup-api-key"
        aria-label={t('llmSetup.apiKeyLabel')}
        className={cn(fieldClassName, 'pr-10')}
        type={showApiKey ? 'text' : 'password'}
        value={activeProvider?.api_key || activeProvider?.services?.chat?.api_key || ''}
        placeholder={t('llmSetup.apiKeyPlaceholder')}
        onChange={(event) => {
          const apiKey = event.target.value;
          updateActiveProvider((provider) => {
            provider.api_key = apiKey;
            provider.services.chat.api_key = apiKey;
          });
        }}
      />
      <button
        type="button"
        className={secretFieldButtonClassName}
        aria-label={showApiKey ? t('llm.providerConfiguration.hideKey') : t('llm.providerConfiguration.showKey')}
        onClick={() => setShowApiKey((current) => !current)}
      >
        {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );

  if (loading) {
    return (
      <div
        data-testid="llm-setup-loading"
        className="flex min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-border bg-muted/20"
      >
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
    <fieldset
      disabled={catalogResolutionPending}
      aria-busy={catalogResolutionPending}
      className={cn(
        'm-0 min-w-0 border-0 p-0',
        catalogResolutionPending && 'pointer-events-none opacity-60',
      )}
      data-testid="llm-setup-simple"
    >
      <AnimatePresence initial={false} mode="popLayout">
        {providerChooserOpen || !activeProvider ? (
          <motion.section
            key="provider-chooser"
            id="llm-provider-chooser"
            data-testid="llm-provider-chooser"
            layout
            initial={shouldReduceMotion ? false : { opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={shouldReduceMotion ? undefined : { opacity: 0, y: -4 }}
            transition={
              shouldReduceMotion
                ? { duration: 0 }
                : { duration: 0.22, ease: PROVIDER_TRANSITION_EASE }
            }
            className="space-y-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-2">
                <h3 className="text-base font-semibold text-foreground">{t('llmSetup.providerTitle')}</h3>
                <p className="text-sm leading-6 text-muted-foreground">{t('llmSetup.providerDesc')}</p>
              </div>
              {activeProvider ? (
                <button
                  type="button"
                  data-testid="llm-setup-provider-back"
                  className="inline-flex h-10 shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors duration-200 hover:bg-muted/65 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                  onClick={() => setProviderChooserOpen(false)}
                >
                  <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                  {t('llmSetup.backToProviderConfig')}
                </button>
              ) : null}
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {providerCards.map((card) => {
                const selected = selectedCardId === card.id || selectedCardId === card.providerType;
                return (
                  <motion.button
                    key={card.id}
                    type="button"
                    data-testid={`llm-setup-provider-${card.id}`}
                    aria-pressed={selected}
                    onClick={() => handleSelectCard(card)}
                    whileHover={shouldReduceMotion ? undefined : { y: -1 }}
                    whileTap={shouldReduceMotion ? undefined : { scale: 0.985 }}
                    transition={{ duration: shouldReduceMotion ? 0 : 0.14 }}
                    className={cn(
                      'flex min-h-[64px] items-center gap-3 rounded-xl bg-card/85 px-4 py-3 text-left shadow-[inset_0_0_0_1px_hsl(var(--border)/0.58)] transition-[background-color,box-shadow,color] duration-200 hover:bg-card hover:shadow-[inset_0_0_0_1px_hsl(var(--border)/0.9),0_8px_24px_-22px_hsl(var(--foreground)/0.28)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 motion-reduce:transition-none',
                      selected && ONBOARDING_SELECTED_SURFACE_CLASS,
                    )}
                  >
                    <ProviderIcon
                      providerId={String(card.providerType)}
                      iconName={card.iconName}
                      displayName={card.title}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold text-foreground">{card.title}</span>
                    </span>
                  </motion.button>
                );
              })}
            </div>
          </motion.section>
        ) : activeProvider ? (
          <motion.section
            key={`provider-config-${selectedCardId}`}
            id="llm-provider-config"
            data-testid="llm-provider-config"
            initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={shouldReduceMotion ? undefined : { opacity: 0, y: 6 }}
            transition={
              shouldReduceMotion
                ? { duration: 0 }
                : { duration: 0.26, ease: PROVIDER_TRANSITION_EASE }
            }
            className="space-y-4"
          >
            <div
              data-testid="llm-setup-provider-summary"
              aria-live="polite"
              className="flex min-h-[48px] items-center justify-between gap-4 py-1"
            >
              <div className="flex min-w-0 items-center gap-3">
                <ProviderIcon
                  providerId={String(activeProvider.provider_type)}
                  iconName={activeProviderCard?.iconName}
                  displayName={activeProviderTitle}
                  className="h-8 w-8 rounded-sm bg-transparent shadow-none"
                />
                <span className="min-w-0">
                  <span className="block text-xs text-muted-foreground">{t('llmSetup.selectedProvider')}</span>
                  <span className="block truncate text-sm font-semibold text-foreground">{activeProviderTitle}</span>
                </span>
              </div>
              <button
                type="button"
                data-testid="llm-setup-provider-change"
                aria-expanded="false"
                aria-controls="llm-provider-chooser"
                className="inline-flex h-9 shrink-0 items-center gap-1 px-0 text-sm font-medium text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:text-foreground focus-visible:underline motion-reduce:transition-none"
                onClick={() => setProviderChooserOpen(true)}
              >
                {t('llmSetup.changeProvider')}
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>

            <div className="space-y-6 px-1 pb-1 pt-1 sm:px-2">
              <p className="max-w-3xl text-xs leading-5 text-muted-foreground">
                {activeProvider.provider_type === 'custom'
                  ? t('llmSetup.customRelaySelectedHint')
                  : t('llmSetup.builtinSelectedHint')}
              </p>

              {activeProvider.provider_type !== 'custom' && activeProviderPlans.length > 0 ? (
                <label className="block space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.providerPlan')}</span>
                  <SelectField
                    value={activeProvider.provider_plan || ''}
                    allowEmpty
                    placeholder={t('llm.providerPlans.default')}
                    options={activeProviderPlans.map((plan) => ({
                      label: plan.display_name || plan.id,
                      value: plan.id,
                    }))}
                    onChange={handleActiveProviderPlanChange}
                  />
                </label>
              ) : null}

              {activeProvider.provider_type !== 'custom' && activeProviderPlanEndpoints.length > 0 ? (
                <label className="block space-y-2">
                  <span className="text-sm font-medium">{t('llm.fields.providerEndpoint')}</span>
                  <SelectField
                    value={getPlanEndpointValue(activeProviderPlan, activeProvider.base_url || activeProvider.services.chat.base_url)}
                    allowEmpty={false}
                    placeholder={t('llm.providerPlans.customEndpoint')}
                    options={activeProviderPlanEndpoints.map((endpoint) => ({
                      label: endpoint.label || endpoint.country || endpoint.id,
                      value: endpoint.id,
                    }))}
                    onChange={handleActiveProviderPlanEndpointChange}
                  />
                </label>
              ) : null}

              {catalogResolutionError ? (
                <div
                  role="alert"
                  className="rounded-lg bg-destructive/5 px-3.5 py-3 text-sm text-destructive"
                >
                  {t('llmSetup.planLoadFailed')}
                </div>
              ) : null}

              {memoryModelStatus === 'missing' ? (
                <div
                  data-testid="llm-setup-embedding-row"
                  role="status"
                  className="flex items-start gap-2.5 rounded-lg bg-secondary/55 px-3 py-2.5 text-secondary-foreground"
                >
                  <Info className="mt-0.5 h-4 w-4 shrink-0 opacity-80" aria-hidden="true" />
                  <span className="flex min-w-0 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
                    <span className="shrink-0 text-sm font-medium">{t(memoryModelMissingTitleKey)}</span>
                    <span className="text-xs leading-5 text-secondary-foreground/70">
                      {t(memoryModelMissingBodyKey)}
                    </span>
                  </span>
                </div>
              ) : null}

              {activeProvider.provider_type === 'custom' ? (
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('llmSetup.baseUrlLabel')}</span>
                    <input
                      data-testid="llm-setup-base-url"
                      aria-label={t('llmSetup.baseUrlLabel')}
                      className={fieldClassName}
                      value={activeProvider.base_url || activeProvider.services.chat.base_url || ''}
                      placeholder={t('llmSetup.baseUrlPlaceholder')}
                      onChange={(event) => {
                        const baseUrl = event.target.value;
                        updateActiveProvider((provider) => {
                          provider.base_url = baseUrl;
                        });
                      }}
                    />
                  </label>

                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('llmSetup.coreModelLabel')}</span>
                    <input
                      data-testid="llm-setup-custom-model"
                      aria-label={t('llmSetup.coreModelLabel')}
                      className={fieldClassName}
                      value={currentCoreModel}
                      placeholder={t('llmSetup.coreModelPlaceholder')}
                      onChange={(event) => {
                        const model = event.target.value;
                        updateActiveProvider(
                          (provider) => {
                            provider.custom_default_model = model;
                          },
                          { core: model, context_decider: currentContextModel || model }
                        );
                      }}
                    />
                  </label>
                </div>
              ) : null}

              <div className="space-y-2">
                <span className="text-sm font-medium">
                  {!providerRequiresApiKey(activeProvider)
                    ? t('llmSetup.apiKeyOptionalLabel')
                    : t('llmSetup.apiKeyLabel')}
                </span>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <div className="min-w-0 flex-1">{renderSecretInput()}</div>
                  <button
                    type="button"
                    className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-muted/45 px-3.5 text-sm font-medium text-muted-foreground transition-[background-color,color,transform] duration-200 hover:bg-muted/70 hover:text-foreground active:translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={connectionTestState.loading}
                    onClick={() => void onTestConnection(true)}
                  >
                    {connectionTestState.loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Activity className="h-4 w-4" />
                    )}
                    <span>
                      {connectionTestState.loading
                        ? t('llmSetup.verifyingConnection')
                        : t('llmSetup.verifyConnection')}
                    </span>
                  </button>
                </div>
              </div>

              {connectionTestState.error || connectionTestState.result ? (
                <LLMProviderTestStatus
                  error={connectionTestState.error}
                  result={connectionTestState.result}
                />
              ) : null}

              <div className="pt-1">
                <button
                  type="button"
                  data-testid="llm-setup-advanced-toggle"
                  aria-expanded={showAdvanced}
                  aria-controls="llm-setup-advanced-settings"
                  className="-ml-2 inline-flex h-9 items-center gap-1.5 rounded-lg px-2 text-sm font-medium text-muted-foreground transition-colors duration-200 hover:bg-muted/45 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                  onClick={() => setShowAdvanced((current) => !current)}
                >
                  <ChevronDown
                    className={cn('h-4 w-4 transition-transform duration-200', showAdvanced && 'rotate-180')}
                    aria-hidden="true"
                  />
                  {showAdvanced ? t('llmSetup.hideAdvanced') : t('llmSetup.showAdvanced')}
                </button>
              </div>

              <AnimatePresence initial={false}>
                {showAdvanced ? (
                  <motion.div
                    id="llm-setup-advanced-settings"
                    key="advanced-settings"
                    initial={shouldReduceMotion ? false : { opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={shouldReduceMotion ? undefined : { opacity: 0, y: -4 }}
                    transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: PROVIDER_TRANSITION_EASE }}
                    className="grid gap-4 rounded-lg bg-muted/25 p-4 md:grid-cols-2"
                  >
                    {activeProvider.provider_type === 'custom' ? (
                      <label className="space-y-2">
                        <span className="text-sm font-medium">{t('llmSetup.customNameLabel')}</span>
                        <input
                          data-testid="llm-setup-custom-name"
                          aria-label={t('llmSetup.customNameLabel')}
                          className={fieldClassName}
                          value={activeProvider.display_name || ''}
                          onChange={(event) => {
                            const displayName = event.target.value;
                            updateActiveProvider((provider) => {
                              provider.display_name = displayName;
                            });
                          }}
                        />
                      </label>
                    ) : null}

                    {activeProvider.provider_type !== 'custom' ? (
                      <label className="space-y-2 md:col-span-2">
                        <span className="text-sm font-medium">{t('llmSetup.baseUrlOptionalLabel')}</span>
                        <input
                          data-testid="llm-setup-base-url"
                          aria-label={t('llmSetup.baseUrlOptionalLabel')}
                          className={fieldClassName}
                          value={activeProvider.base_url || ''}
                          placeholder={activeProviderMeta?.default_base_url || t('llmSetup.baseUrlDefaultPlaceholder')}
                          onChange={(event) => {
                            const baseUrl = event.target.value;
                            updateActiveProvider((provider) => {
                              provider.base_url = baseUrl;
                            });
                          }}
                        />
                      </label>
                    ) : (
                      <label className="space-y-2">
                        <span className="text-sm font-medium">{t('llmSetup.apiFormatLabel')}</span>
                        <select
                          data-testid="llm-setup-api-format"
                          aria-label={t('llmSetup.apiFormatLabel')}
                          className={fieldClassName}
                          value={activeProvider.api_format || 'openai'}
                          onChange={(event) => {
                            const apiFormat = event.target.value as ApiFormat;
                            updateActiveProvider((provider) => {
                              provider.api_format = apiFormat;
                            });
                          }}
                        >
                          <option value="openai">{t('llm.apiFormatOptions.openai')}</option>
                          <option value="anthropic">{t('llm.apiFormatOptions.anthropic')}</option>
                        </select>
                      </label>
                    )}

                    {activeProvider.provider_type !== 'custom' ? (
                      <label className="space-y-2">
                        <span className="text-sm font-medium">{t('llmSetup.coreModelLabel')}</span>
                        <input
                          data-testid="llm-setup-core-model"
                          aria-label={t('llmSetup.coreModelLabel')}
                          className={fieldClassName}
                          value={currentCoreModel}
                          placeholder={t('llmSetup.coreModelPlaceholder')}
                          onChange={(event) => {
                            const model = event.target.value;
                            updateActiveProvider(
                              () => undefined,
                              { core: model, context_decider: currentContextModel || model }
                            );
                          }}
                        />
                      </label>
                    ) : null}

                    <label className={cn('space-y-2', activeProvider.provider_type === 'custom' && 'md:col-span-2')}>
                      <span className="text-sm font-medium">{t('llmSetup.fastModelLabel')}</span>
                      <input
                        data-testid="llm-setup-fast-model"
                        aria-label={t('llmSetup.fastModelLabel')}
                        className={fieldClassName}
                        value={currentContextModel}
                        placeholder={currentCoreModel || t('llmSetup.fastModelPlaceholder')}
                        onChange={(event) => {
                          const model = event.target.value;
                          updateActiveProvider(
                            () => undefined,
                            { core: currentCoreModel, context_decider: model || currentCoreModel }
                          );
                        }}
                      />
                    </label>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          </motion.section>
        ) : null}
      </AnimatePresence>
    </fieldset>
  );
}

export default LLMSetupStep;
