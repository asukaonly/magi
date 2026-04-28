import { useTranslation } from 'react-i18next';

import type { LLMProviderConfig } from '@/api/modules/config';
import type { ProviderWorkbenchModelItem } from '@/components/config-forms/llm-provider-workbench-models';

type LLMProviderModelEditorKind = 'chat' | 'embedding' | 'image';

interface LLMProviderModelEditorHeaderProps {
  providerId: string;
  model: ProviderWorkbenchModelItem;
  activeKind: LLMProviderModelEditorKind;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onRemoveProviderModel: (providerId: string, model: string) => void;
}

const badgeClassName =
  'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground';

export function LLMProviderModelEditorHeader({
  providerId,
  model,
  activeKind,
  onProviderChange,
  onRemoveProviderModel,
}: LLMProviderModelEditorHeaderProps) {
  const { t } = useTranslation('onboarding');

  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <div className="text-base font-semibold text-foreground">{model.label}</div>
        <div className="text-xs text-muted-foreground">
          {t('llm.modelFields.modelId')}: {model.id}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className={badgeClassName}>
          {activeKind === 'embedding'
            ? t('llm.modelKinds.embedding')
            : activeKind === 'image'
            ? t('llm.modelKinds.image')
            : t('llm.modelKinds.chat')}
        </span>
        <span className={badgeClassName}>
          {model.source === 'manual'
            ? t('llm.providerConfiguration.providerKinds.custom')
            : t('llm.providerConfiguration.providerKinds.builtin')}
        </span>
        <button
          type="button"
          onClick={() =>
            onProviderChange(providerId, (provider) => {
              const overrides = { ...(provider.model_metadata_overrides || {}) };
              const previous = overrides[model.id];
              delete overrides[model.id];
              // Preserve embedding-kind marker for manual embedding-only models so they don't
              // disappear (manual embedding models live solely in the override map).
              if (
                previous?.capabilities?.embedding === true &&
                model.source === 'manual' &&
                !(provider.custom_models || []).includes(model.id)
              ) {
                overrides[model.id] = {
                  capabilities: { embedding: true },
                };
              }
              provider.model_metadata_overrides = overrides;
            })
          }
          className="inline-flex h-9 items-center justify-center rounded-md border border-border/70 px-3 text-sm text-foreground transition hover:bg-background/70"
        >
          {t('llm.actions.restoreModelDefaults')}
        </button>
        {model.source === 'manual' ? (
          <button
            type="button"
            onClick={() => onRemoveProviderModel(providerId, model.id)}
            className="inline-flex h-9 items-center justify-center rounded-md border border-destructive/25 px-3 text-sm text-destructive transition hover:bg-destructive/6"
          >
            {t('llm.actions.removeModel')}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export type { LLMProviderModelEditorKind };