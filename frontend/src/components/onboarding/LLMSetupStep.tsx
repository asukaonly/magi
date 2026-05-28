import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  type LLMConfig,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type LLMSelectionConfig,
  type TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
import {
  cloneLLMConfig,
  cloneProvider,
  cloneSelection,
} from '@/components/config-forms/llm-form-state';
import { LLMProviderConfigurationSection } from '@/components/config-forms/LLMProviderConfigurationSection';
import { getRecommendedModels } from '@/constants/llm';

/**
 * Folded LLM setup step for the redesigned onboarding flow.
 *
 * Wraps the existing {@link LLMProviderConfigurationSection} with two pieces
 * of "smart-defaulting" behavior:
 *
 *   1. When the user selects a known provider, recommended model selections
 *      for core / context_decider / embedding are auto-populated via
 *      {@link getRecommendedModels}.
 *   2. When the chosen provider has no native embedding model (e.g. Anthropic),
 *      an embedding-fallback hint row is surfaced so the user knows they need
 *      to configure a separate embedding provider.
 *
 * The component exposes a simplified `value` / `onChange` interface — the
 * granular handler protocol that `LLMProviderConfigurationSection` expects is
 * translated internally.
 */
export interface LLMSetupStepProps {
  registry: LLMProviderRegistry;
  value: LLMConfig;
  onChange: (next: LLMConfig) => void;
  onValid?: (valid: boolean) => void;
  /** Scenario references map for the inner provider section. Optional in onboarding. */
  scenarioReferences?: Record<string, LLMScenario[]>;
  /** Custom-provider defaults pulled from the onboarding template. */
  customProviderDefaults?: LLMProviderConfig | null;
}

function applyRecommendedModels(value: LLMConfig, providerId: string): LLMConfig {
  const rec = getRecommendedModels(providerId);
  if (!rec) return value;

  const next = cloneLLMConfig(value);
  const selections = next.selections as Partial<Record<LLMScenario, LLMSelectionConfig>>;

  selections.core = cloneSelection({
    ...(selections.core ?? {}),
    provider_id: providerId,
    model: rec.core,
  });
  selections.context_decider = cloneSelection({
    ...(selections.context_decider ?? {}),
    provider_id: providerId,
    model: rec.context_decider,
  });
  if (rec.embedding) {
    selections.embedding = cloneSelection({
      ...(selections.embedding ?? {}),
      provider_id: providerId,
      model: rec.embedding,
    });
  }
  // Mirror core into memory_summarizer if not set, matching cloneLLMConfig's
  // existing convention.
  if (!selections.memory_summarizer?.model) {
    selections.memory_summarizer = cloneSelection({
      ...(selections.memory_summarizer ?? {}),
      provider_id: providerId,
      model: rec.core,
    });
  }

  return { ...next, selections: selections as Record<LLMScenario, LLMSelectionConfig> };
}

function isValidConfig(value: LLMConfig): boolean {
  const providers = value.providers ?? {};
  const selections = value.selections ?? ({} as Record<LLMScenario, LLMSelectionConfig>);

  const anyEnabledWithKey = Object.values(providers).some(
    (p) => p?.enabled && (p.api_key?.length ?? 0) > 0,
  );
  if (!anyEnabledWithKey) return false;
  if (!selections.core?.provider_id || !selections.core?.model) return false;
  if (!selections.context_decider?.provider_id || !selections.context_decider?.model) return false;
  return true;
}

export function LLMSetupStep({
  registry,
  value,
  onChange,
  onValid,
  scenarioReferences,
  customProviderDefaults,
}: LLMSetupStepProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  const [activeProviderId, setActiveProviderId] = useState<string>('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const recommended = activeProviderId ? getRecommendedModels(activeProviderId) : undefined;
  const showEmbeddingRow = recommended && recommended.embedding === null;

  useEffect(() => {
    onValid?.(isValidConfig(value));
  }, [value, onValid]);

  const handleActiveProviderChange = useCallback(
    (providerId: string) => {
      setActiveProviderId(providerId);
      if (providerId && getRecommendedModels(providerId)) {
        onChange(applyRecommendedModels(value, providerId));
      }
    },
    [onChange, value],
  );

  const handleProviderChange = useCallback(
    (providerId: string, updater: (draft: LLMProviderConfig) => void) => {
      const next = cloneLLMConfig(value);
      const draft = cloneProvider(next.providers[providerId]);
      updater(draft);
      next.providers = { ...next.providers, [providerId]: draft };
      onChange(next);
    },
    [onChange, value],
  );

  const handleSetProvider = useCallback(
    (providerId: string, provider: LLMProviderConfig) => {
      const next = cloneLLMConfig(value);
      next.providers = { ...next.providers, [providerId]: cloneProvider(provider) };
      onChange(next);
    },
    [onChange, value],
  );

  const handleRemoveProvider = useCallback(
    (providerId: string) => {
      const next = cloneLLMConfig(value);
      const remaining = { ...next.providers };
      delete remaining[providerId];
      next.providers = remaining;
      onChange(next);
    },
    [onChange, value],
  );

  // No-op stubs for handlers that exist on LLMProviderConfigurationSection but
  // are not exercised in the folded onboarding step. Plan 2 keeps model and
  // discovery management hidden behind the advanced disclosure.
  const noopDiscoveryState = useMemo(() => ({}), []);
  const noopTestState = useMemo<Record<string, { loading: boolean; error: string | null; result: TestLLMProviderConnectionResponse | null }>>(() => ({}), []);

  return (
    <div className="flex flex-col gap-6">
      <LLMProviderConfigurationSection
        registry={registry}
        value={value}
        activeProviderId={activeProviderId}
        quickMode
        surface="onboarding"
        showSectionIntro={false}
        scenarioReferences={scenarioReferences ?? {}}
        customProviderDefaults={customProviderDefaults}
        onActiveProviderChange={handleActiveProviderChange}
        onProviderChange={handleProviderChange}
        onSetProvider={handleSetProvider}
        onRemoveProvider={handleRemoveProvider}
        onAddProviderModel={() => undefined}
        onRemoveProviderModel={() => undefined}
        onProviderDefaultModelChange={() => undefined}
        onDiscoverProviderModels={async () => undefined}
        onResolveDraftProviderPreview={async () => null}
        providerDiscoveryState={noopDiscoveryState}
        onTestProviderConnection={() => undefined}
        providerTestState={noopTestState}
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
        className="self-start text-sm underline text-[#7d685a]"
        onClick={() => setShowAdvanced((current) => !current)}
      >
        {showAdvanced ? t('llmSetup.hideAdvanced') : t('llmSetup.showAdvanced')}
      </button>

      {showAdvanced ? (
        <div data-testid="llm-setup-advanced-models">
          {/* P2-T9 may wire LLMModelSelectionSection here. For Plan 2 the
              auto-defaulted models from RECOMMENDED_MODELS are enough. */}
        </div>
      ) : null}
    </div>
  );
}

export default LLMSetupStep;
