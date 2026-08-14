import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { SimpleForm as Form } from "./simple-form";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router";
import {
  CHAT_SESSION_KEY,
  DEFAULT_USER_ID,
  STORAGE_KEYS,
} from "@/constants/app";
import { useConversationStore } from "@/stores/conversation-store";
import { configApi } from "../../api/modules/config";
import type {
  LanguageCode,
  LLMConfig,
  SystemConfig,
} from "../../api/modules/config";
import { personasApi } from "../../api/modules/personas";
import type { SeedPreview } from "../../api/modules/personas";
import {
  listInstallable,
  type InstallableCatalogMode,
  type InstallableItem,
} from "../../api/modules/systemSuggestions";
import GuidedConfigFrame from "../config-forms/GuidedConfigFrame";
import WelcomeScreen from "./WelcomeScreen";
import StepIndicator from "./StepIndicator";
import CompletionScreen from "./CompletionScreen";
import FirstContextStep from "./FirstContextStep";
import LLMSetupStep from "./LLMSetupStep";
import {
  PersonaPreviewChat,
  type CustomPersonaDraft,
  type PersonaCreationDraft,
} from "./PersonaPreviewChat";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, ArrowRight } from "lucide-react";
import type { PluginInstallDoneInfo } from "../../stores/pluginInstallPanel";
import type { HistoryImportJob } from "@/api/modules/historyImports";
import type {
  HistoryImportFlowActionState,
  HistoryImportFlowHandle,
} from "@/components/history-imports/HistoryImportFlow";
import {
  ONBOARDING_PRIMARY_ACTION_CLASS,
  ONBOARDING_SECONDARY_ACTION_CLASS,
} from "./onboardingStyles";
import {
  useOnboardingProgress,
  type FirstContextProgress,
} from "./onboardingProgress";
import { useOnboardingLlmSetup } from "./useOnboardingLlmSetup";
import { usePersonaConfirmation } from "./usePersonaConfirmation";
import { useFirstContextSubmission } from "./useFirstContextSubmission";
import { waitForRuntimeReadyAfterOnboarding } from "./firstContextSubmissionFlow";

const STORAGE_KEY = STORAGE_KEYS.ONBOARDING_STATE;
const ONBOARDING_SAVE_TIMEOUT_MS = 20_000;
const normalizeLanguageCode = (language?: string): LanguageCode =>
  language === "en" ? "en" : "zh";
const toI18nLanguage = (language?: string): "en" | "zh-CN" =>
  language === "en" ? "en" : "zh-CN";
const LLM_SETUP_STEP = 1;
const PERSONA_STEP = 2;
const FIRST_CONTEXT_STEP = 3;
const COMPLETE_STEP = 4;

interface FinishOnboardingOptions {
  destination?: "/" | "/chat";
  sessionId?: string | null;
  onError?: (message: string) => void;
}

class OnboardingTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OnboardingTimeoutError";
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

interface OnboardingFlowProps {
  initialConfig: SystemConfig;
}

export const OnboardingFlow: React.FC<OnboardingFlowProps> = ({
  initialConfig,
}) => {
  const { t, i18n } = useTranslation("onboarding");
  const shouldReduceMotion = useReducedMotion();
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const {
    state: onboardingProgress,
    stateRef: onboardingProgressRef,
    save: saveOnboardingProgress,
    clear: clearOnboardingProgress,
  } = useOnboardingProgress({ storageKey: STORAGE_KEY, initialConfig });
  const {
    current,
    seedSlug,
    customPersonas,
    personaCreationDraft,
    firstContextPluginIds,
    firstContextCountsByPluginId,
    firstContextProgress,
  } = onboardingProgress;
  const [saving, setSaving] = useState(false);
  const [finishingRuntime, setFinishingRuntime] = useState(false);
  const [firstContextHistoryJob, setFirstContextHistoryJob] =
    useState<HistoryImportJob | null>(null);
  const [historyImportActionState, setHistoryImportActionState] =
    useState<HistoryImportFlowActionState>({
      canConfirm: false,
      busy: false,
      primaryAction: null,
    });
  const historyImportFlowRef = useRef<HistoryImportFlowHandle | null>(null);
  const finishInFlightRef = useRef(false);
  const [renderLanguage, setRenderLanguage] = useState(() =>
    toI18nLanguage(
      onboardingProgress.values.preferences?.language || "zh",
    ),
  );
  const llmSetup = useOnboardingLlmSetup(onboardingProgress.values.llm);
  const {
    value: llmValue,
    valid: llmValid,
    connectionTestState: llmConnectionTestState,
    connectionConfigPending: llmConnectionConfigPending,
    setValid: setLlmValid,
    setConnectionConfigPending: setLlmConnectionConfigPending,
    testConnection: testLlmConnection,
  } = llmSetup;
  // True while a custom persona is being generated on the persona step.
  const [personaGenerating, setPersonaGenerating] = useState(false);
  const [installableItems, setInstallableItems] = useState<InstallableItem[]>(
    [],
  );
  const [installableCatalogMode, setInstallableCatalogMode] =
    useState<InstallableCatalogMode | null>(null);
  const [installableLoading, setInstallableLoading] = useState(true);
  const [installableError, setInstallableError] = useState<Error | null>(null);
  const installablePreloadStartedRef = useRef(false);
  const lastPersistedLanguageRef = useRef<LanguageCode | null>(null);
  const lastPersistedDraftFingerprintRef = useRef(
    JSON.stringify({
      language: initialConfig.preferences.language,
      llm: initialConfig.llm,
    }),
  );
  const initializedLanguageRef = useRef<LanguageCode | null>(null);
  const mountedRef = useRef(true);
  const loadInstallableSources = useCallback(async () => {
    setInstallableLoading(true);
    setInstallableError(null);
    try {
      const result = await listInstallable();
      if (mountedRef.current) {
        setInstallableItems(result.items);
        setInstallableCatalogMode(result.catalog_mode);
      }
    } catch (caught) {
      if (mountedRef.current) {
        setInstallableItems([]);
        setInstallableCatalogMode(null);
        setInstallableError(
          caught instanceof Error
            ? caught
            : new Error("Failed to load installable sources"),
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
  const debugI18n = localStorage.getItem("magi_i18n_debug") === "1";

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const persistOnboardingLanguagePreference = useCallback(
    (language: LanguageCode) => {
      if (lastPersistedLanguageRef.current === language) {
        return;
      }
      lastPersistedLanguageRef.current = language;
      void configApi.updateLanguagePreference(language).catch((error) => {
        lastPersistedLanguageRef.current = null;
        console.warn("Failed to persist onboarding language preference", error);
      });
    },
    [],
  );

  useEffect(() => {
    const formLanguage = normalizeLanguageCode(
      onboardingProgress.values.preferences?.language,
    );
    if (initializedLanguageRef.current === formLanguage) {
      return;
    }
    initializedLanguageRef.current = formLanguage;
    const configuredLanguage = toI18nLanguage(formLanguage);

    localStorage.setItem("magi_language", formLanguage);
    document.documentElement.lang = configuredLanguage;
    setRenderLanguage(configuredLanguage);
    persistOnboardingLanguagePreference(formLanguage);

    if ((i18n.resolvedLanguage || i18n.language) !== configuredLanguage) {
      void i18n.changeLanguage(configuredLanguage);
    }
  }, [
    i18n,
    onboardingProgress.values.preferences?.language,
    persistOnboardingLanguagePreference,
  ]);

  // Linear sequence: Welcome → LLM Setup → Persona Preview → First Context → Complete
  const steps = useMemo(
    () => [
      t("steps.welcome"),
      t("steps.llmSetup"),
      t("steps.personaPreview"),
      t("steps.firstContext"),
      t("steps.complete"),
    ],
    [t, activeLanguage],
  );
  const guidedSteps = steps.slice(LLM_SETUP_STEP);

  const isLastStep = current === steps.length - 1;
  const onboardingLanguage = renderLanguage.startsWith("zh") ? "zh" : "en";
  const onboardingInitialValues = useMemo<SystemConfig>(
    () => ({
      ...onboardingProgress.values,
      preferences: {
        ...onboardingProgress.values.preferences,
        language: onboardingLanguage,
      },
    }),
    [onboardingLanguage, onboardingProgress.values],
  );

  // Seed locale folder ("zh" / "en"). Drives both which previews we load and
  // which preset folder the preview chat resolves a seed_slug against — they
  // must agree, or the backend can't find the seed.
  const seedLocale = onboardingLanguage;
  const selectedCustomPersona = useMemo(
    () => customPersonas.find((draft) => draft.slug === seedSlug) ?? null,
    [customPersonas, seedSlug],
  );
  const personaConfirmation = usePersonaConfirmation({
    seedSlug,
    seedLocale,
    selectedCustomPersona,
  });
  const personaConfirming = personaConfirmation.confirming;
  const personaConfirmationError = personaConfirmation.error;

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
        const data = resp.data ?? [];
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

  useEffect(() => {
    if (current < 1 || installablePreloadStartedRef.current) {
      return;
    }

    installablePreloadStartedRef.current = true;
    void loadInstallableSources();
  }, [current, loadInstallableSources]);

  const saveProgress = (
    values: SystemConfig,
    nextSeedSlug?: string | null,
    nextCustomPersonas?: CustomPersonaDraft[],
    nextCurrent?: number,
    nextFirstContextPluginIds?: string[],
    nextFirstContextCountsByPluginId?: Record<string, number | null>,
    nextFirstContextProgress?: FirstContextProgress,
    nextPersonaCreationDraft?: PersonaCreationDraft | null,
  ) => {
    const saved = onboardingProgressRef.current;
    saveOnboardingProgress({
      values,
      current: nextCurrent ?? saved.current,
      seedSlug:
        nextSeedSlug === undefined ? saved.seedSlug : nextSeedSlug,
      customPersonas: nextCustomPersonas ?? saved.customPersonas,
      personaCreationDraft:
        nextPersonaCreationDraft === undefined
          ? saved.personaCreationDraft
          : nextPersonaCreationDraft,
      firstContextPluginIds:
        nextFirstContextPluginIds ?? saved.firstContextPluginIds,
      firstContextCountsByPluginId:
        nextFirstContextCountsByPluginId ??
        saved.firstContextCountsByPluginId,
      firstContextProgress:
        nextFirstContextProgress ?? saved.firstContextProgress,
    });
  };

  const updateFirstContextProgress = (
    update:
      | Partial<FirstContextProgress>
      | ((currentProgress: FirstContextProgress) => FirstContextProgress),
  ): FirstContextProgress => {
    const currentProgress =
      onboardingProgressRef.current.firstContextProgress;
    const nextProgress =
      typeof update === "function"
        ? update(currentProgress)
        : { ...currentProgress, ...update };
    saveProgress(
      form.getFieldsValue(true),
      onboardingProgressRef.current.seedSlug,
      onboardingProgressRef.current.customPersonas,
      onboardingProgressRef.current.current,
      onboardingProgressRef.current.firstContextPluginIds,
      onboardingProgressRef.current.firstContextCountsByPluginId,
      nextProgress,
    );
    return nextProgress;
  };

  const onValuesChange = (_: unknown, allValues: SystemConfig) => {
    const nextLanguage = allValues?.preferences?.language;
    if (nextLanguage) {
      const normalizedLanguage = normalizeLanguageCode(nextLanguage);
      const mapped = toI18nLanguage(normalizedLanguage);
      localStorage.setItem("magi_language", normalizedLanguage);
      document.documentElement.lang = mapped;
      persistOnboardingLanguagePreference(normalizedLanguage);
      if (debugI18n) {
        console.info("[onboarding:i18n] onValuesChange", {
          raw: normalizedLanguage,
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
      console.info("[onboarding:i18n] languageChanged", { lng });
    };
    i18n.on("languageChanged", handleLanguageChanged);
    return () => {
      i18n.off("languageChanged", handleLanguageChanged);
    };
  }, [debugI18n, i18n]);

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      setRenderLanguage(toI18nLanguage(lng));
    };
    i18n.on("languageChanged", handleLanguageChanged);
    return () => {
      i18n.off("languageChanged", handleLanguageChanged);
    };
  }, [i18n]);

  const handleLlmChange = (next: LLMConfig) => {
    llmSetup.change(next);
    form.setFieldValue(["llm"], next);
    saveProgress(form.getFieldsValue(true));
  };

  const invalidatePersonaConfirmation = personaConfirmation.invalidate;
  const confirmPersonaSelection = (): Promise<boolean> =>
    personaConfirmation.confirm(() => {
      saveProgress(
        form.getFieldsValue(true),
        seedSlug,
        onboardingProgressRef.current.customPersonas,
      );
    });

  const markFirstContextHandled = () => {
    const values = form.getFieldsValue(true) as SystemConfig;
    if (!values.preferences) {
      values.preferences = { ...initialConfig.preferences };
    }
    values.preferences.product_tour_completed = true;
    form.setFieldsValue(values);
    saveProgress(
      values,
      seedSlug,
      customPersonas,
      COMPLETE_STEP,
      firstContextPluginIds,
      firstContextCountsByPluginId,
    );
  };

  const finishFirstContextStep = () => {
    markFirstContextHandled();
  };

  const handleHistoryImportActionStateChange = useCallback(
    (state: HistoryImportFlowActionState) => {
      setHistoryImportActionState((currentState) =>
        currentState.canConfirm === state.canConfirm &&
        currentState.busy === state.busy
          ? currentState
          : state,
      );
    },
    [],
  );

  const abandonHistoryImport = async (): Promise<void> => {
    if (historyImportActionState.busy) {
      return;
    }
    const discarded = await historyImportFlowRef.current?.discard();
    if (discarded) {
      finishFirstContextStep();
    }
  };

  const handleFirstContextConnectDone = (
    pluginId: string,
    info?: PluginInstallDoneInfo,
  ) => {
    const values = form.getFieldsValue(true) as SystemConfig;
    const count =
      typeof info?.firstContextCount === "number" &&
      Number.isFinite(info.firstContextCount)
        ? info.firstContextCount
        : null;

    const saved = onboardingProgressRef.current;
    const nextPluginIds = saved.firstContextPluginIds.includes(pluginId)
      ? saved.firstContextPluginIds
      : [...saved.firstContextPluginIds, pluginId];
    const nextCounts = {
      ...saved.firstContextCountsByPluginId,
      [pluginId]: count,
    };
    saveProgress(
      values,
      saved.seedSlug,
      saved.customPersonas,
      FIRST_CONTEXT_STEP,
      nextPluginIds,
      nextCounts,
    );
  };

  const persistOnboardingDraft = async (): Promise<boolean> => {
    const values = form.getFieldsValue(true) as SystemConfig;
    if (!values.preferences) {
      values.preferences = { ...initialConfig.preferences };
    }
    values.llm = llmValue;
    const payload = {
      language: normalizeLanguageCode(values.preferences.language),
      llm: values.llm,
    };
    const fingerprint = JSON.stringify(payload);
    if (lastPersistedDraftFingerprintRef.current === fingerprint) {
      return true;
    }

    setSaving(true);
    try {
      await withTimeout(
        configApi.updateOnboardingDraft(payload),
        ONBOARDING_SAVE_TIMEOUT_MS,
        t("messages.saveTimedOut"),
      );
      lastPersistedDraftFingerprintRef.current = fingerprint;
      saveProgress(values);
      return true;
    } catch (error: any) {
      toast.error(error?.message || t("messages.saveFailed"));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const testAndPersistLlmConnection = async (
    force = false,
  ): Promise<boolean> => {
    if (!(await testLlmConnection(force))) {
      return false;
    }
    return persistOnboardingDraft();
  };

  const enterAppAfterCompletion = (
    language: string | undefined,
    destination: "/" | "/chat" = "/",
    sessionId?: string | null,
  ) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (normalizedSessionId) {
      localStorage.setItem(
        CHAT_SESSION_KEY(DEFAULT_USER_ID),
        normalizedSessionId,
      );
      useConversationStore.getState().setCurrentSessionId(normalizedSessionId);
    }
    clearOnboardingProgress();
    if (language) {
      localStorage.setItem("magi_language", language);
    }
    if (language !== initialConfig.preferences.language) {
      window.location.href = destination;
      return;
    }
    navigate(destination);
  };

  const recoverCompletedOnboarding = async (
    options: FinishOnboardingOptions = {},
  ): Promise<boolean> => {
    try {
      const response = await configApi.getOnboardingStatus();
      if (response.data?.completed !== true) {
        return false;
      }
      const values = form.getFieldsValue(true) as SystemConfig;
      enterAppAfterCompletion(
        values.preferences?.language,
        options.destination,
        options.sessionId,
      );
      return true;
    } catch {
      return false;
    }
  };

  const handleFinish = async (
    options: FinishOnboardingOptions = {},
  ): Promise<boolean> => {
    if (finishInFlightRef.current) {
      return false;
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
        t("messages.saveTimedOut"),
      );

      setFinishingRuntime(true);
      const runtimeSnapshot = await waitForRuntimeReadyAfterOnboarding();
      setFinishingRuntime(false);

      if (!runtimeSnapshot?.runtime_ready) {
        toast.warning(t("messages.runtimeStartingSlow"));
      }

      enterAppAfterCompletion(
        values.preferences.language,
        options.destination,
        options.sessionId,
      );
      return true;
    } catch (error: any) {
      if (await recoverCompletedOnboarding(options)) {
        return true;
      }
      const message = options.onError
        ? t("firstContext.story.errors.finishFailed")
        : error instanceof OnboardingTimeoutError
          ? error.message
          : t("messages.saveFailed");
      if (options.onError) {
        options.onError(message);
      } else {
        toast.error(message);
      }
      return false;
    } finally {
      finishInFlightRef.current = false;
      setSaving(false);
      setFinishingRuntime(false);
    }
  };

  const firstContextSubmission = useFirstContextSubmission({
    progress: firstContextProgress,
    readProgress: () =>
      onboardingProgressRef.current.firstContextProgress,
    updateProgress: updateFirstContextProgress,
    finishOnboarding: handleFinish,
  });
  const firstContextStorySubmitting = firstContextSubmission.submitting;
  const firstContextStoryError = firstContextSubmission.error;

  /** Handle language change from welcome screen. */
  const handleWelcomeLanguageChange = (lang: "zh" | "en") => {
    form.setFieldValue(["preferences", "language"], lang);
    localStorage.setItem("magi_language", lang);
    const mapped = toI18nLanguage(lang);
    document.documentElement.lang = mapped;
    setRenderLanguage(mapped);
    persistOnboardingLanguagePreference(lang);
    void i18n.changeLanguage(mapped);
  };

  const handleNext = async () => {
    if (current === LLM_SETUP_STEP) {
      if (!llmValid) {
        toast.warning(t("llm.completeSelections"));
        return;
      }
      if (!(await testAndPersistLlmConnection())) {
        return;
      }
    }

    if (current === PERSONA_STEP) {
      if (!(await confirmPersonaSelection())) {
        return;
      }
      const persisted = await persistOnboardingDraft();
      if (!persisted) {
        return;
      }
    }

    if (current === FIRST_CONTEXT_STEP) {
      if (firstContextProgress.route === "question") {
        await firstContextSubmission.submit();
        return;
      }
      if (firstContextProgress.route === "history") {
        if (historyImportRestoring || historyImportActionState.busy) {
          return;
        }
        if (historyImportAwaitingConfirmation) {
          await historyImportFlowRef.current?.confirm();
          return;
        }
      }
      finishFirstContextStep();
      return;
    }

    if (isLastStep) {
      await handleFinish();
      return;
    }

    const next = Math.min(steps.length - 1, current + 1);
    saveProgress(form.getFieldsValue(true), seedSlug, customPersonas, next);
  };

  const handlePrev = () => {
    if (
      current === FIRST_CONTEXT_STEP &&
      firstContextProgress.route !== "choose"
    ) {
      firstContextSubmission.changeRoute("choose");
      return;
    }
    const prev = Math.max(0, current - 1);
    saveProgress(form.getFieldsValue(true), seedSlug, customPersonas, prev);
  };

  // The persona preview step uses the standard Previous/Next footer (the
  // active persona in the rail is the selection; Next confirms it). The
  // completion screen uses its own Enter App CTA, so the footer is hidden there.
  const hideFooter = isLastStep;
  const isFirstContextQuestionRoute =
    current === FIRST_CONTEXT_STEP &&
    firstContextProgress.route === "question";
  const isFirstContextHistoryRoute =
    current === FIRST_CONTEXT_STEP &&
    firstContextProgress.route === "history";
  const historyImportRestoring = Boolean(
    isFirstContextHistoryRoute &&
      firstContextProgress.historyImportJobId &&
      firstContextHistoryJob?.job_id !==
        firstContextProgress.historyImportJobId,
  );
  const historyImportAwaitingConfirmation = Boolean(
    isFirstContextHistoryRoute &&
      firstContextHistoryJob &&
      !firstContextHistoryJob.quick_ready &&
      ["preview_ready", "failed"].includes(firstContextHistoryJob.status),
  );
  const historyImportPreparingSelection = Boolean(
    isFirstContextHistoryRoute &&
      ((!firstContextHistoryJob && historyImportActionState.busy) ||
        (firstContextHistoryJob &&
          !firstContextHistoryJob.quick_ready &&
          ["ready", "running"].includes(firstContextHistoryJob.status))),
  );
  const previousLabel =
    current === FIRST_CONTEXT_STEP && firstContextProgress.route !== "choose"
      ? t("firstContext.routes.back")
      : t("actions.previous");
  const nextLabel =
    isFirstContextQuestionRoute
      ? firstContextStorySubmitting
        ? t("firstContext.story.submitting")
        : firstContextProgress.submitted ||
            firstContextProgress.sendUncertain
          ? t("firstContext.story.retryEntering")
          : t("firstContext.story.submit")
      : current === FIRST_CONTEXT_STEP
      ? historyImportRestoring || historyImportPreparingSelection
        ? t("firstContext.history.loading")
        : historyImportAwaitingConfirmation
          ? historyImportActionState.busy
            ? historyImportActionState.primaryAction === "resume"
              ? t("firstContext.history.failed.retrying")
              : t("firstContext.history.preview.importing")
            : historyImportActionState.primaryAction === "resume"
              ? t("firstContext.history.failed.retry")
              : t("firstContext.history.preview.confirm")
          : firstContextPluginIds.length > 0 ||
              firstContextProgress.historyPreparedCount > 0
            ? t("actions.finishContext")
            : t("actions.skipContext")
      : t("actions.next");
  const previousDisabled =
    saving ||
    firstContextStorySubmitting ||
    (current === FIRST_CONTEXT_STEP &&
      (firstContextProgress.submitted ||
        firstContextProgress.sendUncertain)) ||
    llmConnectionConfigPending ||
    (isFirstContextHistoryRoute && historyImportActionState.busy) ||
    (current === PERSONA_STEP &&
      (personaGenerating || personaConfirming));
  const nextDisabled =
    saving ||
    firstContextStorySubmitting ||
    llmConnectionConfigPending ||
    llmConnectionTestState.loading ||
    (current === LLM_SETUP_STEP && !llmValid) ||
    historyImportRestoring ||
    historyImportPreparingSelection ||
    (historyImportAwaitingConfirmation &&
      (!historyImportActionState.canConfirm || historyImportActionState.busy)) ||
    (current === PERSONA_STEP && (personaGenerating || personaConfirming));

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
          onTestConnection={testAndPersistLlmConnection}
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
          initialCreationDraft={personaCreationDraft}
          onActiveSeedChange={(slug) => {
            const saved = onboardingProgressRef.current;
            if (slug === saved.seedSlug) {
              return;
            }
            invalidatePersonaConfirmation();
            saveProgress(
              form.getFieldsValue(true),
              slug,
              saved.customPersonas,
            );
          }}
          onCustomPersonasChange={(drafts) => {
            invalidatePersonaConfirmation();
            const saved = onboardingProgressRef.current;
            saveProgress(
              form.getFieldsValue(true),
              saved.seedSlug,
              drafts,
            );
          }}
          onCreationDraftChange={(draft) => {
            const saved = onboardingProgressRef.current;
            saveProgress(
              form.getFieldsValue(true),
              saved.seedSlug,
              saved.customPersonas,
              saved.current,
              saved.firstContextPluginIds,
              saved.firstContextCountsByPluginId,
              saved.firstContextProgress,
              draft,
            );
          }}
          onGeneratingChange={setPersonaGenerating}
        />
      );
    }

    if (current === FIRST_CONTEXT_STEP) {
      return (
        <FirstContextStep
          llmConfig={llmValue}
          route={firstContextProgress.route}
          questionId={firstContextProgress.questionId}
          storyDraft={firstContextProgress.draft}
          storySubmitting={firstContextStorySubmitting}
          storyLocked={
            firstContextSubmission.locked
          }
          storySubmitted={firstContextSubmission.submitted}
          storyError={firstContextStoryError}
          historyImportJobId={firstContextProgress.historyImportJobId}
          historyImportFlowRef={historyImportFlowRef}
          onHistoryImportUpdate={(job: HistoryImportJob | null) => {
            setFirstContextHistoryJob(job);
            updateFirstContextProgress({
              historyImportJobId: job?.job_id ?? null,
              historyPreparedCount: job?.quick_ready
                ? job.quick_imported_count
                : 0,
            });
          }}
          onHistoryImportActionStateChange={
            handleHistoryImportActionStateChange
          }
          onRouteChange={firstContextSubmission.changeRoute}
          onQuestionChange={firstContextSubmission.changeQuestion}
          onStoryDraftChange={firstContextSubmission.changeDraft}
          onStoryContinueWithoutConfirmation={() =>
            void firstContextSubmission.continueWithoutConfirmation()
          }
          installableItems={installableItems}
          installableCatalogMode={installableCatalogMode}
          installableLoading={installableLoading}
          installableError={installableError}
          onRetryInstallable={loadInstallableSources}
          connectedPluginIds={firstContextPluginIds}
          connectedCountsByPluginId={firstContextCountsByPluginId}
          onConnectDone={handleFirstContextConnectDone}
        />
      );
    }

    if (current === COMPLETE_STEP) {
      return (
        <CompletionScreen
          onFinish={handleFinish}
          connectedSourceCount={firstContextPluginIds.length}
          loading={saving || finishingRuntime}
          loadingLabel={
            finishingRuntime
              ? t("actions.startingRuntime")
              : t("actions.saving")
          }
        />
      );
    }

    return null;
  };

  // Step 0: full-screen welcome
  if (current === 0) {
    const currentLang =
      (form.getFieldValue(["preferences", "language"]) as "zh" | "en") ||
      (onboardingProgress.values.preferences?.language as "zh" | "en") ||
      "zh";

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
    <div className="fixed inset-0 overflow-hidden bg-muted/25">
      <div className="h-full w-full">
        <GuidedConfigFrame
          className="h-full"
          layoutClassName="h-full"
          contentClassName={
            current === LLM_SETUP_STEP ? "overflow-y-auto" : "overflow-hidden"
          }
          sidebar={
            <div className="flex min-w-max items-center lg:h-full lg:min-w-0 lg:flex-col lg:items-stretch">
              <div
                className="hidden select-none px-3 pt-1 lg:block"
                aria-hidden="true"
              >
                <span className="font-onboarding-display text-2xl font-bold tracking-[0.22em] text-foreground/85">
                  Magi
                </span>
              </div>
              <div className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:justify-center">
                <StepIndicator
                  steps={guidedSteps}
                  current={current - LLM_SETUP_STEP}
                />
              </div>
            </div>
          }
          footer={
            hideFooter ? null : (
              <div className="flex items-center justify-between gap-3">
                <Button
                  variant="ghost"
                  size="lg"
                  className={ONBOARDING_SECONDARY_ACTION_CLASS}
                  onClick={handlePrev}
                  disabled={previousDisabled}
                >
                  <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                  {previousLabel}
                </Button>
                <div className="flex items-center gap-2">
                  {historyImportAwaitingConfirmation ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="lg"
                      className={ONBOARDING_SECONDARY_ACTION_CLASS}
                      onClick={() => void abandonHistoryImport()}
                      disabled={historyImportActionState.busy}
                    >
                      {t("actions.abandonImport")}
                    </Button>
                  ) : null}
                  <Button
                    size="lg"
                    data-testid={
                      isFirstContextQuestionRoute
                        ? "first-context-story-submit"
                        : undefined
                    }
                    className={ONBOARDING_PRIMARY_ACTION_CLASS}
                    onClick={handleNext}
                    disabled={nextDisabled}
                  >
                    {current === LLM_SETUP_STEP && llmConnectionTestState.loading
                      ? t("llm.actions.testingConnection")
                      : current === PERSONA_STEP && personaConfirming
                        ? t("actions.activatingPersona")
                        : saving
                          ? finishingRuntime
                            ? t("actions.startingRuntime")
                            : t("actions.saving")
                          : nextLabel}
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              </div>
            )
          }
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
                initial={shouldReduceMotion ? false : { opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={shouldReduceMotion ? undefined : { opacity: 0, x: -12 }}
                transition={{
                  duration: shouldReduceMotion ? 0 : 0.26,
                  ease: [0.22, 1, 0.36, 1],
                }}
              >
                {current === LLM_SETUP_STEP ? (
                  <header className="mb-4 shrink-0 px-1 sm:mb-5">
                    <h1 className="font-onboarding-display text-[1.9rem] font-bold leading-snug text-foreground">
                      {steps[current]}
                    </h1>
                  </header>
                ) : null}
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
