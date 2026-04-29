import { Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { LLMScenario, LLMSelectionConfig } from '@/api/modules/config';
import { SelectField } from '@/components/config-forms/fields';
import { cn } from '@/lib/utils';

interface RemoteEmbeddingModelOption {
  providerId: string;
  providerName: string;
  modelId: string;
  modelLabel: string;
  dimensions: number[];
}

interface LLMRemoteEmbeddingModelSelectorProps {
  scenario: LLMScenario;
  selection: LLMSelectionConfig;
  embeddingModels: RemoteEmbeddingModelOption[];
  inputClassName: string;
  isSettingsSurface: boolean;
  onScenarioProviderChange: (scenario: LLMScenario, providerId: string) => void;
  onScenarioModelChange: (scenario: LLMScenario, model: string) => void;
  onScenarioEmbeddingDimensionChange: (
    scenario: LLMScenario,
    dimension: number | null,
    source?: 'model-sync' | 'manual'
  ) => void;
}

export function LLMRemoteEmbeddingModelSelector({
  scenario,
  selection,
  embeddingModels,
  inputClassName,
  isSettingsSurface,
  onScenarioProviderChange,
  onScenarioModelChange,
  onScenarioEmbeddingDimensionChange,
}: LLMRemoteEmbeddingModelSelectorProps) {
  const { t } = useTranslation('onboarding');
  const currentEmbeddingModel = embeddingModels.find(
    (model) => model.providerId === selection.provider_id && model.modelId === selection.model
  );
  const activeEmbeddingModel = currentEmbeddingModel || embeddingModels[0];
  const availableDimensions = activeEmbeddingModel?.dimensions || [];
  const selectedDimension =
    availableDimensions.includes(selection.embedding_dimension || -1)
      ? selection.embedding_dimension
      : (availableDimensions[0] ?? null);

  if (embeddingModels.length === 0) {
    return (
      <div
        className={cn(
          'flex items-start gap-2 rounded-lg border border-info/40 bg-info/5 px-3 py-2.5 text-sm text-info-foreground',
          isSettingsSurface && 'rounded-none border-x-0 border-b-0 border-t border-[hsl(var(--settings-subnav-border)/0.72)] bg-transparent px-0 pb-0 pt-4 text-muted-foreground'
        )}
      >
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{t('llm.modelSelection.noEmbeddingModels')}</span>
      </div>
    );
  }

  return (
    <>
      <label className="space-y-2">
        <span className="text-sm font-medium">{t('llm.fields.model')}</span>
        <SelectField
          className="w-full"
          triggerClassName={inputClassName}
          value={selection.provider_id && selection.model ? `${selection.provider_id}::${selection.model}` : ''}
          allowEmpty={false}
          placeholder={t('llm.modelSelection.selectEmbeddingModel')}
          searchable
          searchThreshold={10}
          searchPlaceholder={t('llm.modelSelection.searchPlaceholder')}
          noResultsText={t('llm.modelSelection.noSearchResults')}
          options={embeddingModels.map((model) => ({
            label: `${model.modelLabel} (${model.providerName})`,
            value: `${model.providerId}::${model.modelId}`,
          }))}
          onChange={(nextValue) => {
            const [providerId, modelId] = nextValue.split('::');
            onScenarioProviderChange(scenario, providerId);
            onScenarioModelChange(scenario, modelId);
            const matched = embeddingModels.find(
              (item) => item.providerId === providerId && item.modelId === modelId
            );
            onScenarioEmbeddingDimensionChange(
              scenario,
              matched?.dimensions?.[0] ?? null,
              'model-sync'
            );
          }}
        />
      </label>

      <label className="space-y-2 mt-3">
        <span className="text-sm font-medium">{t('llm.fields.embeddingDimension')}</span>
        <SelectField
          className="w-full"
          triggerClassName={inputClassName}
          value={selectedDimension ? String(selectedDimension) : ''}
          allowEmpty={false}
          placeholder={t('llm.modelSelection.selectEmbeddingDimension')}
          options={availableDimensions.map((dimension) => ({
            label: String(dimension),
            value: String(dimension),
          }))}
          onChange={(nextValue) =>
            onScenarioEmbeddingDimensionChange(
              scenario,
              nextValue ? Number(nextValue) : null,
              'manual'
            )
          }
        />
      </label>
    </>
  );
}