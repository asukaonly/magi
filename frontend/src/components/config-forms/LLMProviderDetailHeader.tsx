import { Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { LLMProviderTestMenu } from '@/components/config-forms/LLMProviderTestMenu';
import { ProviderIcon } from '@/components/config-forms/provider-icons';
import { Switch } from '@/components/ui/switch';
import type { LLMProviderConfig, LLMProviderRegistry, LLMScenario } from '@/api/modules/config';
import type { ProviderWorkbenchModelItem } from '@/components/config-forms/llm-provider-workbench-models';
import { cn } from '@/lib/utils';

interface LLMProviderDetailHeaderProps {
  providerId: string;
  provider: LLMProviderConfig;
  providerMeta?: LLMProviderRegistry['providers'][number];
  references: LLMScenario[];
  surface: 'onboarding' | 'settings';
  isSettingsSurface: boolean;
  isTesting: boolean;
  testableModels: ProviderWorkbenchModelItem[];
  selectedTestModelId: string;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onRemoveCustomProvider: (providerId: string) => void;
  onSelectedTestModelChange: (providerId: string, modelId: string) => void;
  onTestProviderConnection: (providerId: string, model: string) => void;
}

const providerKindBadgeClassName =
  'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground';

export function LLMProviderDetailHeader({
  providerId,
  provider,
  providerMeta,
  references,
  surface,
  isSettingsSurface,
  isTesting,
  testableModels,
  selectedTestModelId,
  onProviderChange,
  onRemoveCustomProvider,
  onSelectedTestModelChange,
  onTestProviderConnection,
}: LLMProviderDetailHeaderProps) {
  const { t } = useTranslation('onboarding');
  const displayName = provider.display_name || providerMeta?.display_name || providerId;

  return (
    <div className={cn('space-y-3', isSettingsSurface && 'space-y-4 border-b border-[hsl(var(--settings-subnav-border)/0.72)] pb-5')}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="flex items-start gap-3">
            <ProviderIcon
              providerId={provider.provider_type}
              iconName={providerMeta?.icon || (provider.provider_type === 'custom' ? 'custom' : undefined)}
              displayName={displayName}
              className="mt-0.5"
            />
            <div className="space-y-2">
              <h4 className={cn('text-xl font-semibold tracking-[-0.01em] text-foreground', isSettingsSurface && 'text-lg')}>
                {displayName}
              </h4>
              <div className="flex flex-wrap items-center gap-2">
                <span className={providerKindBadgeClassName}>
                  {provider.provider_type === 'custom'
                    ? t('llm.providerConfiguration.providerKinds.custom')
                    : t('llm.providerConfiguration.providerKinds.builtin')}
                </span>
              </div>
            </div>
          </div>
          {references.length > 0 ? (
            <p className="text-xs leading-5 text-muted-foreground">
              {t('llm.providerConfiguration.referencedBy')}:{' '}
              {references.map((scenario) => t(`llm.scenarios.${scenario}.title`)).join(' / ')}
            </p>
          ) : null}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2.5 lg:justify-end">
          {provider.provider_type === 'custom' ? (
            <button
              type="button"
              onClick={() => onRemoveCustomProvider(providerId)}
              className="inline-flex min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-md border border-destructive/18 bg-transparent px-3 py-2.5 text-sm font-medium text-destructive/85 transition hover:bg-destructive/6 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
              <span>{t('llm.actions.removeProvider')}</span>
            </button>
          ) : null}
          <div className="inline-flex min-w-fit items-center gap-2 whitespace-nowrap rounded-md bg-[hsl(var(--settings-shell-elevated)/0.58)] px-3 py-2 text-[hsl(var(--settings-nav-foreground))]">
            <span className="whitespace-nowrap text-sm font-medium text-foreground/88">{t('llm.fields.enabled')}</span>
            <Switch
              aria-label={t('llm.fields.enabled')}
              checked={provider.enabled}
              disabled={surface !== 'onboarding' && references.length > 0}
              onCheckedChange={(checked) =>
                onProviderChange(providerId, (draftProvider) => {
                  draftProvider.enabled = checked;
                })
              }
            />
          </div>
          <LLMProviderTestMenu
            providerId={providerId}
            isTesting={isTesting}
            testableModels={testableModels}
            selectedModelId={selectedTestModelId}
            onSelectedModelChange={onSelectedTestModelChange}
            onTestProviderConnection={onTestProviderConnection}
          />
        </div>
      </div>
    </div>
  );
}