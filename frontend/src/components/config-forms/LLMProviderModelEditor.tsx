import { useTranslation } from 'react-i18next';

import { LLMProviderChatModelFields } from '@/components/config-forms/LLMProviderChatModelFields';
import { LLMProviderEmbeddingModelFields } from '@/components/config-forms/LLMProviderEmbeddingModelFields';
import { LLMProviderImageModelFields } from '@/components/config-forms/LLMProviderImageModelFields';
import { LLMProviderModelEditorHeader, type LLMProviderModelEditorKind } from '@/components/config-forms/LLMProviderModelEditorHeader';
import type { LLMModelMetadataOverride, LLMProviderConfig } from '@/api/modules/config';
import type { ProviderWorkbenchModelItem } from '@/components/config-forms/llm-provider-workbench-models';
import { cn } from '@/lib/utils';

interface LLMProviderModelEditorProps {
  providerId: string;
  model?: ProviderWorkbenchModelItem;
  modelOverride?: LLMModelMetadataOverride;
  isSettingsSurface: boolean;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onRemoveProviderModel: (providerId: string, model: string) => void;
  onModelOverrideChange: (modelId: string, updater: (draft: LLMModelMetadataOverride) => void) => void;
}

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

function resolveModelEditorKind(model: ProviderWorkbenchModelItem): LLMProviderModelEditorKind {
  if (model.kinds.includes('image') && !model.kinds.includes('chat') && !model.kinds.includes('embedding')) {
    return 'image';
  }
  if (model.kinds.includes('embedding') && !model.kinds.includes('chat')) {
    return 'embedding';
  }
  return 'chat';
}

export function LLMProviderModelEditor({
  providerId,
  model,
  modelOverride,
  isSettingsSurface,
  onProviderChange,
  onRemoveProviderModel,
  onModelOverrideChange,
}: LLMProviderModelEditorProps) {
  const { t } = useTranslation('onboarding');

  return (
    <div
      data-testid="llm-provider-model-editor"
      className={cn(
        'space-y-4 rounded-[18px] bg-muted/25 p-4',
        isSettingsSurface && 'rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.22)]'
      )}
    >
      {model ? (
        <>
          <LLMProviderModelEditorHeader
            providerId={providerId}
            model={model}
            activeKind={resolveModelEditorKind(model)}
            onProviderChange={onProviderChange}
            onRemoveProviderModel={onRemoveProviderModel}
          />

          <div className="grid gap-4">
            <label className="space-y-2">
              <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
              <input
                aria-label={t('llm.fields.displayName')}
                className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                value={modelOverride?.label ?? model.label}
                onChange={(event) =>
                  onModelOverrideChange(model.id, (draft) => {
                    draft.label = event.target.value.trim() || undefined;
                  })
                }
              />
            </label>
          </div>

          {resolveModelEditorKind(model) === 'chat' ? (
            <LLMProviderChatModelFields
              model={model}
              modelOverride={modelOverride}
              isSettingsSurface={isSettingsSurface}
              onModelOverrideChange={onModelOverrideChange}
            />
          ) : resolveModelEditorKind(model) === 'embedding' ? (
            <LLMProviderEmbeddingModelFields
              model={model}
              modelOverride={modelOverride}
              isSettingsSurface={isSettingsSurface}
              onModelOverrideChange={onModelOverrideChange}
            />
          ) : (
            <LLMProviderImageModelFields />
          )}
        </>
      ) : (
        <div className="rounded-lg bg-background/80 px-3 py-3 text-sm text-muted-foreground">
          {t('llm.providerConfiguration.noModelSelected')}
        </div>
      )}
    </div>
  );
}