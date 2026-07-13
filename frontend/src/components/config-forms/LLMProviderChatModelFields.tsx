import { useTranslation } from 'react-i18next';

import { SelectField } from '@/components/config-forms/fields';
import { Switch } from '@/components/ui/switch';
import type { LLMModelMetadataOverride, ModelVendor } from '@/api/modules/config';
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

const selectTriggerClassName =
  'h-11 w-full rounded-xl border border-border/65 bg-background px-3 text-sm shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60';

const VENDOR_OPTIONS: ReadonlyArray<{ value: ModelVendor; labelKey: string }> = [
  { value: 'generic', labelKey: 'llm.modelFields.vendorOptions.generic' },
  { value: 'openai', labelKey: 'llm.modelFields.vendorOptions.openai' },
  { value: 'deepseek', labelKey: 'llm.modelFields.vendorOptions.deepseek' },
  { value: 'anthropic', labelKey: 'llm.modelFields.vendorOptions.anthropic' },
  { value: 'glm', labelKey: 'llm.modelFields.vendorOptions.glm' },
  { value: 'dashscope', labelKey: 'llm.modelFields.vendorOptions.dashscope' },
  { value: 'grok', labelKey: 'llm.modelFields.vendorOptions.grok' },
];

export function LLMProviderChatModelFields({
  model,
  modelOverride,
  isSettingsSurface,
  onModelOverrideChange,
}: LLMProviderChatModelFieldsProps) {
  const { t } = useTranslation('onboarding');

  const effectiveVendor: ModelVendor = (modelOverride?.vendor ?? model.vendor ?? 'generic') as ModelVendor;
  const vendorIsOverridden = modelOverride?.vendor != null;

  return (
    <>
      <label className="space-y-2">
        <span className="text-sm font-medium">{t('llm.modelFields.vendor')}</span>
        <SelectField
          ariaLabel={t('llm.modelFields.vendor')}
          className="w-full"
          triggerClassName={cn(selectTriggerClassName, isSettingsSurface && 'rounded-lg')}
          value={effectiveVendor}
          allowEmpty={false}
          options={VENDOR_OPTIONS.map((option) => ({
            label: t(option.labelKey),
            value: option.value,
          }))}
          onChange={(nextValue) =>
            onModelOverrideChange(model.id, (draft) => {
              const resolvedVendor = nextValue as ModelVendor;
              // Writing the same value as the underlying model.vendor still
              // marks an override; that's intentional so the API round-trip
              // preserves the user's explicit choice even if defaults change.
              draft.vendor = resolvedVendor;
            })
          }
        />
        <span className="block text-xs text-muted-foreground">
          {vendorIsOverridden
            ? t('llm.modelFields.vendorHint.overridden')
            : t('llm.modelFields.vendorHint.default')}
        </span>
      </label>

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

      </div>
    </>
  );
}
