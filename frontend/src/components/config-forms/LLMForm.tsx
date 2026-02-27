import React, { useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Brain, Eye, EyeOff, Info, Loader2, Sparkles, Wand2, Zap } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { SimpleForm as Form, FormContext } from '../onboarding/simple-form';
import { SelectField } from './fields';
import {
  configApi,
  type LLMCustomProviderMeta,
  type LLMProviderFieldConfig,
  type LLMProviderMeta,
  type LLMProviderRegistry,
} from '../../api/modules/config';

interface LLMFormProps {
  quickMode?: boolean;
}

const iconNode = (icon?: string): JSX.Element => {
  switch (icon) {
    case 'brain':
      return <Brain className="h-3.5 w-3.5 text-teal-600" />;
    case 'zap':
      return <Zap className="h-3.5 w-3.5 text-teal-600" />;
    case 'wand':
      return <Wand2 className="h-3.5 w-3.5 text-teal-600" />;
    case 'sparkles':
    default:
      return <Sparkles className="h-3.5 w-3.5 text-teal-600" />;
  }
};

// Get i18n text for provider
const getProviderI18n = (providerId: string) => {
  const i18nMap: Record<string, { name: string; desc: string }> = {
    openai: { name: 'llm.providers.openai.name', desc: 'llm.providers.openai.desc' },
    anthropic: { name: 'llm.providers.anthropic.name', desc: 'llm.providers.anthropic.desc' },
    glm: { name: 'llm.providers.glm.name', desc: 'llm.providers.glm.desc' },
    custom: { name: 'llm.providers.custom.name', desc: 'llm.providers.custom.desc' },
  };
  return i18nMap[providerId] || { name: providerId, desc: '' };
};

const selectableStyle = (active: boolean): string =>
  cn(
    'rounded-xl border bg-background p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600/60',
    active ? 'border-teal-600 bg-teal-600/5 shadow-sm' : 'border-border hover:border-teal-600/40'
  );

const fieldConfig = (
  provider: LLMProviderMeta | LLMCustomProviderMeta | undefined,
  fieldName: string,
  fallback: LLMProviderFieldConfig
): LLMProviderFieldConfig => provider?.fields?.[fieldName] || fallback;

export const LLMForm: React.FC<LLMFormProps> = ({ quickMode = false }) => {
  const { t } = useTranslation('onboarding');
  const [registry, setRegistry] = useState<LLMProviderRegistry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);
  const formCtx = useContext(FormContext);

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

  const providers = useMemo(() => registry?.providers || [], [registry?.providers]);
  const customProvider = useMemo(
    () => registry?.custom_provider || { enabled: false },
    [registry?.custom_provider]
  );

  // Track if we've set the initial model
  const initializedRef = useRef(false);

  // Set default model and fix case mismatch when registry loads
  useEffect(() => {
    if (!registry || loading || !formCtx?.instance) return;
    if (initializedRef.current) return;

    // Small delay to ensure form values are ready
    const timer = setTimeout(() => {
      if (initializedRef.current) return;

      const currentProvider = formCtx.values?.llm?.provider;
      const currentModel = formCtx.values?.llm?.model;

      if (currentProvider) {
        const selected = providers.find((p) => p.id === currentProvider);
        if (selected?.model_options?.length) {
          if (!currentModel) {
            // No model set, use default
            if (selected.default_model) {
              formCtx.instance.setFieldValue?.(['llm', 'model'], selected.default_model);
            }
          } else {
            // Fix case mismatch: find matching option (case-insensitive) and use the correct value
            const matchedOption = selected.model_options.find(
              (opt) => opt.toLowerCase() === currentModel.toLowerCase()
            );
            if (matchedOption && matchedOption !== currentModel) {
              formCtx.instance.setFieldValue?.(['llm', 'model'], matchedOption);
            }
          }
        }
      }

      initializedRef.current = true;
    }, 0);

    return () => clearTimeout(timer);
  }, [registry, loading, formCtx?.instance, formCtx?.values?.llm, providers]);

  // Check if LLM config is from environment variables
  // Masked API key format: "sk-abc****" (first 6 chars + ****)
  const fromEnv = formCtx?.values?.llm?.from_env ?? false;
  const currentApiKey = formCtx?.values?.llm?.api_key;
  const hasEnvApiKey = fromEnv && currentApiKey && currentApiKey.endsWith('****');

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-teal-600" />
        <span className="ml-2 text-muted-foreground">{t('llm.loading')}</span>
      </div>
    );
  }

  // Error state - backend unavailable
  if (error || !registry) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
        <AlertCircle className="h-8 w-8 text-destructive" />
        <p className="text-destructive font-medium">{error || t('llm.loadFailed')}</p>
        <p className="text-sm text-muted-foreground">{t('llm.loadFailedDesc')}</p>
      </div>
    );
  }

  return (
    <>
      {fromEnv && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-teal-600/30 bg-teal-600/10 px-3 py-2 text-sm text-teal-700">
          <Info className="h-4 w-4 flex-shrink-0" />
          <span>{t('llm.fromEnvHint')}</span>
        </div>
      )}

      <Form.Item label={t('llm.providerLabel')} name={['llm', 'provider']} rules={[{ required: true, message: t('llm.providerRequired') }]}>
        <Form.Item noStyle shouldUpdate>
          {({
            getFieldValue,
            setFieldValue,
          }: {
            getFieldValue: (name: any) => any;
            setFieldValue: (name: any, value: any) => void;
          }) => {
            const activeProvider = getFieldValue(['llm', 'provider']);

            const applyProvider = (providerId: string) => {
              const selected = providers.find((item) => item.id === providerId);
              setFieldValue(['llm', 'provider'], providerId);
              if (selected?.default_model) {
                setFieldValue(['llm', 'model'], selected.default_model);
              }
              if (selected?.default_base_url) {
                setFieldValue(['llm', 'base_url'], selected.default_base_url);
              }
            };

            return (
              <div className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-3">
                  {providers.map((provider) => {
                    const i18n = getProviderI18n(provider.id);
                    return (
                      <button
                        type="button"
                        key={provider.id}
                        onClick={() => applyProvider(provider.id)}
                        className={cn(
                          selectableStyle(activeProvider === provider.id),
                          'flex min-h-[78px] flex-col justify-center px-4'
                        )}
                      >
                        <div className="mb-1 flex items-center justify-center gap-2 text-lg font-semibold text-foreground">
                          {iconNode(provider.icon)}
                          {t(i18n.name)}
                        </div>
                        <p className="text-center text-xs text-muted-foreground">{t(i18n.desc)}</p>
                      </button>
                    );
                  })}
                </div>

                {customProvider.enabled && (
                  <button
                    type="button"
                    onClick={() => {
                      setFieldValue(['llm', 'provider'], 'custom');
                    }}
                    className={cn(
                      'mt-2 inline-flex items-center gap-2 rounded-lg border border-dashed px-4 py-2.5 text-base',
                      activeProvider === 'custom'
                        ? 'border-teal-500 bg-teal-50 text-teal-800'
                        : 'border-muted-foreground/45 bg-muted/20 text-foreground/90 hover:border-teal-500/60 hover:bg-teal-50/40'
                    )}
                  >
                    {iconNode(customProvider.icon)}
                    <span className="font-semibold">
                      {t('llm.providers.custom.name')}
                    </span>
                  </button>
                )}
              </div>
            );
          }}
        </Form.Item>
      </Form.Item>

      <Form.Item noStyle shouldUpdate>
        {({ getFieldValue, setFieldValue }: { getFieldValue: (name: any) => any; setFieldValue: (name: any, value: any) => void }) => {
          const activeProvider = getFieldValue(['llm', 'provider']);
          const currentModel = getFieldValue(['llm', 'model']);
          const activeMeta =
            activeProvider === 'custom'
              ? customProvider
              : providers.find((provider) => provider.id === activeProvider);
          const modelConfig = fieldConfig(activeMeta, 'model', { visible: true, required: true });
          const apiKeyConfig = fieldConfig(activeMeta, 'api_key', { visible: true, required: true });
          const baseUrlConfig = fieldConfig(activeMeta, 'base_url', { visible: true, required: false });
          const customNameConfig = fieldConfig(activeMeta, 'custom_name', { visible: true, required: true });
          const apiFormatConfig = fieldConfig(activeMeta, 'api_format', { visible: true, required: true });
          const shouldShowModel = modelConfig.visible;
          const shouldShowBaseUrl = baseUrlConfig.visible;
          const optionalText = t('llm.optional');

          return (
            <div className="mt-5 rounded-xl border border-border/80 bg-muted/20 p-4">
              {shouldShowModel && (
                <Form.Item
                  label={t('llm.modelLabel')}
                  name={['llm', 'model']}
                  rules={
                    modelConfig.required
                      ? [
                          { required: true, message: t('llm.modelRequired') },
                          {
                            validator: (_: any, value: string) => {
                              if (activeProvider === 'custom') return Promise.resolve();
                              const modelOptions = (activeMeta as LLMProviderMeta)?.model_options || [];
                              if (value && modelOptions.length && !modelOptions.includes(value)) {
                                return Promise.reject(new Error(t('llm.modelInvalid')));
                              }
                              return Promise.resolve();
                            },
                          },
                        ]
                      : undefined
                  }
                >
                  {(activeProvider !== 'custom' && (activeMeta as LLMProviderMeta)?.model_options?.length) ? (
                    <SelectField
                      value={currentModel}
                      onChange={(val) => setFieldValue(['llm', 'model'], val)}
                      allowEmpty={false}
                      placeholder={t('llm.modelPlaceholder')}
                      options={((activeMeta as LLMProviderMeta).model_options || []).map((item) => ({
                        label: item,
                        value: item,
                      }))}
                    />
                  ) : (
                    <Input placeholder="gpt-4o-mini" />
                  )}
                </Form.Item>
              )}

              {apiKeyConfig.visible && (
                <Form.Item
                  label="API Key"
                  name={['llm', 'api_key']}
                  rules={!hasEnvApiKey && apiKeyConfig.required ? [{ required: true, message: t('llm.apiKeyRequired') }] : undefined}
                >
                  <div className="relative">
                    <Input
                      type={hasEnvApiKey ? 'text' : (showApiKey ? 'text' : 'password')}
                      placeholder="sk-..."
                      readOnly={hasEnvApiKey}
                      className={hasEnvApiKey ? 'pr-10 bg-muted/50' : 'pr-10'}
                    />
                    {!hasEnvApiKey && (
                      <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        tabIndex={-1}
                      >
                        {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    )}
                  </div>
                </Form.Item>
              )}

              {shouldShowBaseUrl && (
                <Form.Item
                  label={`Base URL${baseUrlConfig.required ? '' : optionalText}`}
                  name={['llm', 'base_url']}
                  rules={baseUrlConfig.required ? [{ required: true, message: t('llm.baseUrlRequired') }] : undefined}
                >
                  <Input placeholder="https://api.openai.com/v1" />
                </Form.Item>
              )}

              {activeProvider === 'custom' && customNameConfig.visible && (
                <Form.Item
                  label={`${t('llm.customNameLabel')}${customNameConfig.required ? '' : optionalText}`}
                  name={['llm', 'custom_name']}
                  rules={customNameConfig.required ? [{ required: true, message: t('llm.customNameRequired') }] : undefined}
                >
                  <Input placeholder={customNameConfig.placeholder || (quickMode ? 'My Provider' : t('llm.customNamePlaceholder'))} />
                </Form.Item>
              )}

              {activeProvider === 'custom' && apiFormatConfig.visible && (
                <Form.Item
                  label={`${t('llm.apiFormatLabel')}${apiFormatConfig.required ? '' : optionalText}`}
                  name={['llm', 'api_format']}
                  rules={apiFormatConfig.required ? [{ required: true, message: t('llm.apiFormatRequired') }] : undefined}
                >
                  <SelectField
                    options={(apiFormatConfig.options || ['openai', 'anthropic', 'custom']).map((value) => ({
                      label:
                        value === 'openai'
                          ? t('llm.apiFormatOptions.openai')
                          : value === 'anthropic'
                            ? t('llm.apiFormatOptions.anthropic')
                            : value === 'custom'
                              ? t('llm.apiFormatOptions.custom')
                              : value,
                      value,
                    }))}
                  />
                </Form.Item>
              )}
            </div>
          );
        }}
      </Form.Item>
    </>
  );
};

export default LLMForm;
