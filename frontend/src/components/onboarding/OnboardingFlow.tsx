import React, { useEffect, useMemo, useState } from 'react';
import { SimpleForm as Form } from './simple-form';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { configApi } from '../../api/modules/config';
import type { SystemConfig, EmbeddingConfig, CrossEncoderConfig } from '../../api/modules/config';
import LLMForm from '../config-forms/LLMForm';
import PersonalityForm from '../config-forms/PersonalityForm';
import MemoryForm from '../config-forms/MemoryForm';
import ToolsForm from '../config-forms/ToolsForm';
import SensorConfigForm from '../config-forms/SensorConfigForm';
import GuidedConfigFrame from '../config-forms/GuidedConfigFrame';
import WelcomeScreen from './WelcomeScreen';
import ScenarioSelection from './ScenarioSelection';
import type { ScenarioId } from './ScenarioSelection';
import StepIndicator from './StepIndicator';
import CompletionScreen from './CompletionScreen';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';

type Mode = 'quick' | 'expert' | null;
type Phase = 'welcome' | 'guided';

const STORAGE_KEY = 'magi_onboarding_state';
const BUILTIN_SCENARIOS = ['context_decider', 'core', 'embedding'] as const;
const toI18nLanguage = (language?: string): 'en' | 'zh-CN' => (language === 'en' ? 'en' : 'zh-CN');

/** Scenario preset config overrides for quick mode. */
const SCENARIO_PRESETS: Record<ScenarioId, Partial<SystemConfig>> = {
  chat_assistant: {
    memory: {
      db_path: '~/.magi/data/memories',
      embedding: { mode: 'remote', local: { model_source: 'managed', managed_model_id: null, model_dir_path: null, idle_timeout_seconds: 1800 } },
      reranker: { top_k: 8, cross_encoder: { enabled: false, managed_model_id: null } },
      l0: { enabled: true, checkpoint_interval_seconds: 30, runtime_replay_include_l0_only: false },
      l1: { enabled: true, retention_days: 7, t1_importance_enabled: true, vectors_enabled: true },
      l2: { enabled: false, vectors_enabled: false, batch_flush_interval_seconds: 60, llm_extraction_enabled: false, auto_extract_relations: false, conflict_arbitration_enabled: false, conflict_arbitration_min_confidence: 0.85 },
      l3: { enabled: false, vectors_enabled: false, llm_summary_enabled: false, temporal_llm_timeout_seconds: 3.0, temporal_llm_min_event_count: 2, summary_interval_minutes: 60 },
      l4: { enabled: false, vectors_enabled: false, skill_extraction_enabled: false },
    },
    tools: {
      builtIn: {
        weather: { enabled: true, provider: 'qweather' },
        webSearch: { enabled: true, provider: 'duckduckgo' },
        webFetch: { enabled: true, usePlaywright: false },
      },
      skills: [],
    },
  },
  life_monitor: {
    memory: {
      db_path: '~/.magi/data/memories',
      embedding: { mode: 'remote', local: { model_source: 'managed', managed_model_id: null, model_dir_path: null, idle_timeout_seconds: 1800 } },
      reranker: { top_k: 8, cross_encoder: { enabled: false, managed_model_id: null } },
      l0: { enabled: true, checkpoint_interval_seconds: 30, runtime_replay_include_l0_only: false },
      l1: { enabled: true, retention_days: 7, t1_importance_enabled: true, vectors_enabled: true },
      l2: { enabled: true, vectors_enabled: true, batch_flush_interval_seconds: 60, llm_extraction_enabled: true, auto_extract_relations: true, conflict_arbitration_enabled: true, conflict_arbitration_min_confidence: 0.85 },
      l3: { enabled: true, vectors_enabled: true, llm_summary_enabled: true, temporal_llm_timeout_seconds: 3.0, temporal_llm_min_event_count: 2, summary_interval_minutes: 60 },
      l4: { enabled: false, vectors_enabled: false, skill_extraction_enabled: false },
    },
    timeline: {
      sources: {
        photo_library: { enabled: true, sync_mode: 'interval', sync_interval_minutes: 60, default_retention_mode: 'retain_raw', storage_mode: 'external_reference', fetch_page_content: false, edge_whitelist: ['CAPTURED', 'RELATED_TO', 'INTERACTED_WITH', 'CREATED'] },
        calendar: { enabled: true, sync_mode: 'interval', sync_interval_minutes: 15, default_retention_mode: 'analyze_only', storage_mode: 'managed', fetch_page_content: false, edge_whitelist: [] },
        screen_time: { enabled: true, sync_mode: 'interval', sync_interval_minutes: 30, default_retention_mode: 'analyze_only', storage_mode: 'managed', fetch_page_content: false, edge_whitelist: [] },
      },
    },
    tools: {
      builtIn: {
        weather: { enabled: true, provider: 'qweather' },
        webSearch: { enabled: true, provider: 'duckduckgo' },
        webFetch: { enabled: true, usePlaywright: false },
      },
      skills: [],
    },
  },
  knowledge_partner: {
    memory: {
      db_path: '~/.magi/data/memories',
      embedding: { mode: 'remote', local: { model_source: 'managed', managed_model_id: null, model_dir_path: null, idle_timeout_seconds: 1800 } },
      reranker: { top_k: 8, cross_encoder: { enabled: false, managed_model_id: null } },
      l0: { enabled: true, checkpoint_interval_seconds: 30, runtime_replay_include_l0_only: false },
      l1: { enabled: true, retention_days: 7, t1_importance_enabled: true, vectors_enabled: true },
      l2: { enabled: true, vectors_enabled: true, batch_flush_interval_seconds: 60, llm_extraction_enabled: true, auto_extract_relations: true, conflict_arbitration_enabled: true, conflict_arbitration_min_confidence: 0.85 },
      l3: { enabled: true, vectors_enabled: true, llm_summary_enabled: true, temporal_llm_timeout_seconds: 3.0, temporal_llm_min_event_count: 2, summary_interval_minutes: 60 },
      l4: { enabled: true, vectors_enabled: true, skill_extraction_enabled: true },
    },
    timeline: {
      sources: {
        photo_library: { enabled: false, sync_mode: 'interval', sync_interval_minutes: 60, default_retention_mode: 'retain_raw', storage_mode: 'external_reference', fetch_page_content: false, edge_whitelist: ['CAPTURED', 'RELATED_TO', 'INTERACTED_WITH', 'CREATED'] },
        chrome_history: { enabled: true, sync_mode: 'interval', sync_interval_minutes: 30, default_retention_mode: 'analyze_only', storage_mode: 'managed', fetch_page_content: false, edge_whitelist: [] },
        git_activity: { enabled: true, sync_mode: 'interval', sync_interval_minutes: 30, default_retention_mode: 'analyze_only', storage_mode: 'managed', fetch_page_content: false, edge_whitelist: [] },
      },
    },
    tools: {
      builtIn: {
        weather: { enabled: true, provider: 'qweather' },
        webSearch: { enabled: true, provider: 'duckduckgo' },
        webFetch: { enabled: true, usePlaywright: false },
      },
      skills: [],
    },
  },
  default: {},
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
  const [renderLanguage, setRenderLanguage] = useState(i18n.resolvedLanguage || i18n.language);
  const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingConfig | undefined>(
    () => form.getFieldValue(['memory', 'embedding']) as EmbeddingConfig | undefined
  );
  const [crossEncoderConfig, setCrossEncoderConfig] = useState<CrossEncoderConfig | undefined>(
    () => form.getFieldValue(['memory', 'reranker', 'cross_encoder']) as CrossEncoderConfig | undefined
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

  // Quick mode steps: Scenario → Provider → Complete
  // Expert mode steps: Provider → Models → Personality → Memory → Sensors → Tools → Complete
  const steps = useMemo(() => {
    if (mode === 'quick') {
      return [t('steps.scenario'), t('steps.llmProviders'), t('steps.complete')];
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
  }, [mode, t, activeLanguage]);

  const isLastStep = current === steps.length - 1;

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
    const values = form.getFieldsValue(true);
    values.preferences.onboarding_completed = true;
    await configApi.completeOnboarding(values);
    localStorage.removeItem(STORAGE_KEY);
    if (values.preferences.language) {
      localStorage.setItem('magi_language', values.preferences.language);
    }
    if (values.preferences.language !== initialConfig.preferences.language) {
      window.location.href = '/';
      return;
    }
    navigate('/');
  };

  const hasEnabledProvider = (): boolean => {
    const llmConfig = form.getFieldValue(['llm']);
    return Object.values(llmConfig?.providers || {}).some((provider: any) => provider?.enabled);
  };

  const validateProviderFields = (): { valid: boolean; message?: string } => {
    const llmConfig = form.getFieldValue(['llm']);
    const providers = llmConfig?.providers || {};

    for (const [providerId, provider] of Object.entries(providers) as [string, any][]) {
      if (!provider?.enabled) continue;

      if (provider.provider_type === 'custom') {
        if (!provider.display_name?.trim()) {
          return { valid: false, message: t('llm.validation.customProviderNameRequired') };
        }
        if (!provider.api_key?.trim()) {
          return { valid: false, message: t('llm.validation.customProviderApiKeyRequired') };
        }
        if (!provider.base_url?.trim()) {
          return { valid: false, message: t('llm.validation.customProviderBaseUrlRequired') };
        }
        if (!provider.custom_models?.length) {
          return { valid: false, message: t('llm.validation.customProviderModelRequired') };
        }
      } else {
        if (!provider.api_key?.trim()) {
          return { valid: false, message: t('llm.validation.apiKeyRequired', { provider: provider.display_name || providerId }) };
        }
      }
    }

    return { valid: true };
  };

  const hasValidSelections = (): boolean => {
    const llmConfig = form.getFieldValue(['llm']);
    return BUILTIN_SCENARIOS.every((scenario) => {
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
  const getProviderStepIndex = (): number => (isQuickMode ? 1 : 0);

  /** Get the model selection step index (expert only). */
  const getModelStepIndex = (): number => 1;

  const handleNext = async () => {
    try {
      setSaving(true);
      await form.validateFields();

      // Quick mode: step 0 = scenario, step 1 = providers, step 2 = complete
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

      // Expert mode: model selection validation
      if (!isQuickMode && current === getModelStepIndex()) {
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

    if (isQuickMode) {
      // Quick: 0=Scenario, 1=Providers, 2=Complete
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
      if (current === 1) return <LLMForm quickMode view="providers" />;
      if (current === 2) return <CompletionScreen onFinish={handleFinish} />;
    } else {
      // Expert: 0=Providers, 1=Models, 2=Personality, 3=Memory, 4=Sensors, 5=Tools, 6=Complete
      if (current === 0) return <LLMForm quickMode={false} view="providers" />;
      if (current === 1) {
        return (
          <LLMForm
            quickMode={false}
            view="models"
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
                const base = prev ?? { enabled: false, managed_model_id: null };
                const draft = { ...base };
                updater(draft);
                form.setFieldValue(['memory', 'reranker', 'cross_encoder'], draft);
                saveProgress(form.getFieldsValue(true));
                return draft;
              });
            }}
          />
        );
      }
      if (current === 2) return <PersonalityForm quickMode={false} language={language} />;
      if (current === 3) return <MemoryForm />;
      if (current === 4) return <SensorConfigForm />;
      if (current === 5) return <ToolsForm />;
      if (current === 6) return <CompletionScreen onFinish={handleFinish} />;
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
          footer={(
            <div className="flex items-center justify-between gap-3">
              <Button variant="outline" onClick={handlePrev}>
                {t('actions.previous')}
              </Button>
              <Button onClick={handleNext} disabled={saving}>
                {saving ? t('actions.saving') : isLastStep ? t('actions.finish') : t('actions.next')}
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
function deepMerge<T extends Record<string, any>>(base: T, patch: Partial<T>): T {
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
