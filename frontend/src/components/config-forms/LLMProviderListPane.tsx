import { Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { ProviderIcon } from '@/components/config-forms/provider-icons';
import type { LLMProviderConfig, LLMProviderRegistry } from '@/api/modules/config';
import { cn } from '@/lib/utils';

interface LLMProviderListItem {
  providerId: string;
  provider: LLMProviderConfig;
}

interface LLMProviderListPaneProps {
  registry: LLMProviderRegistry;
  providerItems: LLMProviderListItem[];
  activeProviderId: string;
  isSettingsSurface: boolean;
  onActiveProviderChange: (providerId: string) => void;
  onAddCustomProvider: () => void;
}

export function LLMProviderListPane({
  registry,
  providerItems,
  activeProviderId,
  isSettingsSurface,
  onActiveProviderChange,
  onAddCustomProvider,
}: LLMProviderListPaneProps) {
  const { t } = useTranslation('onboarding');

  return (
    <div
      data-testid="llm-provider-list-pane"
      className={cn(
        'min-h-0 space-y-1.5 overflow-y-auto rounded-[24px] bg-background/55 p-2 sm:p-3',
        isSettingsSurface &&
          'flex min-h-0 flex-col border-r border-[hsl(var(--settings-subnav-border)/0.72)] bg-transparent p-0 pr-5'
      )}
    >
      <div className={cn('space-y-1.5', isSettingsSurface && 'flex-1 space-y-1 overflow-y-auto pr-1')}>
        {providerItems.map(({ providerId, provider }) => {
          const providerMeta =
            provider.provider_type === 'custom'
              ? undefined
              : registry.providers.find((item) => item.id === provider.provider_type);

          return (
            <button
              key={providerId}
              type="button"
              onClick={() => onActiveProviderChange(providerId)}
              aria-current={providerId === activeProviderId ? 'page' : undefined}
              className={cn(
                'relative flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left transition ring-1 ring-inset focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                providerId === activeProviderId
                  ? 'bg-primary/15 text-foreground ring-primary/70'
                  : 'text-muted-foreground ring-transparent hover:bg-background/70 hover:text-foreground hover:ring-border/50',
                isSettingsSurface &&
                  (providerId === activeProviderId
                    ? 'rounded-md bg-[hsl(var(--settings-nav-active)/0.56)] ring-0 shadow-none'
                    : 'rounded-md bg-transparent ring-0 shadow-none hover:bg-[hsl(var(--settings-shell-elevated)/0.4)]')
              )}
            >
              {isSettingsSurface && providerId === activeProviderId ? (
                <span
                  aria-hidden="true"
                  className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-[hsl(var(--settings-nav-active-foreground)/0.65)]"
                />
              ) : null}
              <ProviderIcon
                providerId={provider.provider_type}
                iconName={providerMeta?.icon || (provider.provider_type === 'custom' ? 'custom' : undefined)}
                displayName={provider.display_name || providerMeta?.display_name || providerId}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold tracking-[0.01em] text-foreground sm:text-base">
                  {provider.display_name || providerMeta?.display_name || providerId}
                </div>
              </div>
              <span className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={cn(
                    'h-2.5 w-2.5 rounded-full',
                    providerId === activeProviderId
                      ? provider.enabled
                        ? 'bg-[hsl(var(--settings-nav-active-foreground)/0.9)]'
                        : 'bg-[hsl(var(--settings-nav-foreground)/0.45)]'
                      : provider.enabled
                        ? 'bg-emerald-500'
                        : 'bg-border'
                  )}
                />
                <span className="sr-only">
                  {provider.enabled ? t('llm.badges.enabled') : t('llm.badges.disabled')}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {isSettingsSurface ? (
        <div className="mt-4 border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-4 pr-1">
          <button
            type="button"
            onClick={onAddCustomProvider}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-[hsl(var(--settings-subnav-border)/0.9)] bg-transparent px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-[hsl(var(--settings-shell-elevated)/0.4)]"
          >
            <Plus className="h-4 w-4" />
            <span>{t('llm.actions.addCustomProvider')}</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}

export type { LLMProviderListItem };