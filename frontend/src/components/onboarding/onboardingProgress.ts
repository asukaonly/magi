import { useCallback, useReducer, useRef } from "react";
import type { SystemConfig } from "../../api/modules/config";
import {
  FIRST_CONTEXT_QUESTION_IDS,
  isFirstContextQuestionId,
  isFirstContextRoute,
  type FirstContextQuestionId,
  type FirstContextRoute,
} from "./FirstContextStep";
import type {
  CustomPersonaDraft,
  PersonaCreationDraft,
} from "./persona-preview/personaPreviewModel";
import {
  ONBOARDING_PROGRESS_VERSION,
  sanitizeOnboardingProgressStorage,
  stripOnboardingCredentialFields,
} from "./onboardingStorage";

export { ONBOARDING_PROGRESS_VERSION } from "./onboardingStorage";
const LLM_SETUP_STEP = 1;
const COMPLETE_STEP = 4;

export interface FirstContextProgress {
  route: FirstContextRoute;
  questionId: FirstContextQuestionId;
  seenQuestionIds: FirstContextQuestionId[];
  draft: string;
  sessionCreationKey: string | null;
  sessionId: string | null;
  turnId: string | null;
  messageId: string | null;
  historyImportJobId: string | null;
  historyPreparedCount: number;
  submitted: boolean;
  sendUncertain: boolean;
}

export const DEFAULT_FIRST_CONTEXT_PROGRESS: FirstContextProgress = {
  route: "choose",
  questionId: FIRST_CONTEXT_QUESTION_IDS[0],
  seenQuestionIds: [FIRST_CONTEXT_QUESTION_IDS[0]],
  draft: "",
  sessionCreationKey: null,
  sessionId: null,
  turnId: null,
  messageId: null,
  historyImportJobId: null,
  historyPreparedCount: 0,
  submitted: false,
  sendUncertain: false,
};

export interface OnboardingProgressState {
  version: typeof ONBOARDING_PROGRESS_VERSION;
  current: number;
  values: SystemConfig;
  seedSlug: string | null;
  customPersonas: CustomPersonaDraft[];
  personaCreationDraft: PersonaCreationDraft | null;
  firstContextPluginIds: string[];
  firstContextCountsByPluginId: Record<string, number | null>;
  firstContextProgress: FirstContextProgress;
}

export interface SaveOnboardingProgress {
  values: SystemConfig;
  current?: number;
  seedSlug?: string | null;
  customPersonas?: CustomPersonaDraft[];
  personaCreationDraft?: PersonaCreationDraft | null;
  firstContextPluginIds?: string[];
  firstContextCountsByPluginId?: Record<string, number | null>;
  firstContextProgress?: FirstContextProgress;
}

type OnboardingProgressAction = {
  type: "save";
  progress: SaveOnboardingProgress;
};

interface PersistedOnboardingValues {
  preferences: {
    language: string;
  };
}

interface PersistedOnboardingProgressState
  extends Omit<OnboardingProgressState, "values"> {
  values: PersistedOnboardingValues;
}

/**
 * Keep browser-owned onboarding state limited to non-sensitive UI progress.
 * The backend owns the complete LLM draft, including every credential.
 */
export function serializeOnboardingProgress(
  state: OnboardingProgressState,
): string {
  const snapshot: PersistedOnboardingProgressState = {
    version: state.version,
    current: state.current,
    values: {
      preferences: {
        language: state.values.preferences?.language || "zh",
      },
    },
    seedSlug: state.seedSlug,
    customPersonas: stripOnboardingCredentialFields(
      state.customPersonas,
    ) as CustomPersonaDraft[],
    personaCreationDraft: stripOnboardingCredentialFields(
      state.personaCreationDraft,
    ) as PersonaCreationDraft | null,
    firstContextPluginIds: state.firstContextPluginIds,
    firstContextCountsByPluginId: stripOnboardingCredentialFields(
      state.firstContextCountsByPluginId,
    ) as Record<string, number | null>,
    firstContextProgress: stripOnboardingCredentialFields(
      state.firstContextProgress,
    ) as FirstContextProgress,
  };
  return JSON.stringify(snapshot);
}

function normalizeFirstContextProgress(
  raw: unknown,
): FirstContextProgress {
  if (!raw || typeof raw !== "object") {
    return DEFAULT_FIRST_CONTEXT_PROGRESS;
  }
  const candidate = raw as Partial<FirstContextProgress>;
  const sessionCreationKey =
    typeof candidate.sessionCreationKey === "string" &&
    candidate.sessionCreationKey.trim()
      ? candidate.sessionCreationKey.trim()
      : null;
  const sessionId =
    sessionCreationKey &&
    typeof candidate.sessionId === "string" &&
    candidate.sessionId.trim()
      ? candidate.sessionId.trim()
      : null;
  const turnId =
    typeof candidate.turnId === "string" && candidate.turnId.trim()
      ? candidate.turnId.trim()
      : null;
  const messageId =
    typeof candidate.messageId === "string" && candidate.messageId.trim()
      ? candidate.messageId.trim()
      : null;
  const submitted = Boolean(candidate.submitted && sessionId && turnId);
  const historyImportJobId =
    typeof candidate.historyImportJobId === "string" &&
    candidate.historyImportJobId.trim()
      ? candidate.historyImportJobId.trim()
      : null;
  const questionId = isFirstContextQuestionId(candidate.questionId)
    ? candidate.questionId
    : DEFAULT_FIRST_CONTEXT_PROGRESS.questionId;
  const seenQuestionIds = Array.isArray(candidate.seenQuestionIds)
    ? candidate.seenQuestionIds.filter(isFirstContextQuestionId)
    : [];

  return {
    route: isFirstContextRoute(candidate.route)
      ? candidate.route
      : DEFAULT_FIRST_CONTEXT_PROGRESS.route,
    questionId,
    seenQuestionIds: seenQuestionIds.includes(questionId)
      ? seenQuestionIds
      : [...seenQuestionIds, questionId],
    draft: typeof candidate.draft === "string" ? candidate.draft : "",
    sessionCreationKey,
    sessionId,
    turnId,
    messageId,
    historyImportJobId,
    historyPreparedCount:
      historyImportJobId &&
      typeof candidate.historyPreparedCount === "number" &&
      Number.isFinite(candidate.historyPreparedCount)
        ? Math.max(0, Math.floor(candidate.historyPreparedCount))
        : 0,
    submitted,
    sendUncertain: Boolean(
      candidate.sendUncertain && sessionId && turnId && !submitted,
    ),
  };
}

function normalizeCounts(
  raw: unknown,
): Record<string, number | null> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  const counts: Record<string, number | null> = {};
  for (const [pluginId, count] of Object.entries(raw)) {
    if (typeof count === "number" || count === null) {
      counts[pluginId] = count;
    }
  }
  return counts;
}

function createInitialProgress(
  initialConfig: SystemConfig,
): OnboardingProgressState {
  return {
    version: ONBOARDING_PROGRESS_VERSION,
    current: 0,
    values: initialConfig,
    seedSlug: null,
    customPersonas: [],
    personaCreationDraft: null,
    firstContextPluginIds: [],
    firstContextCountsByPluginId: {},
    firstContextProgress: DEFAULT_FIRST_CONTEXT_PROGRESS,
  };
}

export function restoreOnboardingProgress(
  serialized: string | null,
  initialConfig: SystemConfig,
  savedLanguage: string | null,
): OnboardingProgressState {
  const fallback = createInitialProgress(initialConfig);
  if (!serialized) return fallback;

  try {
    const parsed = JSON.parse(serialized) as Partial<OnboardingProgressState>;
    if (
      parsed.version !== ONBOARDING_PROGRESS_VERSION ||
      !parsed.values ||
      typeof parsed.values !== "object"
    ) {
      return fallback;
    }
    const recoveredStep =
      typeof parsed.current === "number"
        ? Math.max(0, Math.min(COMPLETE_STEP, parsed.current))
        : 0;
    const persistedPreferences = (
      parsed.values as Partial<SystemConfig>
    ).preferences;
    const values: SystemConfig = {
      ...initialConfig,
      preferences: {
        ...initialConfig.preferences,
        language:
          (savedLanguage === "en" || savedLanguage === "zh"
            ? savedLanguage
            : undefined) ||
          persistedPreferences?.language ||
          initialConfig.preferences.language,
      },
    };
    return {
      version: ONBOARDING_PROGRESS_VERSION,
      current:
        recoveredStep > LLM_SETUP_STEP ? LLM_SETUP_STEP : recoveredStep,
      values,
      seedSlug:
        typeof parsed.seedSlug === "string" ? parsed.seedSlug : null,
      customPersonas: Array.isArray(parsed.customPersonas)
        ? parsed.customPersonas
        : [],
      personaCreationDraft:
        parsed.personaCreationDraft &&
        typeof parsed.personaCreationDraft === "object"
          ? parsed.personaCreationDraft
          : null,
      firstContextPluginIds: Array.isArray(parsed.firstContextPluginIds)
        ? parsed.firstContextPluginIds.filter(
            (pluginId): pluginId is string =>
              typeof pluginId === "string",
          )
        : [],
      firstContextCountsByPluginId: normalizeCounts(
        parsed.firstContextCountsByPluginId,
      ),
      firstContextProgress: normalizeFirstContextProgress(
        parsed.firstContextProgress,
      ),
    };
  } catch {
    return fallback;
  }
}

export function onboardingProgressReducer(
  state: OnboardingProgressState,
  action: OnboardingProgressAction,
): OnboardingProgressState {
  return {
    ...state,
    ...action.progress,
    version: ONBOARDING_PROGRESS_VERSION,
  };
}

interface UseOnboardingProgressOptions {
  storageKey: string;
  initialConfig: SystemConfig;
}

export function useOnboardingProgress({
  storageKey,
  initialConfig,
}: UseOnboardingProgressOptions) {
  const [state, dispatch] = useReducer(
    onboardingProgressReducer,
    initialConfig,
    (config) => {
      const sanitized = sanitizeOnboardingProgressStorage(storageKey);
      const restored = restoreOnboardingProgress(
        sanitized,
        config,
        localStorage.getItem("magi_language"),
      );
      if (sanitized) {
        localStorage.setItem(storageKey, serializeOnboardingProgress(restored));
      }
      return restored;
    },
  );
  const stateRef = useRef(state);
  stateRef.current = state;

  const save = useCallback(
    (progress: SaveOnboardingProgress): OnboardingProgressState => {
      const action: OnboardingProgressAction = { type: "save", progress };
      const nextState = onboardingProgressReducer(stateRef.current, action);
      stateRef.current = nextState;
      dispatch(action);
      localStorage.setItem(storageKey, serializeOnboardingProgress(nextState));
      return nextState;
    },
    [storageKey],
  );

  const clear = useCallback(() => {
    localStorage.removeItem(storageKey);
  }, [storageKey]);

  return { state, stateRef, save, clear };
}
