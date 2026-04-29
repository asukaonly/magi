import { useTranslation } from 'react-i18next';

import { Switch } from '@/components/ui/switch';
import type { LLMModelMetadataOverride } from '@/api/modules/config';
import type { ProviderWorkbenchModelItem } from '@/components/config-forms/llm-provider-workbench-models';
import { cn } from '@/lib/utils';

interface LLMProviderChatModelFieldsProps {
  model: ProviderWorkbenchModelItem;
  modelOverride?: LLMModelMetadataOverride;
  isSettingsSurface: boolean;
  onModelOverrideChange: (modelId: string, updater: (draft: LLMModelMetadataOverride) => void) => void;
}

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

export function LLMProviderChatModelFields({
  model,
  modelOverride,
  isSettingsSurface,
  onModelOverrideChange,
}: LLMProviderChatModelFieldsProps) {
  const { t } = useTranslation('onboarding');

  return (
    <>
      <div className={cn('grid gap-3', !isSettingsSurface && 'md:grid-cols-2 xl:grid-cols-3')}>
        {([
          ['vision', t('llm.modelFields.vision')],
          ['tool_calling', t('llm.modelFields.toolCalling')],
          ['reasoning', t('llm.modelFields.reasoning')],
        ] as const).map(([field, label]) => {
          const checked = Boolean(modelOverride?.capabilities?.[field] ?? model.capabilities[field]);

          return (
            <div
              key={field}
              className="flex items-center justify-between rounded-xl bg-background/80 px-3 py-2.5"
            >
              <span className="text-sm text-foreground">{label}</span>
              <Switch
                aria-label={label}
                checked={checked}
                onCheckedChange={(nextValue) =>
                  onModelOverrideChange(model.id, (draft) => {
                    draft.capabilities = { ...(draft.capabilities || {}), [field]: nextValue };
                  })
                }
              />
            </div>
          );
        })}
      </div>

      <div className={cn('grid gap-4', !isSettingsSurface && 'lg:grid-cols-3')}>
        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.modelFields.contextWindow')}</span>
          <div className="relative">
            <input
              aria-label={t('llm.modelFields.contextWindow')}
              className={cn(fieldClassName, 'pr-8', isSettingsSurface && 'rounded-lg')}
              type="number"
              min={1}
              step={1}
              value={((modelOverride?.limits?.context_window ?? model.limits.context_window) ?? 0) / 1000 || ''}
              onChange={(event) =>
                onModelOverrideChange(model.id, (draft) => {
                  const nextValue = event.target.value.trim();
                  draft.limits = {
                    ...(draft.limits || {}),
                    context_window: nextValue ? Number(nextValue) * 1000 : undefined,
                  };
                })
              }
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">K</span>
          </div>
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.modelFields.maxOutputTokens')}</span>
          <div className="relative">
            <input
              aria-label={t('llm.modelFields.maxOutputTokens')}
              className={cn(fieldClassName, 'pr-8', isSettingsSurface && 'rounded-lg')}
              type="number"
              min={1}
              step={1}
              value={((modelOverride?.limits?.max_output_tokens ?? model.limits.max_output_tokens) ?? 0) / 1000 || ''}
              onChange={(event) =>
                onModelOverrideChange(model.id, (draft) => {
                  const nextValue = event.target.value.trim();
                  draft.limits = {
                    ...(draft.limits || {}),
                    max_output_tokens: nextValue ? Number(nextValue) * 1000 : undefined,
                  };
                })
              }
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">K</span>
          </div>
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.modelFields.maxConcurrency')}</span>
          <input
            aria-label={t('llm.modelFields.maxConcurrency')}
            className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
            type="number"
            min={1}
            step={1}
            value={modelOverride?.limits?.max_concurrency ?? model.limits.max_concurrency ?? ''}
            onChange={(event) =>
              onModelOverrideChange(model.id, (draft) => {
                const nextValue = event.target.value.trim();
                draft.limits = {
                  ...(draft.limits || {}),
                  max_concurrency: nextValue ? Number(nextValue) : undefined,
                };
              })
            }
          />
        </label>
      </div>
    </>
  );
}