import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  TestLLMProviderConnectionRequest,
} from '../../api/modules/config';
import { personasApi } from '../../api/modules/personas';
import type { SeedPreview } from '../../api/modules/personas';
import { listInstallable, type InstallableItem } from '../../api/modules/systemSuggestions';
import { cloneLLMConfig, cloneProvider } from '../config-forms/llm-form-state';
import GuidedConfigFrame from '../config-forms/GuidedConfigFrame';
import WelcomeScreen from './WelcomeScreen';
import StepIndicator from './StepIndicator';
import CompletionScreen from './CompletionScreen';
import FirstContextStep from './FirstContextStep';
import LLMSetupStep, { type LLMConnectionTestState } from './LLMSetupStep';
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

interface LlmConnectionTestTarget {
  fingerprint: string;
  request: TestLLMProviderConnectionRequest;
}

const EMPTY_LLM_CONNECTION_TEST_STATE: LLMConnectionTestState = {
  loading: false,
  error: null,
  result: null,
};

function buildLlmConnectionTestTarget(value: LLMConfig): LlmConnectionTestTarget | null {
  const providerId = String(value.selections?.core?.provider_id || '').trim();
  const model = String(value.selections?.core?.model || '').trim();
  const sourceProvider = providerId ? value.providers?.[providerId] : undefined;
  if (!providerId || !model || !sourceProvider) {
    return null;
  }

  const provider = cloneProvider(sourceProvider);
  const apiKey = provider.services.chat.api_key || provider.api_key || '';
  const baseUrl = provider.services.chat.base_url || provider.base_url || '';
  provider.api_key = provider.api_key || apiKey;
  provider.base_url = provider.base_url || baseUrl;
  provider.services.chat.api_key = apiKey;
  provider.services.chat.base_url = baseUrl;

  return {
    fingerprint: JSON.stringify([
      providerId,
      provider.provider_type,
      provider.provider_plan || '',
      provider.api_format,
      model,
      apiKey,
      baseUrl,
    ]),
    request: {
      provider_id: providerId,
      provider,
      model,
    },
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


class PersonaConfirmationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PersonaConfirmationError';
  }
}


class PersonaConfirmationCancelledError extends Error {
  constructor() {
    super('Persona confirmation was superseded');
    this.name = 'PersonaConfirmationCancelledError';
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
  const [renderLanguage, setRenderLanguage] = useState(() =>
    toI18nLanguage(initialConfig.preferences?.language || 'zh'),
  );
  const [llmValid, setLlmValid] = useState(false);
  const [llmValue, setLlmValue] = useState<LLMConfig>(() =>
    cloneLLMConfig(initialConfig.llm)
  );
  const [llmConnectionTestState, setLlmConnectionTestState] =
    useState<LLMConnectionTestState>(EMPTY_LLM_CONNECTION_TEST_STATE);
  const [validatedLlmFingerprint, setValidatedLlmFingerprint] = useState<string | null>(null);
  const [llmConnectionConfigPending, setLlmConnectionConfigPending] = useState(false);
  const llmConnectionTestRequestIdRef = useRef(0);
  const [seedSlug, setSeedSlug] = useState<string | null>(null);
  const seedSlugRef = useRef<string | null>(null);
  // Onboarding-generated personas carry their final registry IDs before creation.
  const [customPersonas, setCustomPersonas] = useState<CustomPersonaDraft[]>([]);
  const customPersonasRef = useRef<CustomPersonaDraft[]>([]);
  // True while a custom persona is being generated on the persona step.
  const [personaGenerating, setPersonaGenerating] = useState(false);
  const [personaConfirming, setPersonaConfirming] = useState(false);
  const [personaConfirmationError, setPersonaConfirmationError] = useState<string | null>(null);
  const [confirmedPersonaFingerprint, setConfirmedPersonaFingerprint] = useState<string | null>(
    null,
  );
  const personaConfirmationRequestIdRef = useRef(0);
  const personaConfirmationInFlightRef = useRef(false);
  const [installableItems, setInstallableItems] = useState<InstallableItem[]>([]);
  const [installableLoading, setInstallableLoading] = useState(true);
  const [installableError, setInstallableError] = useState<Error | null>(null);
  const [firstContextPluginIds, setFirstContextPluginIds] = useState<string[]>([]);
  const installablePreloadStartedRef = useRef(false);
  const mountedRef = useRef(true);
  const llmConnectionTestTarget = useMemo(
    () => buildLlmConnectionTestTarget(llmValue),
    [llmValue],
  );
  const currentLlmFingerprint = llmConnectionTestTarget?.fingerprint || '';
  const currentLlmFingerprintRef = useRef(currentLlmFingerprint);
  currentLlmFingerprintRef.current = currentLlmFingerprint;
  seedSlugRef.current = seedSlug;
  customPersonasRef.current = customPersonas;

  const loadInstallableSources = useCallback(async () => {
    setInstallableLoading(true);
    setInstallableError(null);
    try {
      const items = await listInstallable();
      if (mountedRef.current) {
        setInstallableItems(items);
      }
    } catch (caught) {
      if (mountedRef.current) {
        setInstallableItems([]);
        setInstallableError(
          caught instanceof Error
            ? caught
            : new Error('Failed to load installable sources'),
        );
      }
    } finally {
      if (mountedRef.current) {
        setInstallableLoading(false);
      }
    }
  }, []);

  // Persona previews (loaded once on mount for the active locale).
  const [seedPreviews, setSeedPreviews] = useState<SeedPreview[]>([]);
  const [seedPreviewsLoading, setSeedPreviewsLoading] = useState(true);

  const activeLanguage = i18n.resolvedLanguage || i18n.language;
  const debugI18n = localStorage.getItem('magi_i18n_debug') === '1';

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      personaConfirmationRequestIdRef.current += 1;
      personaConfirmationInFlightRef.current = false;
    };
  }, []);

  useEffect(() => {
    const formLanguage = initialConfig.preferences?.language || 'zh';
    const configuredLanguage = toI18nLanguage(formLanguage);

    document.documentElement.lang = configuredLanguage;

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
  const onboardingLanguage = renderLanguage.startsWith('zh') ? 'zh' : 'en';
  const onboardingInitialValues = useMemo<SystemConfig>(
    () => ({
      ...initialConfig,
      preferences: {
        ...initialConfig.preferences,
        language: onboardingLanguage,
      },
    }),
    [initialConfig, onboardingLanguage],
  );

  // Seed locale folder ("zh" / "en"). Drives both which previews we load and
  // which preset folder the preview chat resolves a seed_slug against — they
  // must agree, or the backend can't find the seed.
  const seedLocale = onboardingLanguage;
  const selectedCustomPersona = useMemo(
    () => customPersonas.find((draft) => draft.slug === seedSlug) ?? null,
    [customPersonas, seedSlug],
  );
  const personaConfirmationFingerprint = useMemo(
    () => seedSlug
      ? JSON.stringify([
          seedLocale,
          seedSlug,
          selectedCustomPersona?.personaId ?? null,
          selectedCustomPersona?.config ?? null,
        ])
      : null,
    [seedLocale, seedSlug, selectedCustomPersona],
  );
  const currentPersonaFingerprintRef = useRef<string | null>(personaConfirmationFingerprint);
  currentPersonaFingerprintRef.current = personaConfirmationFingerprint;

  // Load persona seed previews for the current locale once on mount and when
  // language changes. This keeps the avatar rail in sync with i18n.
  useEffect(() => {
    let cancelled = false;
    const locale = seedLocale;
    setSeedPreviewsLoading(true);
    setSeedPreviews([]);
    void (async () => {
      try {
        const resp = await personasApi.seedPreviews(locale);
        if (cancelled) return;
        const data = (resp as any)?.data ?? [];
        setSeedPreviews(Array.isArray(data) ? data : []);
      } catch {
        // Persona preview is best-effort; chat preview server may be offline.
      } finally {
        if (!cancelled) {
          setSeedPreviewsLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [seedLocale]);

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
        const recoveredStep = Math.max(0, Math.min(COMPLETE_STEP, parsed.current));
        setCurrent(recoveredStep > LLM_SETUP_STEP ? LLM_SETUP_STEP : recoveredStep);
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
    void loadInstallableSources();
  }, [current, loadInstallableSources]);

  const saveProgress = (
    values: SystemConfig,
    nextSeedSlug: string | null = seedSlugRef.current,
    nextCustomPersonas: CustomPersonaDraft[] = customPersonasRef.current,
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
      setRenderLanguage(toI18nLanguage(lng));
    };
    i18n.on('languageChanged', handleLanguageChanged);
    return () => {
      i18n.off('languageChanged', handleLanguageChanged);
    };
  }, [i18n]);

  const handleLlmChange = (next: LLMConfig) => {
    const nextFingerprint = buildLlmConnectionTestTarget(next)?.fingerprint || '';
    if (nextFingerprint !== currentLlmFingerprint) {
      llmConnectionTestRequestIdRef.current += 1;
      setValidatedLlmFingerprint(null);
      setLlmConnectionTestState(EMPTY_LLM_CONNECTION_TEST_STATE);
    }
    setLlmValue(next);
    form.setFieldValue(['llm'], next);
    saveProgress(form.getFieldsValue(true));
  };

  const testLlmConnection = async (force = false): Promise<boolean> => {
    const target = buildLlmConnectionTestTarget(llmValue);
    if (!target) {
      setValidatedLlmFingerprint(null);
      setLlmConnectionTestState({
        loading: false,
        error: t('llm.providerConfiguration.testModelRequired'),
        result: null,
      });
      return false;
    }

    if (
      !force &&
      validatedLlmFingerprint === target.fingerprint &&
      llmConnectionTestState.result
    ) {
      return true;
    }

    const requestId = ++llmConnectionTestRequestIdRef.current;
    setValidatedLlmFingerprint(null);
    setLlmConnectionTestState({ loading: true, error: null, result: null });
    try {
      const result = await configApi.testLLMProviderConnection(target.request);
      if (
        requestId !== llmConnectionTestRequestIdRef.current ||
        currentLlmFingerprintRef.current !== target.fingerprint
      ) {
        return false;
      }
      setValidatedLlmFingerprint(target.fingerprint);
      setLlmConnectionTestState({ loading: false, error: null, result });
      return true;
    } catch (testError: any) {
      if (
        requestId !== llmConnectionTestRequestIdRef.current ||
        currentLlmFingerprintRef.current !== target.fingerprint
      ) {
        return false;
      }
      setLlmConnectionTestState({
        loading: false,
        error: testError?.message || t('llm.providerConfiguration.testFailed'),
        result: null,
      });
      return false;
    }
  };

  const invalidatePersonaConfirmation = () => {
    personaConfirmationRequestIdRef.current += 1;
    personaConfirmationInFlightRef.current = false;
    setPersonaConfirming(false);
    setPersonaConfirmationError(null);
    setConfirmedPersonaFingerprint(null);
  };

  const confirmPersonaSelection = async (): Promise<boolean> => {
    const fingerprint = personaConfirmationFingerprint;
    const selectedSlug = seedSlug;
    const customDraft = selectedCustomPersona;

    if (!fingerprint || !selectedSlug) {
      personaConfirmationRequestIdRef.current += 1;
      personaConfirmationInFlightRef.current = false;
      setPersonaConfirming(false);
      setConfirmedPersonaFingerprint(null);
      setPersonaConfirmationError(t('messages.personaSelectionRequired'));
      return false;
    }
    if (confirmedPersonaFingerprint === fingerprint) {
      return true;
    }
    if (personaConfirmationInFlightRef.current) {
      return false;
    }

    const requestId = ++personaConfirmationRequestIdRef.current;
    personaConfirmationInFlightRef.current = true;
    setPersonaConfirming(true);
    setPersonaConfirmationError(null);
    setConfirmedPersonaFingerprint(null);

    const assertCurrentRequest = () => {
      if (
        requestId !== personaConfirmationRequestIdRef.current ||
        currentPersonaFingerprintRef.current !== fingerprint
      ) {
        throw new PersonaConfirmationCancelledError();
      }
    };

    const runConfirmation = async () => {
      let personaId: string;

      if (customDraft) {
        // Persist the final ID and config before any create request can leave the client.
        saveProgress(
          form.getFieldsValue(true),
          selectedSlug,
          customPersonasRef.current,
        );
        const created = await personasApi.create({
          persona_id: customDraft.personaId,
          slug: customDraft.slug,
          config_json: JSON.stringify(customDraft.config),
          locale: seedLocale,
        });
        assertCurrentRequest();
        if (created?.data?.persona_id !== customDraft.personaId) {
          throw new PersonaConfirmationError(t('messages.personaActivationFailed'));
        }
        personaId = customDraft.personaId;
      } else {
        await personasApi.seed(seedLocale);
        assertCurrentRequest();
        const listResult = await personasApi.list();
        assertCurrentRequest();
        const builtin = (listResult.data || []).find(
          (persona) => persona.is_builtin === true && persona.seed_slug === selectedSlug,
        );
        if (!builtin) {
          throw new PersonaConfirmationError(t('messages.personaUnavailable'));
        }
        personaId = builtin.persona_id;
      }

      const activated = await personasApi.setActive(personaId);
      assertCurrentRequest();
      if (activated.persona_id !== personaId) {
        throw new PersonaConfirmationError(t('messages.personaActivationFailed'));
      }
    };

    try {
      await withTimeout(
        runConfirmation(),
        PERSONA_SETUP_TIMEOUT_MS,
        t('messages.personaSetupTimedOut'),
      );
      assertCurrentRequest();
      personaConfirmationInFlightRef.current = false;
      setPersonaConfirming(false);
      setPersonaConfirmationError(null);
      setConfirmedPersonaFingerprint(fingerprint);
      return true;
    } catch (error: unknown) {
      if (
        error instanceof PersonaConfirmationCancelledError ||
        requestId !== personaConfirmationRequestIdRef.current ||
        currentPersonaFingerprintRef.current !== fingerprint
      ) {
        return false;
      }

      personaConfirmationRequestIdRef.current += 1;
      personaConfirmationInFlightRef.current = false;
      setPersonaConfirming(false);
      setConfirmedPersonaFingerprint(null);
      if (error instanceof OnboardingTimeoutError || error instanceof PersonaConfirmationError) {
        setPersonaConfirmationError(error.message);
      } else {
        setPersonaConfirmationError(t('messages.personaActivationFailed'));
      }
      return false;
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
    setRenderLanguage(mapped);
    void i18n.changeLanguage(mapped);
  };

  const handleNext = async () => {
    if (current === LLM_SETUP_STEP) {
      if (!llmValid) {
        toast.warning(t('llm.completeSelections'));
        return;
      }
      if (!(await testLlmConnection())) {
        return;
      }
    }

    if (current === PERSONA_STEP) {
      if (!(await confirmPersonaSelection())) {
        return;
      }
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
          connectionTestState={llmConnectionTestState}
          onTestConnection={testLlmConnection}
          onConnectionConfigPendingChange={setLlmConnectionConfigPending}
        />
      );
    }

    if (current === PERSONA_STEP) {
      return (
        <PersonaPreviewChat
          previews={seedPreviews}
          previewsLoading={seedPreviewsLoading}
          activeSeed={seedSlug}
          disabled={personaConfirming || saving}
          confirmationError={personaConfirmationError}
          locale={seedLocale}
          llmConfig={llmValue}
          initialCustomPersonas={customPersonas}
          onActiveSeedChange={(slug) => {
            if (slug === seedSlugRef.current) {
              return;
            }
            invalidatePersonaConfirmation();
            seedSlugRef.current = slug;
            setSeedSlug(slug);
            saveProgress(form.getFieldsValue(true), slug, customPersonasRef.current);
          }}
          onCustomPersonasChange={(drafts) => {
            invalidatePersonaConfirmation();
            customPersonasRef.current = drafts;
            setCustomPersonas(drafts);
            saveProgress(form.getFieldsValue(true), seedSlugRef.current, drafts);
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
          installableError={installableError}
          onRetryInstallable={loadInstallableSources}
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
        initialValues={onboardingInitialValues}
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
                disabled={
                  saving ||
                  llmConnectionConfigPending ||
                  (current === PERSONA_STEP && (personaGenerating || personaConfirming))
                }
              >
                {t('actions.previous')}
              </Button>
              <Button
                onClick={handleNext}
                disabled={
                  saving ||
                  llmConnectionConfigPending ||
                  llmConnectionTestState.loading ||
                  (current === LLM_SETUP_STEP && !llmValid) ||
                  (current === PERSONA_STEP && (personaGenerating || personaConfirming))
                }
              >
                {current === LLM_SETUP_STEP && llmConnectionTestState.loading
                  ? t('llm.actions.testingConnection')
                  : current === PERSONA_STEP && personaConfirming
                  ? t('actions.activatingPersona')
                  : saving
                  ? (finishingRuntime ? t('actions.startingRuntime') : t('actions.saving'))
                  : nextLabel}
              </Button>
            </div>
          )}
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={onboardingInitialValues}
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
