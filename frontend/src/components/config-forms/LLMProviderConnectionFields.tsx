import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { LLMProviderApiKeyField } from '@/components/config-forms/LLMProviderApiKeyField';
import type { LLMProviderConfig, LLMProviderRegistry } from '@/api/modules/config';
import { cn } from '@/lib/utils';

interface LLMProviderConnectionFieldsProps {
  registry: LLMProviderRegistry;
  providerId: string;
  provider: LLMProviderConfig;
  providerMeta?: LLMProviderRegistry['providers'][number];
  isSettingsSurface: boolean;
  showApiKey: boolean;
  onShowApiKeyChange: (next: boolean | ((current: boolean) => boolean)) => void;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onProviderDefaultModelChange: (providerId: string, model: string) => void;
}

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

export function LLMProviderConnectionFields({
  registry,
  providerId,
  provider,
  providerMeta,
  isSettingsSurface,
  showApiKey,
  onShowApiKeyChange,
  onProviderChange,
  onProviderDefaultModelChange,
}: LLMProviderConnectionFieldsProps) {
  const { t } = useTranslation('onboarding');

  if (provider.provider_type !== 'custom') {
    return (
      <>
        <LLMProviderApiKeyField
          providerId={providerId}
          provider={provider}
          isSettingsSurface={isSettingsSurface}
          showApiKey={showApiKey}
          onShowApiKeyChange={onShowApiKeyChange}
          onProviderChange={onProviderChange}
        />

        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.fields.baseUrl')}</span>
          <input
            aria-label={t('llm.fields.baseUrl')}
            className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
            placeholder={providerMeta?.default_base_url || ''}
            value={provider.base_url || ''}
            onChange={(event) =>
              onProviderChange(providerId, (draftProvider) => {
                draftProvider.base_url = event.target.value;
              })
            }
          />
        </label>
      </>
    );
  }

  return (
    <>
      <label className="space-y-2">
        <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
        <input
          aria-label={t('llm.fields.displayName')}
          className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
          value={provider.display_name || ''}
          onChange={(event) =>
            onProviderChange(providerId, (draftProvider) => {
              draftProvider.display_name = event.target.value;
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
          value={provider.api_format || 'openai'}
          allowEmpty={false}
          options={(registry.custom_provider.fields?.api_format?.options || ['openai', 'anthropic']).map((option) => ({
            label: t(`llm.apiFormatOptions.${option}`),
            value: option,
          }))}
          onChange={(nextValue) =>
            onProviderChange(providerId, (draftProvider) => {
              draftProvider.api_format = nextValue as LLMProviderConfig['api_format'];
            })
          }
        />
      </label>

      <LLMProviderApiKeyField
        providerId={providerId}
        provider={provider}
        isSettingsSurface={isSettingsSurface}
        showApiKey={showApiKey}
        onShowApiKeyChange={onShowApiKeyChange}
        onProviderChange={onProviderChange}
      />

      <label className="space-y-2">
        <span className="text-sm font-medium">{t('llm.fields.baseUrl')}</span>
        <input
          aria-label={t('llm.fields.baseUrl')}
          className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
          value={provider.base_url || ''}
          onChange={(event) =>
            onProviderChange(providerId, (draftProvider) => {
              draftProvider.base_url = event.target.value;
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
              value={provider.custom_default_model || ''}
              disabled={!provider.custom_models?.length}
              placeholder={t('llm.providerConfiguration.defaultModelEmpty')}
              allowEmpty={false}
              options={(provider.custom_models || []).map((model) => ({
                label: model,
                value: model,
              }))}
              onChange={(nextValue) => onProviderDefaultModelChange(providerId, nextValue)}
            />
          </label>
        </div>
      </div>
    </>
  );
}