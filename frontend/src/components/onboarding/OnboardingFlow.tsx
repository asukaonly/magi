import React, { useEffect, useMemo, useRef, useState } from 'react';
import { SimpleForm as Form } from './simple-form';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/api/client';
import { STORAGE_KEYS } from '@/constants/app';
import { configApi } from '../../api/modules/config';
import type { SystemConfig, EmbeddingConfig, CrossEncoderConfig } from '../../api/modules/config';
import { personasApi, selectDefaultSeedPreview } from '../../api/modules/personas';
import type { SeedPreview } from '../../api/modules/personas';
import LLMForm from '../config-forms/LLMForm';
import PersonalityForm from '../config-forms/PersonalityForm';
import MemoryForm from '../config-forms/MemoryForm';
import ToolsForm from '../config-forms/ToolsForm';
import { validateToolsConfig, type ToolValidationIssue } from '../config-forms/tool-validation';
import GuidedConfigFrame from '../config-forms/GuidedConfigFrame';
import WelcomeScreen from './WelcomeScreen';
import ScenarioSelection from './ScenarioSelection';
import type { ScenarioId } from './ScenarioSelection';
import { SCENARIO_NEEDS_SENSORS } from './ScenarioSelection';
import SensorSelection from './SensorSelection';
import type { SensorInstallStatus } from './SensorSelection';
import StepIndicator from './StepIndicator';
import CompletionScreen from './CompletionScreen';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { validateLLMCustomProviderReadiness, type LLMValidationIssue } from '../config-forms/llm-form-state';

type Mode = 'quick' | 'expert' | null;
type Phase = 'welcome' | 'guided';

const QUICK_MODE_PERSONALITY_SEEDS: Record<string, Record<'zh' | 'en', string>> = {
  chat_assistant: {
    zh: 'echo',
    en: 'nova',
  },
  life_monitor: {
    zh: 'sumen',
    en: 'ember',
  },
  knowledge_partner: {
    zh: 'sichen',
    en: 'halberd',
  },
  default: {
    zh: 'echo',
    en: 'nova',
  },
};

const STORAGE_KEY = STORAGE_KEYS.ONBOARDING_STATE;
const BUILTIN_SCENARIOS = ['context_decider', 'core', 'embedding'] as const;
const RUNTIME_READY_WAIT_INTERVAL_MS = 500;
const RUNTIME_READY_WAIT_TIMEOUT_MS = 12_000;
const toI18nLanguage = (language?: string): 'en' | 'zh-CN' => (language === 'en' ? 'en' : 'zh-CN');

interface QuickScenarioPresetOptions {
  retentionDays: number;
  queryExpansionEnabled: boolean;
  autoBackgroundEnabled: boolean;
  weatherEnabled: boolean;
  webSearchEnabled: boolean;
  webFetchEnabled: boolean;
  l2Enabled: boolean;
  l3Enabled: boolean;
  l4Enabled: boolean;
}

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends Array<infer U>
    ? Array<U>
    : T[K] extends Record<string, any>
      ? DeepPartial<T[K]>
      : T[K];
};

interface RuntimeReadyResponse {
  success: boolean;
  data?: {
    ready: boolean;
    status: string;
    runtime_ready: boolean;
    runtime_status: string;
    startup_state?: string;
    deferred_reason?: string | null;
  };
}


function waitFor(durationMs: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, durationMs);
  });
}


async function waitForRuntimeReadyAfterOnboarding() {
  const deadline = Date.now() + RUNTIME_READY_WAIT_TIMEOUT_MS;
  let lastSnapshot: RuntimeReadyResponse['data'] | null = null;

  while (Date.now() <= deadline) {
    try {
      const response = await apiClient.get<RuntimeReadyResponse>('/ready');
      const snapshot = response.data?.data;
      lastSnapshot = snapshot || null;
      if (snapshot?.runtime_ready) {
        return snapshot;
      }
    } catch {
      // Keep polling for a short window while the runtime finishes starting.
    }

    await waitFor(RUNTIME_READY_WAIT_INTERVAL_MS);
  }

  return lastSnapshot;
}


function selectQuickModeSeedSlug(
  locale: 'zh' | 'en',
  scenario: string | null | undefined,
  previews: SeedPreview[]
): string | undefined {
  const scenarioKey = scenario && scenario in QUICK_MODE_PERSONALITY_SEEDS ? scenario : 'default';
  const preferredSeedSlug = QUICK_MODE_PERSONALITY_SEEDS[scenarioKey]?.[locale];
  if (preferredSeedSlug && previews.some((preview) => preview.seed_slug === preferredSeedSlug)) {
    return preferredSeedSlug;
  }
  return selectDefaultSeedPreview(previews)?.seed_slug;
}

/** Scenario preset config overrides for quick mode.
 *
 * These shape conversation, memory, and tool defaults.
 * Sensor / timeline source config is handled by plugin installation
 * in the SensorSelection step.
 */
const buildQuickScenarioPreset = ({
  retentionDays,
  queryExpansionEnabled,
  autoBackgroundEnabled,
  weatherEnabled,
  webSearchEnabled,
  webFetchEnabled,
  l2Enabled,
  l3Enabled,
  l4Enabled,
}: QuickScenarioPresetOptions): DeepPartial<SystemConfig> => ({
  agent: {
    background_tasks: {
      auto_detect_long_task: autoBackgroundEnabled,
    },
  },
  memory: {
    db_path: '~/.magi/data/memories',
    retention_days: retentionDays,
    history_behavior: 'delete',
    embedding: {
      mode: 'off',
      local: {
        model_source: 'managed',
        managed_model_id: null,
        model_dir_path: null,
        idle_timeout_seconds: 1800,
      },
    },
    reranker: {
      top_k: 8,
      cross_encoder: {
        enabled: false,
        managed_model_id: null,
      },
    },
    query_expansion: { enabled: queryExpansionEnabled },
    l0: { enabled: true, checkpoint_interval_seconds: 30 },
    l1: { enabled: true, vectors_enabled: true },
    l2: {
      enabled: l2Enabled,
      vectors_enabled: l2Enabled,
      batch_flush_interval_seconds: 60,
      auto_extract_relations: l2Enabled,
      conflict_arbitration_enabled: l2Enabled,
      conflict_arbitration_min_confidence: 0.85,
    },
    l3: {
      enabled: l3Enabled,
      vectors_enabled: l3Enabled,
      llm_summary_enabled: l3Enabled,
      temporal_llm_timeout_seconds: 3.0,
      temporal_llm_min_event_count: 2,
      summary_interval_minutes: 60,
    },
    l4: {
      enabled: l4Enabled,
      vectors_enabled: l4Enabled,
    },
  },
  preferences: {
    allow_interjection: false,
    allow_ask_in_background: false,
  },
  tools: {
    builtIn: {
      weather: { enabled: weatherEnabled, provider: 'qweather' },
      webSearch: { enabled: webSearchEnabled, provider: 'duckduckgo' },
      webFetch: { enabled: webFetchEnabled, usePlaywright: false },
    },
    skills: [],
  },
});

const SCENARIO_PRESETS: Record<ScenarioId, DeepPartial<SystemConfig>> = {
  chat_assistant: buildQuickScenarioPreset({
    retentionDays: 60,
    queryExpansionEnabled: false,
    autoBackgroundEnabled: false,
    weatherEnabled: false,
    webSearchEnabled: true,
    webFetchEnabled: true,
    l2Enabled: false,
    l3Enabled: false,
    l4Enabled: false,
  }),
  life_monitor: buildQuickScenarioPreset({
    retentionDays: 180,
    queryExpansionEnabled: false,
    autoBackgroundEnabled: false,
    weatherEnabled: true,
    webSearchEnabled: true,
    webFetchEnabled: true,
    l2Enabled: true,
    l3Enabled: true,
    l4Enabled: false,
  }),
  knowledge_partner: buildQuickScenarioPreset({
    retentionDays: 365,
    queryExpansionEnabled: true,
    autoBackgroundEnabled: true,
    weatherEnabled: false,
    webSearchEnabled: true,
    webFetchEnabled: true,
    l2Enabled: true,
    l3Enabled: true,
    l4Enabled: true,
  }),
  default: buildQuickScenarioPreset({
    retentionDays: 120,
    queryExpansionEnabled: false,
    autoBackgroundEnabled: false,
    weatherEnabled: false,
    webSearchEnabled: true,
    webFetchEnabled: true,
    l2Enabled: true,
    l3Enabled: false,
    l4Enabled: false,
  }),
};

interface OnboardingFlowProps {
  initialConfig: SystemConfig;
}

export const OnboardingFlow: React.FC<OnboardingFlowProps> = ({ initialConfig }) => {
  const { t, i18n } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>('welcome');
  const [mode, setMode] = useState<Mode>(initialConfig.preferences.user_mode);
  const [scenario, setScenario] = useState<ScenarioId | null>(
    (initialConfig.preferences.scenario as ScenarioId) || null
  );
  const [current, setCurrent] = useState(0);
  const [saving, setSaving] = useState(false);
  const [finishingRuntime, setFinishingRuntime] = useState(false);
  const finishInFlightRef = useRef(false);
  const [sensorInstallStatus, setSensorInstallStatus] = useState<SensorInstallStatus>({
    canContinue: true,
    isInstalling: false,
  });
  const [renderLanguage, setRenderLanguage] = useState(i18n.resolvedLanguage || i18n.language);
  const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingConfig | undefined>(
    () => initialConfig.memory?.embedding
  );
  const [crossEncoderConfig, setCrossEncoderConfig] = useState<CrossEncoderConfig | undefined>(
    () => initialConfig.memory?.reranker?.cross_encoder
  );
  const [llmValidationIssues, setLlmValidationIssues] = useState<LLMValidationIssue[]>([]);
  const [toolValidationIssues, setToolValidationIssues] = useState<ToolValidationIssue[]>(
    () => validateToolsConfig(initialConfig)
  );
  const activeLanguage = i18n.resolvedLanguage || i18n.language;
  const isQuickMode = mode === 'quick';
  const debugI18n = localStorage.getItem('magi_i18n_debug') === '1';

  useEffect(() => {
    const formLanguage = initialConfig.preferences?.language || 'zh';
    const configuredLanguage = toI18nLanguage(formLanguage);

    document.documentElement.lang = configuredLanguage;
    setRenderLanguage(configuredLanguage);

    if ((i18n.resolvedLanguage || i18n.language) !== configuredLanguage) {
      void i18n.changeLanguage(configuredLanguage);
    }
  }, [i18n, initialConfig.preferences?.language]);

  // Quick mode steps: Scenario → [Sensors] → Provider → Models → Complete
  // Expert mode steps: Provider → Models → Personality → Memory → Sensors → Tools → Complete
  const needsSensors = scenario ? SCENARIO_NEEDS_SENSORS[scenario] : false;
  const steps = useMemo(() => {
    if (mode === 'quick') {
      const base = [t('steps.scenario')];
      if (needsSensors) base.push(t('steps.sensors'));
      base.push(t('steps.llmProviders'), t('steps.llmModels'), t('steps.complete'));
      return base;
    }
    return [
      t('steps.llmProviders'),
      t('steps.llmModels'),
      t('steps.personality'),
      t('steps.memory'),
      t('steps.sensors'),
      t('steps.tools'),
      t('steps.complete'),
    ];
  }, [mode, needsSensors, t, activeLanguage]);

  const isLastStep = current === steps.length - 1;
  const isSensorStep = (isQuickMode && needsSensors && current === 1) || (!isQuickMode && current === 4);
  const sensorStepBlocksNext = isSensorStep && !sensorInstallStatus.canContinue;
  const providerStepIndex = isQuickMode ? (needsSensors ? 2 : 1) : 0;
  const modelStepIndex = isQuickMode ? providerStepIndex + 1 : 1;
  const llmStepBlocksNext = (current === providerStepIndex || current === modelStepIndex) && llmValidationIssues.length > 0;
  const isToolsStep = !isQuickMode && current === 5;
  const toolStepBlocksNext = isToolsStep && toolValidationIssues.length > 0;

  const formatLlmValidationIssue = (issue: LLMValidationIssue): string => {
    const serviceLabel = t(`llm.providerConfiguration.serviceLabels.${issue.serviceName}`);
    if (issue.code === 'customScenarioModelMissing' && issue.scenario && issue.model) {
      return t('llm.validation.customScenarioModelMissing', {
        provider: issue.providerName,
        scenario: t(`llm.scenarios.${issue.scenario}.title`),
        model: issue.model,
        service: serviceLabel,
      });
    }
    return t('llm.validation.customServiceModelRequired', {
      provider: issue.providerName,
      service: serviceLabel,
    });
  };

  const formatToolValidationIssue = (issue: ToolValidationIssue): string =>
    t(issue.messageKey, issue.values);

  // Restore saved progress
  useEffect(() => {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (!cached) return;
    try {
      const parsed = JSON.parse(cached) as {
        current?: number;
        mode?: Mode;
        phase?: Phase;
        scenario?: ScenarioId | null;
        values?: SystemConfig;
      };
      if (parsed.mode) {
        setMode(parsed.mode);
        setPhase('guided');
      }
      if (parsed.scenario) {
        setScenario(parsed.scenario);
      }
      if (typeof parsed.current === 'number') {
        setCurrent(parsed.current);
      }
      if (parsed.values) {
        const savedLanguage = localStorage.getItem('magi_language');
        const mergedValues = {
          ...parsed.values,
          preferences: {
            ...parsed.values?.preferences,
            language: savedLanguage || parsed.values?.preferences?.language,
          },
        };
        form.setFieldsValue(mergedValues);
        setToolValidationIssues(validateToolsConfig(mergedValues));
      }
    } catch {
      // Ignore invalid cached state.
    }
  }, [form]);

  useEffect(() => {
    const language = form.getFieldValue(['preferences', 'language']);
    if (!language) {
      form.setFieldValue(['preferences', 'language'], 'zh');
    }
  }, [form]);

  const saveProgress = (values: SystemConfig) => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        current,
        mode,
        phase,
        scenario,
        values,
      })
    );
  };

  const onValuesChange = (_: unknown, allValues: SystemConfig) => {
    const nextLanguage = allValues?.preferences?.language;
    if (nextLanguage) {
      const mapped = toI18nLanguage(nextLanguage);
      localStorage.setItem('magi_language', nextLanguage);
      document.documentElement.lang = mapped;
      if (debugI18n) {
        console.info('[onboarding:i18n] onValuesChange', {
          raw: nextLanguage,
          mapped,
          current: i18n.language,
        });
      }
      if (i18n.language !== mapped) {
        void i18n.changeLanguage(mapped);
      }
    }
    saveProgress(allValues);
    setToolValidationIssues(validateToolsConfig(allValues));
  };

  useEffect(() => {
    if (!debugI18n) return;
    const handleLanguageChanged = (lng: string) => {
      console.info('[onboarding:i18n] languageChanged', { lng });
    };
    i18n.on('languageChanged', handleLanguageChanged);
    return () => {
      i18n.off('languageChanged', handleLanguageChanged);
    };
  }, [debugI18n, i18n]);

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      setRenderLanguage(lng);
    };
    i18n.on('languageChanged', handleLanguageChanged);
    return () => {
      i18n.off('languageChanged', handleLanguageChanged);
    };
  }, [i18n]);

  const handleFinish = async () => {
    if (finishInFlightRef.current) {
      return;
    }
    finishInFlightRef.current = true;
    setSaving(true);

    try {
      const values = form.getFieldsValue(true);
      values.preferences.onboarding_completed = true;
      await configApi.completeOnboarding(values);

      // Seed builtin personas into the registry and set the selected one active
      const locale = (values.preferences?.language || 'en').startsWith('zh') ? 'zh' : 'en';
      try {
        const quickSeedPreviewsPromise =
          mode === 'quick' ? personasApi.seedPreviews(locale) : Promise.resolve(null);
        await personasApi.seed(locale);
        const [listResult, quickSeedPreviews] = await Promise.all([
          personasApi.list(),
          quickSeedPreviewsPromise,
        ]);
        const personas = listResult.data || [];
        const quickDefaultSeedSlug = quickSeedPreviews
          ? selectQuickModeSeedSlug(locale, values.preferences?.scenario, quickSeedPreviews.data || [])
          : undefined;

        // Determine which persona to activate:
        // - Quick mode: use the scenario-mapped seed preview when available
        // - Expert mode with preset: use the seed_slug saved by PersonalityForm
        // - Expert mode with custom: create a new persona entry
        const seedSlug: string | undefined =
          mode === 'quick' ? quickDefaultSeedSlug : values.personalitySeedSlug;

        let activatedPersonaId: string | undefined;

        if (seedSlug) {
          const match = personas.find((p) => p.slug === seedSlug);
          if (match) activatedPersonaId = match.persona_id;
        }

        if (!activatedPersonaId && !seedSlug && values.personality) {
          // Expert mode with a custom/generated persona — create a new registry entry
          try {
            const configJson = JSON.stringify(values.personality);
            const created = await personasApi.create({ config_json: configJson, locale });
            if (created.data?.persona_id) activatedPersonaId = created.data.persona_id;
          } catch {
            // Fall through to name-based matching
          }
        }

        // Fallback: match by name, then first persona
        if (!activatedPersonaId) {
          const selectedName = values.personality?.name;
          const fallback = personas.find((p) => p.name === selectedName) || personas[0];
          if (fallback) activatedPersonaId = fallback.persona_id;
        }

        if (activatedPersonaId) {
          await personasApi.setActive(activatedPersonaId);
        }
      } catch {
        // Persona registry is best-effort during onboarding;
        // the backend lifecycle fallback handles missing registry state.
      }

      setFinishingRuntime(true);
      const runtimeSnapshot = await waitForRuntimeReadyAfterOnboarding();
      setFinishingRuntime(false);

      if (!runtimeSnapshot?.runtime_ready) {
        toast.warning(t('messages.runtimeStartingSlow'));
      }

      localStorage.removeItem(STORAGE_KEY);
      if (values.preferences.language) {
        localStorage.setItem('magi_language', values.preferences.language);
      }
      if (values.preferences.language !== initialConfig.preferences.language) {
        window.location.href = '/';
        return;
      }
      navigate('/');
    } catch (error: any) {
      toast.error(error?.message || t('messages.saveFailed'));
    } finally {
      finishInFlightRef.current = false;
      setSaving(false);
      setFinishingRuntime(false);
    }
  };

  const hasEnabledProvider = (): boolean => {
    const llmConfig = form.getFieldValue(['llm']);
    return Object.values(llmConfig?.providers || {}).some((provider: any) => provider?.enabled);
  };

  const validateProviderFields = (): { valid: boolean; message?: string } => {
    const llmConfig = form.getFieldValue(['llm']);
    const providers = llmConfig?.providers || {};
    const modelReadinessIssue = validateLLMCustomProviderReadiness(llmConfig)?.[0];
    if (modelReadinessIssue) {
      return { valid: false, message: formatLlmValidationIssue(modelReadinessIssue) };
    }

    for (const [providerId, provider] of Object.entries(providers) as [string, any][]) {
      if (!provider?.enabled) continue;
      const chatService = provider.services?.chat;

      if (provider.provider_type === 'custom') {
        if (!provider.display_name?.trim()) {
          return { valid: false, message: t('llm.validation.customProviderNameRequired') };
        }
        if (chatService?.enabled && !(chatService.api_key?.trim() || provider.api_key?.trim())) {
          return { valid: false, message: t('llm.validation.customProviderApiKeyRequired') };
        }
        if (chatService?.enabled && !(chatService.base_url?.trim() || provider.base_url?.trim())) {
          return { valid: false, message: t('llm.validation.customProviderBaseUrlRequired') };
        }
      }

      for (const service of Object.values(provider.services || {}) as any[]) {
        if (service?.enabled && !(service.api_key?.trim() || provider.api_key?.trim())) {
          return {
            valid: false,
            message: t('llm.validation.apiKeyRequired', { provider: provider.display_name || providerId }),
          };
        }
      }
    }

    return { valid: true };
  };

  const hasValidSelections = (): boolean => {
    const llmConfig = form.getFieldValue(['llm']);
    return BUILTIN_SCENARIOS.every((scenario) => {
      // Skip embedding validation when embedding mode is off or local
      if (scenario === 'embedding' && embeddingConfig?.mode !== 'remote') return true;
      const selection = llmConfig?.selections?.[scenario];
      return Boolean(
        selection?.provider_id &&
        selection?.model &&
        llmConfig?.providers?.[selection.provider_id]?.enabled
      );
    });
  };

  /** Apply scenario presets to the form values. */
  const applyScenarioPreset = (scenarioId: ScenarioId) => {
    const preset = SCENARIO_PRESETS[scenarioId];
    if (!preset || Object.keys(preset).length === 0) return;
    // Deep merge preset into current form values
    const currentValues = form.getFieldsValue(true);
    const merged = deepMerge(currentValues, preset);
    form.setFieldsValue(merged);
  };

  /** Handle welcome screen mode selection. */
  const handleWelcomeSelectMode = (selectedMode: 'quick' | 'expert') => {
    setMode(selectedMode);
    form.setFieldValue(['preferences', 'user_mode'], selectedMode);
    setPhase('guided');
    setCurrent(0);
    saveProgress(form.getFieldsValue(true));
  };

  /** Handle language change from welcome screen. */
  const handleWelcomeLanguageChange = (lang: 'zh' | 'en') => {
    form.setFieldValue(['preferences', 'language'], lang);
    localStorage.setItem('magi_language', lang);
    const mapped = toI18nLanguage(lang);
    document.documentElement.lang = mapped;
    void i18n.changeLanguage(mapped);
  };

  /** Get the provider config step index for the current mode. */
  const getProviderStepIndex = (): number => (isQuickMode ? (needsSensors ? 2 : 1) : 0);

  /** Get the model selection step index for the current mode. */
  const getModelStepIndex = (): number => (isQuickMode ? getProviderStepIndex() + 1 : 1);

  const handleNext = async () => {
    if (sensorStepBlocksNext) {
      toast.warning(
        sensorInstallStatus.isInstalling
          ? t('sensorSelection.installingBlockNext')
          : t('sensorSelection.installBeforeNextHint')
      );
      return;
    }

    if (toolStepBlocksNext) {
      toast.warning(formatToolValidationIssue(toolValidationIssues[0]));
      return;
    }

    try {
      setSaving(true);
      await form.validateFields();

      // Quick mode: step 0 = scenario, then sensors (if needed), then providers, then models, then complete
      if (isQuickMode && current === 0) {
        if (!scenario) {
          toast.warning(t('scenario.description'));
          return;
        }
        applyScenarioPreset(scenario);
        form.setFieldValue(['preferences', 'scenario'], scenario);
        saveProgress(form.getFieldsValue(true));
        setCurrent(1);
        return;
      }

      const providerStep = getProviderStepIndex();
      if (current === providerStep) {
        if (!hasEnabledProvider()) {
          toast.warning(t('llm.providerConfiguration.enableProviderFirst'));
          return;
        }
        const validation = validateProviderFields();
        if (!validation.valid) {
          toast.warning(validation.message || t('messages.validationFailed'));
          return;
        }
      }

      if (current === getModelStepIndex()) {
        const modelReadinessIssue = validateLLMCustomProviderReadiness(form.getFieldValue(['llm']))?.[0];
        if (modelReadinessIssue) {
          toast.warning(formatLlmValidationIssue(modelReadinessIssue));
          return;
        }
        if (!hasValidSelections()) {
          toast.warning(t('llm.completeSelections'));
          return;
        }
      }

      if (isLastStep) {
        await handleFinish();
      } else {
        setCurrent((prev) => prev + 1);
      }
    } catch (error: any) {
      if (error?.errorFields?.length) {
        // Inline field errors are already displayed by SimpleForm.
      } else {
        toast.error(error?.message || t('messages.saveFailed'));
      }
    } finally {
      setSaving(false);
    }
  };

  const handlePrev = () => {
    if (current === 0) {
      // Go back to welcome screen
      setPhase('welcome');
      return;
    }
    setCurrent((prev) => Math.max(0, prev - 1));
  };

  const renderStepContent = () => {
    if (!mode) return null;

    const language = form.getFieldValue(['preferences', 'language']) || 'zh';
    const renderLLMModelStep = (quickModeForStep: boolean) => (
      <LLMForm
        quickMode={quickModeForStep}
        view="models"
        onValidationChange={setLlmValidationIssues}
        embeddingConfig={embeddingConfig}
        onEmbeddingConfigChange={(updater) => {
          setEmbeddingConfig((prev) => {
            const base = prev ?? (form.getFieldValue(['memory', 'embedding']) as EmbeddingConfig);
            const draft = { ...base, local: { ...base.local } };
            updater(draft);
            form.setFieldValue(['memory', 'embedding'], draft);
            saveProgress(form.getFieldsValue(true));
            return draft;
          });
        }}
        crossEncoderConfig={crossEncoderConfig}
        onCrossEncoderConfigChange={(updater) => {
          setCrossEncoderConfig((prev) => {
            const base = prev ?? { enabled: false, managed_model_id: null, variant: null };
            const draft = { ...base };
            updater(draft);
            form.setFieldValue(['memory', 'reranker', 'cross_encoder'], draft);
            saveProgress(form.getFieldsValue(true));
            return draft;
          });
        }}
      />
    );

    if (isQuickMode) {
      const providerIdx = needsSensors ? 2 : 1;
      const modelIdx = providerIdx + 1;
      const completeIdx = modelIdx + 1;

      if (current === 0) {
        return (
          <ScenarioSelection
            value={scenario}
            onChange={(s) => {
              setScenario(s);
              form.setFieldValue(['preferences', 'scenario'], s);
              saveProgress(form.getFieldsValue(true));
            }}
          />
        );
      }
      if (needsSensors && current === 1) {
        return <SensorSelection scenario={scenario!} onInstallStatusChange={setSensorInstallStatus} />;
      }
      if (current === providerIdx) {
        return <LLMForm quickMode view="providers" onValidationChange={setLlmValidationIssues} />;
      }
      if (current === modelIdx) return renderLLMModelStep(true);
      if (current === completeIdx) {
        return (
          <CompletionScreen
            onFinish={handleFinish}
            loading={saving || finishingRuntime}
            loadingLabel={finishingRuntime ? t('actions.startingRuntime') : t('actions.saving')}
          />
        );
      }
    } else {
      // Expert: 0=Providers, 1=Models, 2=Personality, 3=Memory, 4=Sensors, 5=Tools, 6=Complete
      if (current === 0) {
        return <LLMForm quickMode={false} view="providers" onValidationChange={setLlmValidationIssues} />;
      }
      if (current === 1) return renderLLMModelStep(false);
      if (current === 2) return <PersonalityForm quickMode={false} language={language} />;
      if (current === 3) return <MemoryForm />;
      if (current === 4) return <SensorSelection onInstallStatusChange={setSensorInstallStatus} />;
      if (current === 5) return <ToolsForm validationIssues={toolValidationIssues} />;
      if (current === 6) {
        return (
          <CompletionScreen
            onFinish={handleFinish}
            loading={saving || finishingRuntime}
            loadingLabel={finishingRuntime ? t('actions.startingRuntime') : t('actions.saving')}
          />
        );
      }
    }

    return null;
  };

  // Welcome phase: full-screen welcome
  if (phase === 'welcome') {
    const currentLang = (form.getFieldValue(['preferences', 'language']) as 'zh' | 'en') ||
      (initialConfig.preferences?.language as 'zh' | 'en') || 'zh';

    return (
      <Form
        form={form}
        layout="vertical"
        initialValues={initialConfig}
        onValuesChange={onValuesChange}
      >
        <WelcomeScreen
          language={currentLang}
          onLanguageChange={handleWelcomeLanguageChange}
          onSelectMode={handleWelcomeSelectMode}
        />
      </Form>
    );
  }

  // Guided phase: step-by-step config
  return (
    <div className="fixed inset-0 flex items-center justify-center overflow-y-auto bg-background p-[4vh_4vw]">
      <div className="h-full w-full max-h-[960px] max-w-[1400px]">
        <GuidedConfigFrame
          className="h-full"
          layoutClassName="h-full"
          sidebarClassName="lg:w-44"
          sidebar={<StepIndicator steps={steps} current={current} />}
          footer={isLastStep ? null : (
            <div className="flex items-center justify-between gap-3">
              <Button variant="outline" onClick={handlePrev}>
                {t('actions.previous')}
              </Button>
              <Button
                onClick={handleNext}
                disabled={saving || sensorStepBlocksNext || llmStepBlocksNext || toolStepBlocksNext}
              >
                {saving
                  ? (finishingRuntime ? t('actions.startingRuntime') : t('actions.saving'))
                  : t('actions.next')}
              </Button>
            </div>
          )}
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={initialConfig}
            onValuesChange={onValuesChange}
          >
            <AnimatePresence mode="wait">
              <motion.div
                className="flex min-h-0 flex-1 flex-col"
                key={`${renderLanguage}-${mode ?? 'none'}-${current}`}
                initial={shouldReduceMotion ? false : { opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={shouldReduceMotion ? undefined : { opacity: 0, x: -24 }}
                transition={{ duration: shouldReduceMotion ? 0 : 0.22, ease: 'easeOut' }}
              >
                {renderStepContent()}
              </motion.div>
            </AnimatePresence>
          </Form>
        </GuidedConfigFrame>
      </div>
    </div>
  );
};

/** Deep merge helper for applying scenario presets. */
function deepMerge<T extends Record<string, any>>(base: T, patch: DeepPartial<T>): T {
  const result = { ...base } as Record<string, any>;
  for (const key of Object.keys(patch)) {
    const patchVal = (patch as any)[key];
    const baseVal = result[key];
    if (
      patchVal != null &&
      typeof patchVal === 'object' &&
      !Array.isArray(patchVal) &&
      baseVal != null &&
      typeof baseVal === 'object' &&
      !Array.isArray(baseVal)
    ) {
      result[key] = deepMerge(baseVal, patchVal);
    } else {
      result[key] = patchVal;
    }
  }
  return result as T;
}

export default OnboardingFlow;
