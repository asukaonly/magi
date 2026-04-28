import { useTranslation } from 'react-i18next';

import type { ProviderWorkbenchModelItem } from '@/components/config-forms/llm-provider-workbench-models';
import { cn } from '@/lib/utils';

interface LLMProviderModelListPaneProps {
  models: ProviderWorkbenchModelItem[];
  activeModelId?: string;
  isSettingsSurface: boolean;
  onSelectedModelChange: (modelId: string) => void;
}

const badgeClassName =
  'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground';

export function LLMProviderModelListPane({
  models,
  activeModelId,
  isSettingsSurface,
  onSelectedModelChange,
}: LLMProviderModelListPaneProps) {
  const { t } = useTranslation('onboarding');

  return (
    <div
      data-testid="llm-provider-model-list-pane"
      className={cn(
        'space-y-1.5 rounded-[18px] bg-muted/35 p-2',
        isSettingsSurface && 'rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.35)] p-2.5'
      )}
    >
      {models.length ? (
        models.map((model) => (
          <button
            key={model.id}
            type="button"
            onClick={() => onSelectedModelChange(model.id)}
            aria-current={activeModelId === model.id ? 'true' : undefined}
            className={cn(
              'relative w-full rounded-xl border px-3 py-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45',
              activeModelId === model.id
                ? 'border-border/70 bg-background text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.06)]'
                : 'border-transparent text-muted-foreground hover:border-border/45 hover:bg-background/70 hover:text-foreground',
              isSettingsSurface &&
                (activeModelId === model.id
                  ? 'rounded-md border-[hsl(var(--settings-subnav-border)/0.95)] bg-background/95 shadow-[0_2px_8px_rgba(15,23,42,0.04)]'
                  : 'rounded-md hover:bg-background/60')
            )}
          >
            {activeModelId === model.id ? (
              <span
                aria-hidden="true"
                className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-[hsl(var(--settings-nav-active-foreground)/0.7)]"
              />
            ) : null}
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{model.label}</div>
                <div className="truncate text-xs text-muted-foreground">{model.id}</div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {model.kinds.includes('chat') ? <span className={badgeClassName}>{t('llm.badges.chat')}</span> : null}
                {model.kinds.includes('embedding') ? <span className={badgeClassName}>{t('llm.badges.embedding')}</span> : null}
                {model.kinds.includes('image') ? <span className={badgeClassName}>{t('llm.badges.image')}</span> : null}
              </div>
            </div>
          </button>
        ))
      ) : (
        <div className="rounded-lg bg-background/80 px-3 py-3 text-sm text-muted-foreground">
          {t('llm.providerConfiguration.noEditableModels')}
        </div>
      )}
    </div>
  );
}