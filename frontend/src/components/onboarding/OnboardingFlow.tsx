import React, { useEffect, useMemo, useRef, useState } from 'react';
import { SimpleForm as Form } from './simple-form';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/api/client';
import { STORAGE_KEYS } from '@/constants/app';
import { configApi } from '../../api/modules/config';
import type {
  LLMConfig,
  SystemConfig,
} from '../../api/modules/config';
import { personasApi } from '../../api/modules/personas';
import type { SeedPreview } from '../../api/modules/personas';
import { listInstallable, type InstallableItem } from '../../api/modules/systemSuggestions';
import { cloneLLMConfig } from '../config-forms/llm-form-state';
import GuidedConfigFrame from '../config-forms/GuidedConfigFrame';
import WelcomeScreen from './WelcomeScreen';
import StepIndicator from './StepIndicator';
import CompletionScreen from './CompletionScreen';
import FirstContextStep from './FirstContextStep';
import LLMSetupStep from './LLMSetupStep';
import { PersonaPreviewChat, type CustomPersonaDraft } from './PersonaPreviewChat';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';

const STORAGE_KEY = STORAGE_KEYS.ONBOARDING_STATE;
const RUNTIME_READY_WAIT_INTERVAL_MS = 500;
const RUNTIME_READY_WAIT_TIMEOUT_MS = 12_000;
const ONBOARDING_SAVE_TIMEOUT_MS = 20_000;
const PERSONA_SETUP_TIMEOUT_MS = 15_000;
const toI18nLanguage = (language?: string): 'en' | 'zh-CN' => (language === 'en' ? 'en' : 'zh-CN');
const LLM_SETUP_STEP = 1;
const PERSONA_STEP = 2;
const FIRST_CONTEXT_STEP = 3;
const COMPLETE_STEP = 4;

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


class OnboardingTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OnboardingTimeoutError';
  }
}


function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  message: string,
): Promise<T> {
  let timeoutId: number | undefined;
  const timeoutPromise = new Promise<T>((_, reject) => {
    timeoutId = window.setTimeout(() => {
      reject(new OnboardingTimeoutError(message));
    }, timeoutMs);
  });

  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timeoutId !== undefined) {
      window.clearTimeout(timeoutId);
    }
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


interface OnboardingFlowProps {
  initialConfig: SystemConfig;
}

export const OnboardingFlow: React.FC<OnboardingFlowProps> = ({ initialConfig }) => {
  const { t, i18n } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [current, setCurrent] = useState(0);
  const [saving, setSaving] = useState(false);
  const [finishingRuntime, setFinishingRuntime] = useState(false);
  const finishInFlightRef = useRef(false);
  const [renderLanguage, setRenderLanguage] = useState(i18n.resolvedLanguage || i18n.language);
  const [llmValid, setLlmValid] = useState(false);
  const [llmValue, setLlmValue] = useState<LLMConfig>(() =>
    cloneLLMConfig(initialConfig.llm)
  );
  const [seedSlug, setSeedSlug] = useState<string | null>(null);
  // Onboarding-generated (unsaved) personas; persisted on completion.
  const [customPersonas, setCustomPersonas] = useState<CustomPersonaDraft[]>([]);
  // True while a custom persona is being generated on the persona step.
  const [personaGenerating, setPersonaGenerating] = useState(false);
  const [installableItems, setInstallableItems] = useState<InstallableItem[]>([]);
  const [installableLoading, setInstallableLoading] = useState(true);
  const [firstContextPluginIds, setFirstContextPluginIds] = useState<string[]>([]);
  const installablePreloadStartedRef = useRef(false);
  const mountedRef = useRef(true);

  // Persona previews (loaded once on mount for the active locale).
  const [seedPreviews, setSeedPreviews] = useState<SeedPreview[]>([]);

  const activeLanguage = i18n.resolvedLanguage || i18n.language;
  const debugI18n = localStorage.getItem('magi_i18n_debug') === '1';

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const formLanguage = initialConfig.preferences?.language || 'zh';
    const configuredLanguage = toI18nLanguage(formLanguage);

    document.documentElement.lang = configuredLanguage;
    setRenderLanguage(configuredLanguage);

    if ((i18n.resolvedLanguage || i18n.language) !== configuredLanguage) {
      void i18n.changeLanguage(configuredLanguage);
    }
  }, [i18n, initialConfig.preferences?.language]);

  // Linear sequence: Welcome → LLM Setup → Persona Preview → First Context → Complete
  const steps = useMemo(
    () => [
      t('steps.welcome'),
      t('steps.llmSetup'),
      t('steps.personaPreview'),
      t('steps.firstContext'),
      t('steps.complete'),
    ],
    [t, activeLanguage]
  );

  const isLastStep = current === steps.length - 1;

  // Seed locale folder ("zh" / "en"). Drives both which previews we load and
  // which preset folder the preview chat resolves a seed_slug against — they
  // must agree, or the backend can't find the seed.
  const seedLocale = (initialConfig.preferences?.language || 'en').startsWith('zh')
    ? 'zh'
    : 'en';

  // Load persona seed previews for the current locale once on mount and when
  // language changes. This keeps the avatar rail in sync with i18n.
  useEffect(() => {
    let cancelled = false;
    const locale = seedLocale;
    void (async () => {
      try {
        const resp = await personasApi.seedPreviews(locale);
        if (cancelled) return;
        const data = (resp as any)?.data ?? [];
        setSeedPreviews(Array.isArray(data) ? data : []);
      } catch {
        // Persona preview is best-effort; chat preview server may be offline.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialConfig.preferences?.language]);

  // Restore saved progress
  useEffect(() => {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (!cached) return;
    try {
      const parsed = JSON.parse(cached) as {
        current?: number;
        values?: SystemConfig;
        seedSlug?: string | null;
        customPersonas?: CustomPersonaDraft[];
        firstContextPluginIds?: string[];
      };
      if (typeof parsed.current === 'number') {
        setCurrent(parsed.current);
      }
      if (parsed.seedSlug) {
        setSeedSlug(parsed.seedSlug);
      }
      if (Array.isArray(parsed.customPersonas)) {
        setCustomPersonas(parsed.customPersonas);
      }
      if (Array.isArray(parsed.firstContextPluginIds)) {
        setFirstContextPluginIds(
          parsed.firstContextPluginIds.filter((pluginId) => typeof pluginId === 'string'),
        );
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
        if (parsed.values.llm) {
          setLlmValue(cloneLLMConfig(parsed.values.llm));
        }
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

  useEffect(() => {
    if (current < 1 || installablePreloadStartedRef.current) {
      return;
    }

    installablePreloadStartedRef.current = true;
    setInstallableLoading(true);
    void listInstallable()
      .then((items) => {
        if (mountedRef.current) {
          setInstallableItems(items);
        }
      })
      .catch(() => {
        if (mountedRef.current) {
          setInstallableItems([]);
        }
      })
      .finally(() => {
        if (mountedRef.current) {
          setInstallableLoading(false);
        }
      });
  }, [current]);

  const saveProgress = (
    values: SystemConfig,
    nextSeedSlug: string | null = seedSlug,
    nextCustomPersonas: CustomPersonaDraft[] = customPersonas,
    nextCurrent: number = current,
    nextFirstContextPluginIds: string[] = firstContextPluginIds,
  ) => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        current: nextCurrent,
        values,
        seedSlug: nextSeedSlug,
        customPersonas: nextCustomPersonas,
        firstContextPluginIds: nextFirstContextPluginIds,
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

  const handleLlmChange = (next: LLMConfig) => {
    setLlmValue(next);
    form.setFieldValue(['llm'], next);
    saveProgress(form.getFieldsValue(true));
  };

  const persistPersonaSelection = async (locale: string) => {
    await personasApi.seed(locale);

    // Remember the client slug to assigned persona id mapping for activation.
    const customIdBySlug: Record<string, string> = {};
    for (const draft of customPersonas) {
      try {
        const created = await personasApi.create({
          config_json: JSON.stringify(draft.config),
          locale,
        });
        const createdId = created?.data?.persona_id;
        if (createdId) customIdBySlug[draft.slug] = createdId;
      } catch {
        // Best-effort: a failed custom-persona create shouldn't block
        // onboarding completion.
      }
    }

    const listResult = await personasApi.list();
    const personas = listResult.data || [];
    let activatedPersonaId: string | undefined;
    if (seedSlug && customIdBySlug[seedSlug]) {
      activatedPersonaId = customIdBySlug[seedSlug];
    } else if (seedSlug) {
      const match = personas.find((p) => p.slug === seedSlug);
      if (match) activatedPersonaId = match.persona_id;
    }
    if (!activatedPersonaId && personas.length > 0) {
      activatedPersonaId = personas[0].persona_id;
    }
    if (activatedPersonaId) {
      await personasApi.setActive(activatedPersonaId);
    }
  };

  const markFirstContextHandled = () => {
    const values = form.getFieldsValue(true) as SystemConfig;
    if (!values.preferences) {
      values.preferences = { ...initialConfig.preferences };
    }
    values.preferences.product_tour_completed = true;
    form.setFieldsValue(values);
    saveProgress(values, seedSlug, customPersonas, COMPLETE_STEP, firstContextPluginIds);
  };

  const finishFirstContextStep = () => {
    markFirstContextHandled();
    setCurrent(COMPLETE_STEP);
  };

  const handleFirstContextConnectDone = (pluginId: string) => {
    const values = form.getFieldsValue(true) as SystemConfig;
    setFirstContextPluginIds((prev) => {
      if (prev.includes(pluginId)) {
        saveProgress(values, seedSlug, customPersonas, FIRST_CONTEXT_STEP, prev);
        return prev;
      }
      const next = [...prev, pluginId];
      saveProgress(values, seedSlug, customPersonas, FIRST_CONTEXT_STEP, next);
      return next;
    });
  };

  const persistRuntimeConfigBeforeFirstContext = async (): Promise<boolean> => {
    setSaving(true);
    try {
      const values = form.getFieldsValue(true) as SystemConfig;
      if (!values.preferences) {
        values.preferences = { ...initialConfig.preferences };
      }
      values.llm = llmValue;
      await withTimeout(
        configApi.updateOnboardingDraft({
          language: values.preferences.language,
          llm: values.llm,
        }),
        ONBOARDING_SAVE_TIMEOUT_MS,
        t('messages.saveTimedOut'),
      );
      saveProgress(values, seedSlug, customPersonas, FIRST_CONTEXT_STEP, firstContextPluginIds);
      return true;
    } catch (error: any) {
      toast.error(error?.message || t('messages.saveFailed'));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const enterAppAfterCompletion = (language: string | undefined) => {
    localStorage.removeItem(STORAGE_KEY);
    if (language) {
      localStorage.setItem('magi_language', language);
    }
    if (language !== initialConfig.preferences.language) {
      window.location.href = '/';
      return;
    }
    navigate('/');
  };

  const recoverCompletedOnboarding = async (): Promise<boolean> => {
    try {
      const response = await configApi.getOnboardingStatus();
      if (response.data?.completed !== true) {
        return false;
      }
      const values = form.getFieldsValue(true) as SystemConfig;
      enterAppAfterCompletion(values.preferences?.language);
      return true;
    } catch {
      return false;
    }
  };

  const handleFinish = async () => {
    if (finishInFlightRef.current) {
      return;
    }
    finishInFlightRef.current = true;
    setSaving(true);

    try {
      const values = form.getFieldsValue(true) as SystemConfig;
      values.preferences.onboarding_completed = true;
      values.preferences.product_tour_completed = true;
      // Ensure the latest LLM state and selected persona slug land in the payload.
      values.llm = llmValue;
      await withTimeout(
        configApi.completeOnboarding({
          language: values.preferences.language,
          llm: values.llm,
        }),
        ONBOARDING_SAVE_TIMEOUT_MS,
        t('messages.saveTimedOut'),
      );

      const locale = (values.preferences?.language || 'en').startsWith('zh') ? 'zh' : 'en';
      try {
        await withTimeout(
          persistPersonaSelection(locale),
          PERSONA_SETUP_TIMEOUT_MS,
          t('messages.personaSetupTimedOut'),
        );
      } catch (error: any) {
        if (error instanceof OnboardingTimeoutError) {
          toast.warning(error.message);
        }
        // Persona registry is best-effort during onboarding;
        // the backend lifecycle fallback handles missing registry state.
      }

      setFinishingRuntime(true);
      const runtimeSnapshot = await waitForRuntimeReadyAfterOnboarding();
      setFinishingRuntime(false);

      if (!runtimeSnapshot?.runtime_ready) {
        toast.warning(t('messages.runtimeStartingSlow'));
      }

      enterAppAfterCompletion(values.preferences.language);
    } catch (error: any) {
      if (await recoverCompletedOnboarding()) {
        return;
      }
      toast.error(error?.message || t('messages.saveFailed'));
    } finally {
      finishInFlightRef.current = false;
      setSaving(false);
      setFinishingRuntime(false);
    }
  };

  /** Handle language change from welcome screen. */
  const handleWelcomeLanguageChange = (lang: 'zh' | 'en') => {
    form.setFieldValue(['preferences', 'language'], lang);
    localStorage.setItem('magi_language', lang);
    const mapped = toI18nLanguage(lang);
    document.documentElement.lang = mapped;
    void i18n.changeLanguage(mapped);
  };

  const handleNext = async () => {
    if (current === LLM_SETUP_STEP && !llmValid) {
      toast.warning(t('llm.completeSelections'));
      return;
    }

    if (current === PERSONA_STEP) {
      const persisted = await persistRuntimeConfigBeforeFirstContext();
      if (!persisted) {
        return;
      }
    }

    if (current === FIRST_CONTEXT_STEP) {
      finishFirstContextStep();
      return;
    }

    if (isLastStep) {
      await handleFinish();
      return;
    }

    const next = Math.min(steps.length - 1, current + 1);
    saveProgress(form.getFieldsValue(true), seedSlug, customPersonas, next);
    setCurrent(next);
  };

  const handlePrev = () => {
    const prev = Math.max(0, current - 1);
    saveProgress(form.getFieldsValue(true), seedSlug, customPersonas, prev);
    setCurrent(prev);
  };

  // The persona preview step uses the standard Previous/Next footer (the
  // active persona in the rail is the selection; Next confirms it). The
  // completion screen uses its own Enter App CTA, so the footer is hidden there.
  const hideFooter = isLastStep;
  const nextLabel = current === FIRST_CONTEXT_STEP
    ? firstContextPluginIds.length > 0
      ? t('actions.finishContext')
      : t('actions.skipContext')
    : t('actions.next');

  const renderStepContent = () => {
    if (current === LLM_SETUP_STEP) {
      // LLMSetupStep delegates to LLMForm, which self-loads the provider
      // catalog and shows its own loading state — no registry plumbing needed
      // from OnboardingFlow.
      return (
        <LLMSetupStep
          value={llmValue}
          onChange={handleLlmChange}
          onValid={setLlmValid}
        />
      );
    }

    if (current === PERSONA_STEP) {
      return (
        <PersonaPreviewChat
          previews={seedPreviews}
          locale={seedLocale}
          llmConfig={llmValue}
          initialCustomPersonas={customPersonas}
          onActiveSeedChange={(slug) => {
            setSeedSlug(slug);
            saveProgress(form.getFieldsValue(true), slug);
          }}
          onCustomPersonasChange={(drafts) => {
            setCustomPersonas(drafts);
            saveProgress(form.getFieldsValue(true), seedSlug, drafts);
          }}
          onGeneratingChange={setPersonaGenerating}
        />
      );
    }

    if (current === FIRST_CONTEXT_STEP) {
      return (
        <FirstContextStep
          llmConfig={llmValue}
          installableItems={installableItems}
          installableLoading={installableLoading}
          connectedPluginIds={firstContextPluginIds}
          onConnectDone={handleFirstContextConnectDone}
        />
      );
    }

    if (current === COMPLETE_STEP) {
      return (
        <CompletionScreen
          onFinish={handleFinish}
          loading={saving || finishingRuntime}
          loadingLabel={finishingRuntime ? t('actions.startingRuntime') : t('actions.saving')}
        />
      );
    }

    return null;
  };

  // Step 0: full-screen welcome
  if (current === 0) {
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
          onContinue={() => {
            setCurrent(LLM_SETUP_STEP);
            saveProgress(
              form.getFieldsValue(true),
              seedSlug,
              customPersonas,
              LLM_SETUP_STEP,
              firstContextPluginIds,
            );
          }}
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
          footer={hideFooter ? null : (
            <div className="flex items-center justify-between gap-3">
              <Button
                variant="outline"
                onClick={handlePrev}
                disabled={saving || (current === PERSONA_STEP && personaGenerating)}
              >
                {t('actions.previous')}
              </Button>
              <Button
                onClick={handleNext}
                disabled={
                  saving ||
                  (current === LLM_SETUP_STEP && !llmValid) ||
                  (current === PERSONA_STEP && personaGenerating)
                }
              >
                {saving
                  ? (finishingRuntime ? t('actions.startingRuntime') : t('actions.saving'))
                  : nextLabel}
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
                className="flex h-full min-h-0 flex-1 flex-col"
                key={`${renderLanguage}-${current}`}
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

export default OnboardingFlow;
