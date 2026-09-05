import type { ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  resolveProviderModels,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type LLMSelectionConfig,
} from '@/api/modules/config';
import { SelectField } from '@/components/config-forms/fields';
import { cn } from '@/lib/utils';

interface LLMChatScenarioPanelProps {
  scenario: LLMScenario;
  selection: LLMSelectionConfig;
  provider?: LLMProviderConfig;
  enabledProviders: Array<[string, LLMProviderConfig]>;
  registry: LLMProviderRegistry;
  quickMode: boolean;
  inputClassName: string;
  isSettingsSurface: boolean;
  disabled?: boolean;
  advancedSettings: ReactNode;
  onScenarioProviderChange: (scenario: LLMScenario, providerId: string) => void;
  onScenarioModelChange: (scenario: LLMScenario, model: string) => void;
}

const compareOptionLabels = (left: { label: string; value: string }, right: { label: string; value: string }) => {
  const labelComparison = left.label.localeCompare(right.label, 'en', { sensitivity: 'base' });
  if (labelComparison !== 0) {
    return labelComparison;
  }
  return left.value.localeCompare(right.value, 'en', { sensitivity: 'base' });
};

export function LLMChatScenarioPanel({
  scenario,
  selection,
  provider,
  enabledProviders,
  registry,
  quickMode,
  inputClassName,
  isSettingsSurface,
  disabled = false,
  advancedSettings,
  onScenarioProviderChange,
  onScenarioModelChange,
}: LLMChatScenarioPanelProps) {
  const { t } = useTranslation('onboarding');
  const pluginProvider = registry.plugin_providers?.find((entry) => entry.provider_id === selection.provider_id);
  const isPluginSelection = !provider && selection.provider_id.includes(':');
  const unavailablePlugin = isPluginSelection && !pluginProvider;
  const providerOptions = [
    ...enabledProviders.map(([providerId, enabledProvider]) => ({
      label: enabledProvider.display_name || providerId,
      value: providerId,
    })),
    ...(registry.plugin_providers || []).map((entry) => ({
      label: t('llm.modelSelection.pluginProvider', { provider: entry.display_name }),
      value: entry.provider_id,
    })),
    ...(unavailablePlugin ? [{
      label: t('llm.modelSelection.pluginUnavailableOption', { provider: selection.provider_id }),
      value: selection.provider_id,
      disabled: true,
    }] : []),
  ];
  const models = provider
    ? resolveProviderModels(registry, selection.provider_id, provider).chat_models.filter((model) => !model.hidden)
    : [];
  const modelOptions = models
    .map((model) => ({
      label: model.label || model.id,
      value: model.id,
    }))
    .sort(compareOptionLabels);

  return (
    <>
      <div className={cn('grid gap-3', quickMode ? 'lg:grid-cols-2' : 'md:grid-cols-2')}>
        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.fields.provider')}</span>
          <SelectField
            className="w-full"
            ariaLabel={t('llm.fields.provider')}
            triggerClassName={inputClassName}
            value={selection.provider_id}
            disabled={disabled}
            allowEmpty={false}
            options={providerOptions}
            onChange={(nextValue) => onScenarioProviderChange(scenario, nextValue)}
          />
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium">{t('llm.fields.model')}</span>
          {models.length > 0 ? (
            <SelectField
              className="w-full"
              triggerClassName={inputClassName}
              value={selection.model}
              disabled={disabled}
              allowEmpty={false}
              searchable
              searchThreshold={10}
              searchPlaceholder={t('llm.modelSelection.searchPlaceholder')}
              noResultsText={t('llm.modelSelection.noSearchResults')}
              options={modelOptions}
              onChange={(nextValue) => onScenarioModelChange(scenario, nextValue)}
            />
          ) : (
            <input
              aria-label={t('llm.fields.model')}
              className={inputClassName}
              value={selection.model}
              disabled={disabled}
              placeholder={t('llm.modelManualPlaceholder')}
              onChange={(event) => onScenarioModelChange(scenario, event.target.value)}
            />
          )}
        </label>
      </div>

      {isPluginSelection ? (
        <p className="mt-3 text-xs text-muted-foreground" role={unavailablePlugin ? 'alert' : undefined}>
          {t(unavailablePlugin ? 'llm.modelSelection.pluginUnavailable' : 'llm.modelSelection.pluginManualModel')}
        </p>
      ) : advancedSettings}

      {scenario === 'core' && !selection.capabilities.vision ? (
        <div
          role="alert"
          className={cn(
            'mt-3 flex items-start gap-2 rounded-lg border border-amber-300/45 bg-amber-50/80 px-3 py-2.5 text-xs text-amber-900 shadow-[0_1px_2px_rgba(120,53,15,0.06)] dark:border-amber-300/30 dark:bg-amber-500/10 dark:text-amber-100',
            isSettingsSurface && 'rounded-md border border-amber-300/40 bg-amber-50/72 px-3 py-2.5 text-amber-900 shadow-none dark:border-amber-300/25 dark:bg-amber-500/10 dark:text-amber-100'
          )}
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('llm.warnings.coreVisionMissing')}</span>
        </div>
      ) : null}
    </>
  );
}
