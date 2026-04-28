import { XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { LLMModelMetadataOverride } from '@/api/modules/config';
import type { ProviderWorkbenchModelItem } from '@/components/config-forms/llm-provider-workbench-models';
import { cn } from '@/lib/utils';

interface LLMProviderEmbeddingModelFieldsProps {
  model: ProviderWorkbenchModelItem;
  modelOverride?: LLMModelMetadataOverride;
  isSettingsSurface: boolean;
  onModelOverrideChange: (modelId: string, updater: (draft: LLMModelMetadataOverride) => void) => void;
}

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

export function LLMProviderEmbeddingModelFields({
  model,
  modelOverride,
  isSettingsSurface,
  onModelOverrideChange,
}: LLMProviderEmbeddingModelFieldsProps) {
  const { t } = useTranslation('onboarding');
  const dimensionsValue = modelOverride?.dimensions ?? model.dimensions;

  const addDimension = (rawValue: string): 'empty' | 'invalid' | 'handled' => {
    const raw = rawValue.trim();
    if (!raw) {
      return 'empty';
    }
    const parsed = Math.floor(Number(raw));
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return 'invalid';
    }

    onModelOverrideChange(model.id, (draft) => {
      draft.capabilities = {
        ...(draft.capabilities || {}),
        embedding: true,
      };
      const current = dimensionsValue || [];
      if (!current.includes(parsed)) {
        draft.dimensions = [...current, parsed];
      }
    });
    return 'handled';
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <span className="text-sm font-medium">{t('llm.modelFields.dimensions')}</span>
        <div
          className={cn(
            'flex flex-wrap items-center gap-2 rounded-xl bg-background/80 p-2 ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
            isSettingsSurface && 'rounded-lg'
          )}
        >
          {(dimensionsValue || []).map((dimension, index) => (
            <span
              key={`${dimension}-${index}`}
              className="inline-flex items-center gap-1.5 rounded-full bg-muted/80 py-1 pl-3 pr-1 text-sm text-foreground"
            >
              <span className="tabular-nums">{dimension}</span>
              <button
                type="button"
                aria-label={t('llm.modelFields.dimensionsRemove', { value: dimension })}
                onClick={() =>
                  onModelOverrideChange(model.id, (draft) => {
                    draft.capabilities = {
                      ...(draft.capabilities || {}),
                      embedding: true,
                    };
                    const next = (dimensionsValue || []).filter((_value, position) => position !== index);
                    draft.dimensions = next.length ? next : null;
                  })
                }
                className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition hover:bg-background hover:text-foreground"
              >
                <XCircle className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
          <input
            aria-label={t('llm.modelFields.dimensionsAdd')}
            type="number"
            min={1}
            step={1}
            placeholder={t('llm.modelFields.dimensionsAddPlaceholder')}
            className="h-8 min-w-[120px] flex-1 bg-transparent px-2 text-sm focus-visible:outline-none"
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ',') {
                return;
              }
              event.preventDefault();
              if (addDimension(event.currentTarget.value) === 'handled') {
                event.currentTarget.value = '';
              }
            }}
            onBlur={(event) => {
              if (addDimension(event.target.value) !== 'empty') {
                event.target.value = '';
              }
            }}
          />
        </div>
        <span className="block text-xs text-muted-foreground">
          {t('llm.modelFields.dimensionsChipHint')}
        </span>
      </div>

      <label className="block space-y-2 sm:max-w-xs">
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
              draft.capabilities = {
                ...(draft.capabilities || {}),
                embedding: true,
              };
              draft.limits = {
                ...(draft.limits || {}),
                max_concurrency: nextValue ? Number(nextValue) : undefined,
              };
            })
          }
        />
      </label>
    </div>
  );
}