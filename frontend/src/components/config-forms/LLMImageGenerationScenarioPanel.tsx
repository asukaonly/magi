import { Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { LLMProviderConfig, LLMScenario, LLMSelectionConfig } from '@/api/modules/config';
import { SelectField } from '@/components/config-forms/fields';
import { cn } from '@/lib/utils';

interface ImageGenerationModelOption {
  providerId: string;
  providerName: string;
  modelId: string;
  modelLabel: string;
}

interface LLMImageGenerationScenarioPanelProps {
  scenario: LLMScenario;
  selection: LLMSelectionConfig;
  enabledProviders: Array<[string, LLMProviderConfig]>;
  imageGenerationModels: ImageGenerationModelOption[];
  quickMode: boolean;
  inputClassName: string;
  onScenarioProviderChange: (scenario: LLMScenario, providerId: string) => void;
  onScenarioModelChange: (scenario: LLMScenario, model: string) => void;
}

export function LLMImageGenerationScenarioPanel({
  scenario,
  selection,
  enabledProviders,
  imageGenerationModels,
  quickMode,
  inputClassName,
  onScenarioProviderChange,
  onScenarioModelChange,
}: LLMImageGenerationScenarioPanelProps) {
  const { t } = useTranslation('onboarding');
  const providerImageModels = imageGenerationModels.filter(
    (model) => model.providerId === (selection.provider_id || '')
  );

  return (
    <>
      <div className={cn('grid gap-3', quickMode ? 'lg:grid-cols-2' : 'md:grid-cols-2')}>
        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.fields.provider')}</span>
          <SelectField
            className="w-full"
            triggerClassName={inputClassName}
            value={selection.provider_id || ''}
            allowEmpty={false}
            options={enabledProviders.map(([providerId, enabledProvider]) => ({
              label: enabledProvider.display_name || providerId,
              value: providerId,
            }))}
            onChange={(nextValue) => onScenarioProviderChange(scenario, nextValue)}
          />
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.fields.model')}</span>
          {providerImageModels.length > 0 ? (
            <SelectField
              className="w-full"
              triggerClassName={inputClassName}
              value={selection.model || ''}
              allowEmpty={false}
              searchable
              searchThreshold={10}
              searchPlaceholder={t('llm.modelSelection.searchPlaceholder')}
              noResultsText={t('llm.modelSelection.noSearchResults')}
              options={providerImageModels.map((model) => ({
                label: model.modelLabel,
                value: model.modelId,
              }))}
              onChange={(nextValue) => onScenarioModelChange(scenario, nextValue)}
            />
          ) : (
            <div className={cn(inputClassName, 'flex items-center text-muted-foreground')}>
              {t('llm.providerConfiguration.imageModelsManaged')}
            </div>
          )}
        </label>
      </div>

      {!selection.provider_id || !selection.model ? (
        <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900/50 dark:bg-amber-950/30">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <p className="text-xs leading-5 text-amber-800 dark:text-amber-300">
            {t('llm.scenarios.image_generation.notConfiguredHint')}
          </p>
        </div>
      ) : null}
    </>
  );
}