import React, { useContext, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Brain,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  ImageIcon,
  Info,
  Loader2,
  Settings2,
  Sparkles,
  Wand2,
  Wrench,
  Database,
  ScanEye,
  RotateCcw,
  Zap,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

import { configApi, DEFAULT_LLM_CAPABILITIES, DEFAULT_LLM_LIMITS, type LLMCapabilities, type LLMConfig, type LLMCustomProviderMeta, type LLMLimits, type LLMModelMeta, type LLMProviderFieldConfig, type LLMProviderMeta, type LLMProviderRegistry } from '../../api/modules/config';
import { SimpleForm as Form, FormContext } from '../onboarding/simple-form';
import { SelectField } from './fields';

interface LLMFormProps {
  quickMode?: boolean;
  value?: LLMConfig;
  onChange?: (nextValue: LLMConfig) => void;
  showAdvancedByDefault?: boolean;
}

const cloneCapabilities = (value?: Partial<LLMCapabilities>): LLMCapabilities => ({
  ...DEFAULT_LLM_CAPABILITIES,
  ...(value || {}),
});

const cloneLimits = (value?: Partial<LLMLimits>): LLMLimits => ({
  ...DEFAULT_LLM_LIMITS,
  ...(value || {}),
});

const cloneLLMConfig = (value?: LLMConfig): LLMConfig => ({
  provider: value?.provider || 'openai',
  model: value?.model || '',
  api_key: value?.api_key,
  base_url: value?.base_url,
  custom_name: value?.custom_name,
  api_format: value?.api_format,
  from_env: value?.from_env,
  capability_override_enabled: Boolean(value?.capability_override_enabled),
  capabilities: cloneCapabilities(value?.capabilities),
  limits: cloneLimits(value?.limits),
  provider_options: { ...(value?.provider_options || {}) },
});

const iconNode = (icon?: string): JSX.Element => {
  switch (icon) {
    case 'brain':
      return <Brain className="h-3.5 w-3.5 text-primary-600" />;
    case 'zap':
      return <Zap className="h-3.5 w-3.5 text-primary-600" />;
    case 'wand':
      return <Wand2 className="h-3.5 w-3.5 text-primary-600" />;
    case 'sparkles':
    default:
      return <Sparkles className="h-3.5 w-3.5 text-primary-600" />;
  }
};

const capabilityIcon = (key: keyof LLMCapabilities): JSX.Element => {
  switch (key) {
    case 'vision':
      return <ScanEye className="h-4 w-4" />;
    case 'image_output':
      return <ImageIcon className="h-4 w-4" />;
    case 'tool_calling':
      return <Wrench className="h-4 w-4" />;
    case 'reasoning':
      return <Brain className="h-4 w-4" />;
    case 'embedding':
      return <Database className="h-4 w-4" />;
    default:
      return <Sparkles className="h-4 w-4" />;
  }
};

const selectableStyle = (active: boolean): string =>
  cn(
    'rounded-xl border bg-background p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-600/60',
    active ? 'border-primary-600 bg-primary-600/5 shadow-sm' : 'border-border hover:border-primary-500/40'
  );

const getProviderI18n = (providerId: string) => {
  const i18nMap: Record<string, { name: string; desc: string }> = {
    openai: { name: 'llm.providers.openai.name', desc: 'llm.providers.openai.desc' },
    anthropic: { name: 'llm.providers.anthropic.name', desc: 'llm.providers.anthropic.desc' },
    glm: { name: 'llm.providers.glm.name', desc: 'llm.providers.glm.desc' },
    custom: { name: 'llm.providers.custom.name', desc: 'llm.providers.custom.desc' },
  };
  return i18nMap[providerId] || { name: providerId, desc: '' };
};

const fieldConfig = (
  provider: LLMProviderMeta | LLMCustomProviderMeta | undefined,
  fieldName: string,
  fallback: LLMProviderFieldConfig,
): LLMProviderFieldConfig => provider?.fields?.[fieldName] || fallback;

const normalizeModels = (provider?: LLMProviderMeta): LLMModelMeta[] => {
  if (!provider) return [];
  if (provider.models?.length) return provider.models;
  return (provider.model_options || []).map((modelId) => ({
    id: modelId,
    label: modelId,
    capabilities: cloneCapabilities(),
    limits: cloneLimits(),
    provider_options_example: {},
  }));
};

const findModelMeta = (provider: LLMProviderMeta | undefined, modelId?: string): LLMModelMeta | undefined => {
  const lowered = String(modelId || '').trim().toLowerCase();
  return normalizeModels(provider).find((item) => item.id.toLowerCase() === lowered);
};

const capabilityEntries = (
  t: ReturnType<typeof useTranslation>['t'],
): Array<{ key: keyof LLMCapabilities; label: string; helper?: string }> => [
  { key: 'vision', label: t('llm.capabilities.vision') },
  { key: 'image_output', label: t('llm.capabilities.imageOutput') },
  { key: 'tool_calling', label: t('llm.capabilities.toolCalling'), helper: t('llm.autoBadge') },
  { key: 'reasoning', label: t('llm.capabilities.reasoning'), helper: t('llm.autoBadge') },
  { key: 'embedding', label: t('llm.capabilities.embedding') },
];

const llmSignature = (value: LLMConfig): string => JSON.stringify({
  provider: value.provider,
  model: value.model,
  base_url: value.base_url,
  custom_name: value.custom_name,
  api_format: value.api_format,
  capability_override_enabled: value.capability_override_enabled,
  capabilities: value.capabilities,
  limits: value.limits,
  provider_options: value.provider_options,
});

const buildModelDefaults = (
  model: LLMModelMeta | undefined,
  customProvider: LLMCustomProviderMeta | undefined,
  activeProvider: string,
) => {
  if (activeProvider === 'custom') {
    return {
      capabilities: cloneCapabilities(customProvider?.capabilities),
      limits: cloneLimits(customProvider?.limits),
      provider_options: { ...(customProvider?.provider_options_example || {}) },
    };
  }

  return {
    capabilities: cloneCapabilities(model?.capabilities),
    limits: cloneLimits(model?.limits),
    provider_options: { ...(model?.provider_options_example || {}) },
  };
};

const syncWithRegistry = (
  llm: LLMConfig,
  registry: LLMProviderRegistry,
): LLMConfig => {
  const next = cloneLLMConfig(llm);
  const providers = registry.providers || [];
  const customProvider = registry.custom_provider;

  if (!next.provider && providers[0]) {
    next.provider = providers[0].id as LLMConfig['provider'];
  }

  if (next.provider === 'custom') {
    const defaults = buildModelDefaults(undefined, customProvider, 'custom');
    if (!next.capability_override_enabled) {
      next.capabilities = defaults.capabilities;
      next.limits = defaults.limits;
      next.provider_options = defaults.provider_options;
    }
    return next;
  }

  const providerMeta = providers.find((provider) => provider.id === next.provider) || providers[0];
  if (!providerMeta) return next;

  const models = normalizeModels(providerMeta);
  const matchedModel = findModelMeta(providerMeta, next.model);
  const fallbackModel = matchedModel || models.find((item) => item.id === providerMeta.default_model) || models[0];

  next.provider = providerMeta.id as LLMConfig['provider'];
  if (fallbackModel) {
    next.model = fallbackModel.id;
  }
  if (providerMeta.default_base_url && !next.base_url) {
    next.base_url = providerMeta.default_base_url;
  }

  if (!next.capability_override_enabled) {
    const defaults = buildModelDefaults(fallbackModel, customProvider, providerMeta.id);
    next.capabilities = defaults.capabilities;
    next.limits = defaults.limits;
    next.provider_options = defaults.provider_options;
  }

  return next;
};

const LLMForm: React.FC<LLMFormProps> = ({
  quickMode = false,
  value,
  onChange,
  showAdvancedByDefault,
}) => {
  const { t } = useTranslation('onboarding');
  const formCtx = useContext(FormContext);
  const controlled = value !== undefined && typeof onChange === 'function';
  const [registry, setRegistry] = useState<LLMProviderRegistry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(showAdvancedByDefault ?? !quickMode);
  const [providerOptionsDraft, setProviderOptionsDraft] = useState('{}');
  const [providerOptionsError, setProviderOptionsError] = useState<string | null>(null);

  const currentValue = useMemo(() => {
    if (controlled) return cloneLLMConfig(value);
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
        if (response.data?.providers?.length) {
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
    setProviderOptionsDraft(JSON.stringify(currentValue.provider_options || {}, null, 2));
    setProviderOptionsError(null);
  }, [currentValue.provider_options, currentValue.provider, currentValue.model]);

  useEffect(() => {
    if (!registry) return;
    const synced = syncWithRegistry(currentValue, registry);
    if (llmSignature(synced) !== llmSignature(currentValue)) {
      updateValue((draft) => Object.assign(draft, synced));
    }
  }, [currentValue, registry]); // eslint-disable-line react-hooks/exhaustive-deps

  const providers = registry?.providers || [];
  const customProvider = registry?.custom_provider || { enabled: false };
  const activeProvider =
    currentValue.provider === 'custom'
      ? undefined
      : providers.find((provider) => provider.id === currentValue.provider);
  const activeModel = currentValue.provider === 'custom'
    ? undefined
    : findModelMeta(activeProvider, currentValue.model);
  const activeProviderMeta = currentValue.provider === 'custom' ? customProvider : activeProvider;
  const modelConfig = fieldConfig(activeProviderMeta, 'model', { visible: true, required: true });
  const apiKeyConfig = fieldConfig(activeProviderMeta, 'api_key', { visible: true, required: true });
  const baseUrlConfig = fieldConfig(activeProviderMeta, 'base_url', { visible: true, required: false });
  const customNameConfig = fieldConfig(activeProviderMeta, 'custom_name', { visible: true, required: true });
  const apiFormatConfig = fieldConfig(activeProviderMeta, 'api_format', { visible: true, required: true });
  const fromEnv = currentValue.from_env ?? false;
  const hasEnvApiKey = Boolean(fromEnv && currentValue.api_key && currentValue.api_key.endsWith('****'));
  const capabilitySummary = capabilityEntries(t);

  const applyProvider = (providerId: string) => {
    const selected = providers.find((item) => item.id === providerId);
    updateValue((draft) => {
      draft.provider = providerId as LLMConfig['provider'];
      if (providerId === 'custom') {
        draft.capability_override_enabled = false;
        draft.capabilities = cloneCapabilities(customProvider.capabilities);
        draft.limits = cloneLimits(customProvider.limits);
        draft.provider_options = { ...(customProvider.provider_options_example || {}) };
        return;
      }

      if (selected?.default_model) {
        draft.model = selected.default_model;
      } else if (normalizeModels(selected)[0]) {
        draft.model = normalizeModels(selected)[0].id;
      }
      draft.base_url = selected?.default_base_url || draft.base_url;
      draft.capability_override_enabled = false;
      const selectedModel = findModelMeta(selected, draft.model);
      draft.capabilities = cloneCapabilities(selectedModel?.capabilities);
      draft.limits = cloneLimits(selectedModel?.limits);
      draft.provider_options = { ...(selectedModel?.provider_options_example || {}) };
    });
  };

  const applyModel = (modelId: string) => {
    updateValue((draft) => {
      draft.model = modelId;
      draft.capability_override_enabled = false;
      const selectedModel = findModelMeta(activeProvider, modelId);
      draft.capabilities = cloneCapabilities(selectedModel?.capabilities);
      draft.limits = cloneLimits(selectedModel?.limits);
      draft.provider_options = { ...(selectedModel?.provider_options_example || {}) };
    });
  };

  const commitProviderOptions = (rawValue: string) => {
    setProviderOptionsDraft(rawValue);
    try {
      const parsed = rawValue.trim() ? JSON.parse(rawValue) : {};
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setProviderOptionsError(t('llm.providerOptionsInvalid'));
        return;
      }
      setProviderOptionsError(null);
      updateValue((draft) => {
        draft.provider_options = parsed as Record<string, any>;
      });
    } catch {
      setProviderOptionsError(t('llm.providerOptionsInvalid'));
    }
  };

  const renderFieldShell = (
    label: string,
    name: any[] | null,
    rules: Array<{ required?: boolean; message?: string; validator?: (_: any, value: string) => Promise<void> }> | undefined,
    child: React.ReactNode,
  ) => {
    if (!controlled && name) {
      return (
        <Form.Item label={label} name={name} rules={rules}>
          {child}
        </Form.Item>
      );
    }
    return (
      <label className="space-y-2">
        <span className="text-sm font-medium">{label}</span>
        {child}
      </label>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
        <span className="ml-2 text-muted-foreground">{t('llm.loading')}</span>
      </div>
    );
  }

  if (error || !registry) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive" />
        <p className="font-medium text-destructive">{error || t('llm.loadFailed')}</p>
        <p className="text-sm text-muted-foreground">{t('llm.loadFailedDesc')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {fromEnv && (
        <div className="flex items-center gap-2 rounded-lg border border-primary-600/30 bg-primary-600/10 px-3 py-2 text-sm text-primary-700">
          <Info className="h-4 w-4 flex-shrink-0" />
          <span>{t('llm.fromEnvHint')}</span>
        </div>
      )}

      {!controlled ? (
        <Form.Item label={t('llm.providerLabel')} name={['llm', 'provider']} rules={[{ required: true, message: t('llm.providerRequired') }]}>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              {providers.map((provider) => {
                const i18n = getProviderI18n(provider.id);
                return (
                  <button
                    type="button"
                    key={provider.id}
                    onClick={() => applyProvider(provider.id)}
                    className={cn(selectableStyle(currentValue.provider === provider.id), 'flex min-h-[82px] flex-col justify-center px-4')}
                  >
                    <div className="mb-1 flex items-center justify-center gap-2 text-lg font-semibold text-foreground">
                      {iconNode(provider.icon)}
                      {provider.display_name || t(i18n.name)}
                    </div>
                    <p className="text-center text-xs text-muted-foreground">{provider.description || t(i18n.desc)}</p>
                  </button>
                );
              })}
            </div>

            {customProvider.enabled && (
              <button
                type="button"
                onClick={() => applyProvider('custom')}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg border border-dashed px-4 py-2.5 text-base',
                  currentValue.provider === 'custom'
                    ? 'border-primary-500 bg-primary-50 text-primary-800'
                    : 'border-muted-foreground/45 bg-muted/20 text-foreground/90 hover:border-primary-500/60 hover:bg-primary-50/40'
                )}
              >
                {iconNode(customProvider.icon)}
                <span className="font-semibold">{customProvider.display_name || t('llm.providers.custom.name')}</span>
              </button>
            )}
          </div>
        </Form.Item>
      ) : (
        <div className="space-y-3">
          <div>
            <h3 className="text-sm font-medium">{t('llm.providerLabel')}</h3>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {providers.map((provider) => {
              const i18n = getProviderI18n(provider.id);
              return (
                <button
                  type="button"
                  key={provider.id}
                  onClick={() => applyProvider(provider.id)}
                  className={cn(selectableStyle(currentValue.provider === provider.id), 'flex min-h-[82px] flex-col justify-center px-4')}
                >
                  <div className="mb-1 flex items-center justify-center gap-2 text-lg font-semibold text-foreground">
                    {iconNode(provider.icon)}
                    {provider.display_name || t(i18n.name)}
                  </div>
                  <p className="text-center text-xs text-muted-foreground">{provider.description || t(i18n.desc)}</p>
                </button>
              );
            })}
          </div>
          {customProvider.enabled && (
            <button
              type="button"
              onClick={() => applyProvider('custom')}
              className={cn(
                'inline-flex items-center gap-2 rounded-lg border border-dashed px-4 py-2.5 text-base',
                currentValue.provider === 'custom'
                  ? 'border-primary-500 bg-primary-50 text-primary-800'
                  : 'border-muted-foreground/45 bg-muted/20 text-foreground/90 hover:border-primary-500/60 hover:bg-primary-50/40'
              )}
            >
              {iconNode(customProvider.icon)}
              <span className="font-semibold">{customProvider.display_name || t('llm.providers.custom.name')}</span>
            </button>
          )}
        </div>
      )}

      <div className="rounded-2xl border border-border/80 bg-muted/20 p-4">
        <div className="grid gap-4 md:grid-cols-2">
          {modelConfig.visible && renderFieldShell(
            t('llm.modelLabel'),
            ['llm', 'model'],
            modelConfig.required
              ? [
                  { required: true, message: t('llm.modelRequired') },
                  {
                    validator: (_: any, fieldValue: string) => {
                      if (currentValue.provider === 'custom') return Promise.resolve();
                      const modelIds = normalizeModels(activeProvider).map((item) => item.id);
                      if (fieldValue && modelIds.length && !modelIds.includes(fieldValue)) {
                        return Promise.reject(new Error(t('llm.modelInvalid')));
                      }
                      return Promise.resolve();
                    },
                  },
                ]
              : undefined,
            currentValue.provider !== 'custom' && normalizeModels(activeProvider).length ? (
              <SelectField
                value={currentValue.model}
                onChange={applyModel}
                allowEmpty={false}
                placeholder={t('llm.modelPlaceholder')}
                options={normalizeModels(activeProvider).map((item) => ({
                  label: item.label || item.id,
                  value: item.id,
                }))}
              />
            ) : (
              <Input
                value={currentValue.model}
                onChange={(event) => updateValue((draft) => {
                  draft.model = event.target.value;
                })}
                placeholder="gpt-5.2"
              />
            ),
          )}

          {apiKeyConfig.visible && renderFieldShell(
            'API Key',
            ['llm', 'api_key'],
            !hasEnvApiKey && apiKeyConfig.required ? [{ required: true, message: t('llm.apiKeyRequired') }] : undefined,
            <div className="relative">
              <Input
                type={hasEnvApiKey ? 'text' : showApiKey ? 'text' : 'password'}
                readOnly={hasEnvApiKey}
                value={currentValue.api_key || ''}
                onChange={(event) => updateValue((draft) => {
                  draft.api_key = event.target.value;
                })}
                placeholder="sk-..."
                className={hasEnvApiKey ? 'bg-muted/50 pr-10' : 'pr-10'}
              />
              {!hasEnvApiKey && (
                <button
                  type="button"
                  onClick={() => setShowApiKey((prev) => !prev)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  tabIndex={-1}
                >
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              )}
            </div>,
          )}

          {baseUrlConfig.visible && renderFieldShell(
            `${t('llm.baseUrlLabel')}${baseUrlConfig.required ? '' : t('llm.optional')}`,
            ['llm', 'base_url'],
            baseUrlConfig.required ? [{ required: true, message: t('llm.baseUrlRequired') }] : undefined,
            <Input
              value={currentValue.base_url || ''}
              onChange={(event) => updateValue((draft) => {
                draft.base_url = event.target.value;
              })}
              placeholder="https://api.openai.com/v1"
            />,
          )}

          {currentValue.provider === 'custom' && customNameConfig.visible && renderFieldShell(
            `${t('llm.customNameLabel')}${customNameConfig.required ? '' : t('llm.optional')}`,
            ['llm', 'custom_name'],
            customNameConfig.required ? [{ required: true, message: t('llm.customNameRequired') }] : undefined,
            <Input
              value={currentValue.custom_name || ''}
              onChange={(event) => updateValue((draft) => {
                draft.custom_name = event.target.value;
              })}
              placeholder={customNameConfig.placeholder || t('llm.customNamePlaceholder')}
            />,
          )}

          {currentValue.provider === 'custom' && apiFormatConfig.visible && renderFieldShell(
            `${t('llm.apiFormatLabel')}${apiFormatConfig.required ? '' : t('llm.optional')}`,
            ['llm', 'api_format'],
            apiFormatConfig.required ? [{ required: true, message: t('llm.apiFormatRequired') }] : undefined,
            <SelectField
              value={currentValue.api_format}
              onChange={(nextValue) => updateValue((draft) => {
                draft.api_format = nextValue as LLMConfig['api_format'];
              })}
              allowEmpty={false}
              options={(apiFormatConfig.options || ['openai', 'anthropic', 'custom']).map((nextValue) => ({
                label:
                  nextValue === 'openai'
                    ? t('llm.apiFormatOptions.openai')
                    : nextValue === 'anthropic'
                      ? t('llm.apiFormatOptions.anthropic')
                      : nextValue === 'custom'
                        ? t('llm.apiFormatOptions.custom')
                        : nextValue,
                value: nextValue,
              }))}
            />,
          )}
        </div>

        <div className="mt-5 rounded-2xl border border-primary-500/15 bg-background/80 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary-700/80">{t('llm.summaryEyebrow')}</p>
              <h3 className="mt-1 text-xl font-semibold text-foreground">{currentValue.model || t('llm.modelPlaceholder')}</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {currentValue.capability_override_enabled ? t('llm.summaryOverride') : t('llm.summaryDefault')}
              </p>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border border-border bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
              <Settings2 className="h-3.5 w-3.5" />
              {currentValue.capability_override_enabled ? t('llm.overrideEnabled') : t('llm.overrideDisabled')}
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {capabilitySummary.map((item) => {
              const enabled = currentValue.capabilities[item.key];
              return (
                <div
                  key={item.key}
                  className={cn(
                    'rounded-2xl border px-3 py-3 transition-colors',
                    enabled ? 'border-primary-500/30 bg-primary-50/60 text-primary-900' : 'border-border bg-muted/30 text-muted-foreground'
                  )}
                >
                  <div className="flex items-center gap-2 text-sm font-medium">
                    {capabilityIcon(item.key)}
                    <span>{item.label}</span>
                  </div>
                  <div className="mt-2 text-xs">
                    {enabled ? t('llm.capabilityEnabled') : t('llm.capabilityDisabled')}
                    {item.helper ? ` · ${item.helper}` : ''}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 flex flex-wrap gap-3 text-xs text-muted-foreground">
            <span>{t('llm.contextWindowLabelShort')}: {currentValue.limits.context_window || t('llm.notSet')}</span>
            <span>{t('llm.maxOutputTokensLabelShort')}: {currentValue.limits.max_output_tokens || t('llm.notSet')}</span>
          </div>

          {!currentValue.capabilities.tool_calling && (
            <div className="mt-4 rounded-xl border border-amber-400/35 bg-amber-50/80 px-3 py-2 text-sm text-amber-800">
              {t('llm.toolCallingWarning')}
            </div>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={() => setAdvancedOpen((prev) => !prev)}
        className="flex w-full items-center justify-between rounded-2xl border border-border/80 bg-background px-4 py-3 text-left transition hover:border-primary-500/30"
      >
        <div>
          <p className="text-sm font-medium text-foreground">{t('llm.advancedTitle')}</p>
          <p className="text-xs text-muted-foreground">{t('llm.advancedDesc')}</p>
        </div>
        {advancedOpen ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
      </button>

      {advancedOpen && (
        <div className="space-y-5 rounded-2xl border border-border/70 bg-muted/15 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/80 bg-background px-4 py-3">
            <div>
              <p className="text-sm font-medium text-foreground">{t('llm.overrideSwitchLabel')}</p>
              <p className="text-xs text-muted-foreground">{t('llm.overrideSwitchDesc')}</p>
            </div>
            <div className="flex items-center gap-3">
              <Switch
                checked={currentValue.capability_override_enabled}
                onCheckedChange={(checked) => updateValue((draft) => {
                  draft.capability_override_enabled = checked;
                  if (!checked) {
                    const defaults = buildModelDefaults(activeModel, customProvider, currentValue.provider);
                    draft.capabilities = defaults.capabilities;
                    draft.limits = defaults.limits;
                    draft.provider_options = defaults.provider_options;
                  }
                })}
              />
              <button
                type="button"
                onClick={() => updateValue((draft) => {
                  draft.capability_override_enabled = false;
                  const defaults = buildModelDefaults(activeModel, customProvider, currentValue.provider);
                  draft.capabilities = defaults.capabilities;
                  draft.limits = defaults.limits;
                  draft.provider_options = defaults.provider_options;
                })}
                className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t('llm.resetDefaults')}
              </button>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {capabilitySummary.map((item) => {
              const checked = currentValue.capabilities[item.key];
              const locked = !currentValue.capability_override_enabled;
              return (
                <div
                  key={item.key}
                  className={cn(
                    'rounded-2xl border px-4 py-3 transition-colors',
                    checked ? 'border-primary-500/30 bg-primary-50/40' : 'border-border bg-background'
                  )}
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        {capabilityIcon(item.key)}
                        <span>{item.label}</span>
                        {locked && <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{t('llm.defaultBadge')}</span>}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{locked ? t('llm.followModelPreset') : t('llm.customizedPreset')}</p>
                    </div>
                    <Switch
                      checked={checked}
                      disabled={locked}
                      onCheckedChange={(nextChecked) => updateValue((draft) => {
                        draft.capabilities[item.key] = nextChecked;
                      })}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm font-medium">{t('llm.contextWindowLabel')}</span>
              <Input
                type="number"
                disabled={!currentValue.capability_override_enabled}
                value={currentValue.limits.context_window ?? ''}
                onChange={(event) => updateValue((draft) => {
                  draft.limits.context_window = event.target.value ? Number(event.target.value) : null;
                })}
                placeholder="204800"
              />
            </label>
            <label className="space-y-2">
              <span className="text-sm font-medium">{t('llm.maxOutputTokensLabel')}</span>
              <Input
                type="number"
                disabled={!currentValue.capability_override_enabled}
                value={currentValue.limits.max_output_tokens ?? ''}
                onChange={(event) => updateValue((draft) => {
                  draft.limits.max_output_tokens = event.target.value ? Number(event.target.value) : null;
                })}
                placeholder="131072"
              />
            </label>
          </div>

          <label className="space-y-2">
            <span className="text-sm font-medium">{t('llm.providerOptionsLabel')}</span>
            <textarea
              value={providerOptionsDraft}
              onChange={(event) => commitProviderOptions(event.target.value)}
              disabled={!currentValue.capability_override_enabled}
              className={cn(
                'min-h-[180px] w-full rounded-2xl border border-input bg-background px-4 py-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-600/60',
                !currentValue.capability_override_enabled && 'cursor-not-allowed opacity-70'
              )}
            />
            <p className="text-xs text-muted-foreground">{t('llm.providerOptionsHint')}</p>
            {providerOptionsError && (
              <p className="text-xs text-destructive">{providerOptionsError}</p>
            )}
          </label>
        </div>
      )}
    </div>
  );
};

export default LLMForm;
