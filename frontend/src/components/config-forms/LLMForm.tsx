import React, { useContext, useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  configApi,
  DEFAULT_LLM_CAPABILITIES,
  DEFAULT_LLM_LIMITS,
  type LLMCapabilities,
  type LLMConfig,
  type LLMLimits,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type LLMSelectionConfig,
} from '@/api/modules/config';
import { cn } from '@/lib/utils';

import { FormContext } from '../onboarding/simple-form';
import { LLMModelSelectionSection } from './LLMModelSelectionSection';
import { LLMProviderConfigurationSection } from './LLMProviderConfigurationSection';

interface LLMFormProps {
  quickMode?: boolean;
  value?: LLMConfig;
  onChange?: (nextValue: LLMConfig) => void;
  showAdvancedByDefault?: boolean;
}

const BUILTIN_SCENARIOS: LLMScenario[] = ['context_decider', 'core'];

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
});

const cloneSelection = (value?: Partial<LLMSelectionConfig>): LLMSelectionConfig => ({
  provider_id: value?.provider_id || 'openai',
  model: value?.model || '',
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
  },
});

const llmSignature = (value: LLMConfig): string => JSON.stringify(value);

const getProviderMeta = (registry: LLMProviderRegistry, providerId?: string) =>
  registry.providers.find((provider) => provider.id === providerId);

const getProviderModels = (registry: LLMProviderRegistry, providerId?: string) =>
  getProviderMeta(registry, providerId)?.models || [];

const applySelectionDefaults = (
  selection: LLMSelectionConfig,
  registry: LLMProviderRegistry,
  provider: LLMProviderConfig | undefined
) => {
  if (!provider) {
    return;
  }

  if (provider.provider_type === 'custom') {
    if (!selection.capability_override_enabled) {
      selection.capabilities = cloneCapabilities(registry.custom_provider.capabilities);
      selection.limits = cloneLimits(registry.custom_provider.limits);
      selection.provider_options = { ...(registry.custom_provider.provider_options_example || {}) };
    }
    return;
  }

  const models = getProviderModels(registry, provider.provider_type);
  const matchedModel = models.find((model) => model.id === selection.model);
  const fallbackModel = matchedModel || models[0];
  if (fallbackModel) {
    selection.model = fallbackModel.id;
    if (!selection.capability_override_enabled) {
      selection.capabilities = cloneCapabilities(fallbackModel.capabilities);
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
        base_url: providerMeta.default_base_url || '',
      };
    } else {
      next.providers[providerMeta.id] = {
        ...cloneProvider(next.providers[providerMeta.id]),
        provider_type: providerMeta.id as LLMProviderConfig['provider_type'],
        display_name: next.providers[providerMeta.id].display_name || providerMeta.display_name || providerMeta.id,
        base_url: next.providers[providerMeta.id].base_url || providerMeta.default_base_url || '',
      };
    }
  }

  const firstEnabledProviderId =
    Object.entries(next.providers).find(([, provider]) => provider.enabled)?.[0] || registry.providers[0]?.id || 'openai';

  for (const scenario of BUILTIN_SCENARIOS) {
    const selection = cloneSelection(next.selections[scenario]);
    const selectedProvider =
      next.providers[selection.provider_id] && next.providers[selection.provider_id].enabled
        ? next.providers[selection.provider_id]
        : next.providers[firstEnabledProviderId];

    selection.provider_id =
      next.providers[selection.provider_id] && next.providers[selection.provider_id].enabled
        ? selection.provider_id
        : firstEnabledProviderId;

    applySelectionDefaults(selection, registry, selectedProvider);
    next.selections[scenario] = selection;
  }

  return next;
};

const LLMForm: React.FC<LLMFormProps> = ({ quickMode = false, value, onChange }) => {
  const { t } = useTranslation('onboarding');
  const formCtx = useContext(FormContext);
  const controlled = value !== undefined && typeof onChange === 'function';
  const [registry, setRegistry] = useState<LLMProviderRegistry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeProviderId, setActiveProviderId] = useState<string>('openai');

  const currentValue = useMemo(() => {
    if (controlled) {
      return cloneLLMConfig(value);
    }
    return cloneLLMConfig(formCtx?.values?.llm as LLMConfig | undefined);
  }, [controlled, formCtx?.values?.llm, value]);

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
      if (provider?.provider_type === 'custom') {
        selection.model = selection.model || '';
      } else {
        const fallbackModel = getProviderMeta(registry, provider?.provider_type)?.default_model || getProviderModels(registry, providerId)[0]?.id || '';
        selection.model = fallbackModel;
      }
      applySelectionDefaults(selection, registry, provider);
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
      applySelectionDefaults(selection, registry, draft.providers[selection.provider_id]);
      draft.selections[scenario] = selection;
    });
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
      };
    });
    setActiveProviderId(nextProviderId);
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
    <div className={cn('space-y-6', quickMode && 'space-y-5')}>
      <LLMModelSelectionSection
        registry={registry}
        value={currentValue}
        quickMode={quickMode}
        onScenarioProviderChange={handleScenarioProviderChange}
        onScenarioModelChange={handleScenarioModelChange}
      />

      <LLMProviderConfigurationSection
        registry={registry}
        value={currentValue}
        activeProviderId={activeProviderId}
        quickMode={quickMode}
        scenarioReferences={scenarioReferences}
        onActiveProviderChange={setActiveProviderId}
        onProviderChange={handleProviderChange}
        onAddCustomProvider={handleAddCustomProvider}
      />
    </div>
  );
};

export default LLMForm;
