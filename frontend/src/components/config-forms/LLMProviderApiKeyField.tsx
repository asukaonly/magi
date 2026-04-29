import { Eye, EyeOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { LLMProviderConfig } from '@/api/modules/config';
import { cn } from '@/lib/utils';

interface LLMProviderApiKeyFieldProps {
  providerId: string;
  provider: LLMProviderConfig | undefined;
  isSettingsSurface: boolean;
  showApiKey: boolean;
  onShowApiKeyChange: (next: boolean | ((current: boolean) => boolean)) => void;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
}

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

export function LLMProviderApiKeyField({
  providerId,
  provider,
  isSettingsSurface,
  showApiKey,
  onShowApiKeyChange,
  onProviderChange,
}: LLMProviderApiKeyFieldProps) {
  const { t } = useTranslation('onboarding');
  const { t: appT } = useTranslation('app');

  return (
    <label className="space-y-2">
      <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
      <div className="relative">
        <input
          aria-label={t('llm.fields.apiKey')}
          className={cn(fieldClassName, 'pr-10', isSettingsSurface && 'rounded-lg')}
          type={showApiKey ? 'text' : 'password'}
          value={provider?.api_key || ''}
          onChange={(event) =>
            onProviderChange(providerId, (draftProvider) => {
              draftProvider.api_key = event.target.value;
            })
          }
        />
        <button
          type="button"
          onClick={() => onShowApiKeyChange((current) => !current)}
          className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent/50 hover:text-foreground"
          aria-label={showApiKey ? appT('settings.hideSensitiveValue') : appT('settings.showSensitiveValue')}
        >
          {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </label>
  );
}