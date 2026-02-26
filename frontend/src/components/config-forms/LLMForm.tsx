import React, { useEffect, useMemo, useState } from 'react';
import { Brain, Sparkles, Wand2, Zap } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { SimpleForm as Form } from '../onboarding/simple-form';
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

const FALLBACK_REGISTRY: LLMProviderRegistry = {
  providers: [
    {
      id: 'openai',
      display_name: 'OpenAI',
      description: '通用能力强，生态最完善',
      icon: 'sparkles',
      default_model: 'gpt-4o-mini',
      default_base_url: 'https://api.openai.com/v1',
      model_options: ['gpt-4o-mini', 'gpt-4.1', 'o3'],
      fields: {
        model: { visible: false, required: false },
        api_key: { visible: true, required: true },
        base_url: { visible: true, required: false },
      },
    },
    {
      id: 'anthropic',
      display_name: 'Anthropic',
      description: '长文本与复杂推理表现稳定',
      icon: 'brain',
      default_model: 'claude-3-5-sonnet',
      default_base_url: 'https://api.anthropic.com/v1',
      model_options: ['claude-3-5-sonnet', 'claude-3-7-sonnet', 'claude-opus-4-1'],
      fields: {
        model: { visible: false, required: false },
        api_key: { visible: true, required: true },
        base_url: { visible: true, required: false },
      },
    },
    {
      id: 'glm',
      display_name: 'GLM',
      description: '本地中文场景体验更友好',
      icon: 'zap',
      default_model: 'glm-4.5',
      default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
      model_options: ['glm-4.5', 'glm-4.5-air', 'glm-4.5-flash'],
      fields: {
        model: { visible: false, required: false },
        api_key: { visible: true, required: true },
        base_url: { visible: true, required: false },
      },
    },
  ],
  custom_provider: {
    enabled: true,
    display_name: '自定义 Provider',
    description: '接入兼容 OpenAI/Anthropic 或自定义格式的服务',
    icon: 'wand',
    fields: {
      custom_name: { visible: true, required: true, placeholder: 'My Provider' },
      api_format: { visible: true, required: true, options: ['openai', 'anthropic', 'custom'] },
      model: { visible: true, required: true },
      api_key: { visible: true, required: true },
      base_url: { visible: true, required: false },
    },
  },
};

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
  const [registry, setRegistry] = useState<LLMProviderRegistry>(FALLBACK_REGISTRY);

  useEffect(() => {
    const loadRegistry = async () => {
      try {
        const response = await configApi.getLLMProviders();
        if (response.data?.providers?.length) {
          setRegistry(response.data);
        }
      } catch {
        setRegistry(FALLBACK_REGISTRY);
      }
    };
    void loadRegistry();
  }, []);

  const providers = useMemo(() => registry.providers || FALLBACK_REGISTRY.providers, [registry.providers]);
  const customProvider = useMemo(
    () => registry.custom_provider || FALLBACK_REGISTRY.custom_provider,
    [registry.custom_provider]
  );

  return (
    <>
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
                  {providers.map((provider) => (
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
                        {provider.display_name}
                      </div>
                      <p className="text-center text-xs text-muted-foreground">{provider.description}</p>
                    </button>
                  ))}
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
                      {customProvider.display_name || t('llm.customProviderAction')}
                    </span>
                  </button>
                )}
              </div>
            );
          }}
        </Form.Item>
      </Form.Item>

      <Form.Item noStyle shouldUpdate>
        {({ getFieldValue }: { getFieldValue: (name: any) => any }) => {
          const activeProvider = getFieldValue(['llm', 'provider']);
          const activeMeta =
            activeProvider === 'custom'
              ? customProvider
              : providers.find((provider) => provider.id === activeProvider) || providers[0];
          const modelConfig = fieldConfig(activeMeta, 'model', { visible: true, required: true });
          const apiKeyConfig = fieldConfig(activeMeta, 'api_key', { visible: true, required: true });
          const baseUrlConfig = fieldConfig(activeMeta, 'base_url', { visible: true, required: false });
          const customNameConfig = fieldConfig(activeMeta, 'custom_name', { visible: true, required: true });
          const apiFormatConfig = fieldConfig(activeMeta, 'api_format', { visible: true, required: true });
          const shouldShowModel = modelConfig.visible;
          const shouldShowBaseUrl = baseUrlConfig.visible;
          const optionalText = '（可选）';

          return (
            <div className="mt-5 rounded-xl border border-border/80 bg-muted/20 p-4">
              {shouldShowModel && (
                <Form.Item
                  label={`${t('llm.modelLabel')}${modelConfig.required ? '' : optionalText}`}
                  name={['llm', 'model']}
                  rules={modelConfig.required ? [{ required: true, message: t('llm.modelRequired') }] : undefined}
                >
                  {(activeProvider !== 'custom' && (activeMeta as LLMProviderMeta)?.model_options?.length) ? (
                    <SelectField
                      allowEmpty={false}
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
                  label={`API Key${apiKeyConfig.required ? '' : optionalText}`}
                  name={['llm', 'api_key']}
                  rules={apiKeyConfig.required ? [{ required: true, message: t('llm.apiKeyRequired') }] : undefined}
                >
                  <Input type="password" placeholder="sk-..." />
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
