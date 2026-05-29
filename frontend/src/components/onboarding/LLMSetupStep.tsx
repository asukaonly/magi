import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  type LLMConfig,
  type LLMScenario,
  type LLMSelectionConfig,
} from '@/api/modules/config';
import { getRecommendedModels } from '@/constants/llm';
import LLMForm from '@/components/config-forms/LLMForm';

/**
 * Folded LLM setup step for the redesigned onboarding flow.
 *
 * This is a thin wrapper over {@link LLMForm} — the same component Settings
 * uses — so the provider config gets the real "test connection" handler,
 * model discovery, and (behind the advanced toggle) the real
 * `LLMModelSelectionSection`. LLMForm self-loads the provider catalog and
 * auto-normalizes model selections when a provider is added, so the onboarding
 * happy path needs no extra defaulting.
 *
 * The wrapper adds two onboarding-specific concerns on top of LLMForm:
 *   1. `onValid` — reports whether the config is ready to proceed (an enabled
 *      provider with an API key + core/context_decider selections). LLMForm's
 *      own validation only covers custom-provider model readiness, which is a
 *      different signal.
 *   2. The embedding-fallback hint, shown when the chosen core provider has no
 *      native embedding model (e.g. Anthropic) and no embedding selection is
 *      configured yet.
 */
export interface LLMSetupStepProps {
  value: LLMConfig;
  onChange: (next: LLMConfig) => void;
  onValid?: (valid: boolean) => void;
}

function isValidConfig(value: LLMConfig): boolean {
  const providers = value.providers ?? {};
  const selections = value.selections ?? ({} as Record<LLMScenario, LLMSelectionConfig>);

  const anyEnabledWithKey = Object.values(providers).some(
    (p) =>
      p?.enabled &&
      ((p.api_key?.length ?? 0) > 0 || (p.services?.chat?.api_key?.length ?? 0) > 0),
  );
  if (!anyEnabledWithKey) return false;
  if (!selections.core?.provider_id || !selections.core?.model) return false;
  if (!selections.context_decider?.provider_id || !selections.context_decider?.model) return false;
  return true;
}

/**
 * True when the core scenario points at a known provider that has no native
 * embedding model and the embedding scenario hasn't been given a model yet.
 * Looks up by the provider's `provider_type` (the template id used as the key
 * in RECOMMENDED_MODELS), falling back to the instance id.
 */
/**
 * True when any configured provider is a custom (OpenAI-compatible) provider.
 * Custom providers require the user to pick concrete models per scenario, so we
 * auto-expand the advanced model config when one is present.
 */
function hasCustomProvider(value: LLMConfig): boolean {
  return Object.values(value.providers ?? {}).some(
    (p) => p?.provider_type === 'custom',
  );
}

function showsEmbeddingFallback(value: LLMConfig): boolean {
  const coreProviderId = value.selections?.core?.provider_id;
  if (!coreProviderId) return false;
  if (value.selections?.embedding?.model) return false;
  const provider = value.providers?.[coreProviderId];
  const lookupKey = provider?.provider_type || coreProviderId;
  const recommended = getRecommendedModels(lookupKey);
  return recommended ? recommended.embedding === null : false;
}

export function LLMSetupStep({ value, onChange, onValid }: LLMSetupStepProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    onValid?.(isValidConfig(value));
  }, [value, onValid]);

  // Auto-expand the advanced model config once a custom provider appears —
  // custom providers can't be auto-defaulted from the catalog, so the user
  // must pick models per scenario. The user can still collapse it afterward.
  const customPresent = hasCustomProvider(value);
  useEffect(() => {
    if (customPresent) setShowAdvanced(true);
  }, [customPresent]);

  const showEmbeddingRow = showsEmbeddingFallback(value);

  return (
    <div className="flex flex-col gap-6">
      <LLMForm
        value={value}
        onChange={onChange}
        view={showAdvanced ? 'all' : 'providers'}
        quickMode
        surface="onboarding"
        showSectionIntro={false}
      />

      {showEmbeddingRow ? (
        <div
          data-testid="llm-setup-embedding-row"
          className="rounded border border-amber-400 bg-amber-50 p-4 dark:border-amber-600 dark:bg-amber-950/30"
        >
          <p className="text-sm text-amber-900 dark:text-amber-200">
            {t('llmSetup.embeddingFallbackHint')}
          </p>
        </div>
      ) : null}

      <button
        type="button"
        data-testid="llm-setup-advanced-toggle"
        className="self-start text-sm underline text-[#7d685a]"
        onClick={() => setShowAdvanced((current) => !current)}
      >
        {showAdvanced ? t('llmSetup.hideAdvanced') : t('llmSetup.showAdvanced')}
      </button>
    </div>
  );
}

export default LLMSetupStep;
