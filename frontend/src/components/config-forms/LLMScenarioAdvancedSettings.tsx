import { useTranslation } from 'react-i18next';

import type { LLMScenario } from '@/api/modules/config';
import { cn } from '@/lib/utils';

interface ScenarioConcurrencyState {
  effectiveMaxConcurrency: number | null;
  sharedScenarios: LLMScenario[];
}

interface LLMScenarioAdvancedSettingsProps {
  scenario: LLMScenario;
  concurrencyState: ScenarioConcurrencyState;
  expanded: boolean;
  isSettingsSurface: boolean;
  inputClassName: string;
  onToggle: () => void;
  onMaxConcurrencyChange: (scenario: LLMScenario, value: number | null) => void;
}

export function LLMScenarioAdvancedSettings({
  scenario,
  concurrencyState,
  expanded,
  isSettingsSurface,
  inputClassName,
  onToggle,
  onMaxConcurrencyChange,
}: LLMScenarioAdvancedSettingsProps) {
  const { t } = useTranslation('onboarding');
  const sharedScenarioTitles = concurrencyState.sharedScenarios.map((sharedScenario) =>
    t(`llm.scenarios.${sharedScenario}.title`)
  );

  return (
    <div
      className={cn(
        'mt-3 space-y-3',
        isSettingsSurface ? 'pt-1' : 'border-t border-border/60 pt-3'
      )}
    >
      <button
        type="button"
        className="text-sm font-medium text-primary underline-offset-4 hover:underline"
        onClick={onToggle}
      >
        {expanded ? t('llm.hideAdvanced') : t('llm.showAdvanced')}
      </button>

      {expanded ? (
        <div className="space-y-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('llm.fields.maxConcurrency')}</span>
            <input
              aria-label={t('llm.fields.maxConcurrency')}
              className={inputClassName}
              type="number"
              min={1}
              step={1}
              value={
                concurrencyState.effectiveMaxConcurrency !== null
                  ? String(concurrencyState.effectiveMaxConcurrency)
                  : ''
              }
              placeholder={t('llm.modelSelection.maxConcurrencyPlaceholder')}
              onChange={(event) => {
                const nextValue = event.target.value.trim();
                onMaxConcurrencyChange(
                  scenario,
                  nextValue ? Number(nextValue) : null
                );
              }}
            />
          </label>
          <p className="text-xs leading-5 text-muted-foreground">
            {t('llm.modelSelection.maxConcurrencyHelp')}
          </p>
          {sharedScenarioTitles.length > 0 ? (
            <p className="text-xs leading-5 text-muted-foreground">
              {t('llm.modelSelection.sharedConcurrencyHint', {
                scenarios: sharedScenarioTitles.join(', '),
              })}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}