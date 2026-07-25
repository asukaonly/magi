import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';
import { personasApi, type PersonaSummary } from '@/api/modules/personas';
import { DEFAULT_USER_ID } from '@/constants';
import { normalizeHistoryMessages, type ChatTimelineMessage } from '@/domain/chat/state';
import {
  resolvePendingTurnFromHistory,
  type PendingTurnHistoryResolution,
} from '@/domain/chat/turn-completion';
import { useProductTourFlag } from '@/hooks/useProductTourFlag';
import {
  captureChatHistoryGuard,
  isChatHistoryGuardCurrent,
} from './chatRetryInvalidation';
import { useConversationStore } from '@/stores';
import { useContextUsageStore } from '@/stores/context-usage';
import { upsertTimelineMessage } from '@/stores/conversation-timeline';

const USER_ID = DEFAULT_USER_ID;
const BOOTSTRAP_PENDING_TURN_ID = 'bootstrap-init-pending';
const BOOTSTRAP_PENDING_MESSAGE_ID = 'bootstrap-init-pending';
const HISTORY_LOAD_MAX_ATTEMPTS = 2;
const HISTORY_LOAD_RETRY_DELAY_MS = 200;
const HISTORY_BACKGROUND_RETRY_DELAYS_MS = [800, 2_000, 5_000] as const;

/**
 * Pure gate deciding whether the persona's bootstrap opening may fire yet.
 *
 * The opening is deferred until both the one-time first-run context prompt and
 * the current session history are resolved. A persisted user message always
 * wins over the synthetic opening. Extracted as a pure helper so the gate is
 * unit-testable independently of the hook.
 */
export function shouldFireBootstrap(args: {
  needsBootstrap: boolean;
  tourLoaded: boolean;
  tourCompleted: boolean;
  historyLoaded: boolean;
  hasUserMessage: boolean;
}): boolean {
  return (
    args.needsBootstrap
    && args.tourLoaded
    && args.tourCompleted
    && args.historyLoaded
    && !args.hasUserMessage
  );
}

export type HistoryBootstrapState = {
  loaded: boolean;
  hasUserMessage: boolean;
  messages: ChatTimelineMessage[];
  historyVersion: number | null;
};

type HistoryRequestOptions = {
  force?: boolean;
  maxAttempts?: number;
  showError?: boolean;
  commit?: boolean;
};

type UseChatSessionLifecycleOptions = {
  currentSessionId: string | null;
  upsertMessage: (sessionId: string, message: ChatTimelineMessage) => void;
  removeMessage: (sessionId: string, messageId: string) => void;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

const normalizeHistoryVersion = (value: unknown): number | null => {
  const version = Number(value);
  if (!Number.isFinite(version) || version < 0) {
    return null;
  }
  return Math.trunc(version);
};

const hasFreshCachedHistory = (sessionId: string): boolean => {
  const state = useConversationStore.getState();
  if (!Object.prototype.hasOwnProperty.call(state.messagesBySession, sessionId)) {
    return false;
  }
  const serverVersion = normalizeHistoryVersion(state.sessionsById[sessionId]?.history_version);
  const cachedVersion = normalizeHistoryVersion(state.historyVersionBySession[sessionId]);
  return serverVersion !== null && cachedVersion === serverVersion;
};

const sessionHasUserMessage = (sessionId: string): boolean => (
  (useConversationStore.getState().messagesBySession[sessionId] || [])
    .some((message) => message.role === 'user')
);

export type ChatPersonaIdentity = {
  name: string;
  avatar: string;
};

export function useChatSessionLifecycle({
  currentSessionId,
  upsertMessage,
  removeMessage,
  translate,
}: UseChatSessionLifecycleOptions) {
  const [aiName, setAiName] = useState('AI');
  const [aiAvatar, setAiAvatar] = useState('');
  const [assistantPersonas, setAssistantPersonas] = useState<Record<string, ChatPersonaIdentity>>({});
  const [coreModelSupportsVision, setCoreModelSupportsVision] = useState(false);
  const [coreModelContextWindow, setCoreModelContextWindow] = useState<number | null>(null);
  const [allowInterjection, setAllowInterjection] = useState(false);
  const [interjectionSettingLoaded, setInterjectionSettingLoaded] = useState(false);
  const initialHistoryRequestsRef = useRef(
    new Map<string, Promise<HistoryBootstrapState>>(),
  );
  const bootstrappedSessionIdRef = useRef<string | null>(null);
  // Defer the persona's bootstrap opening until the one-time first-run context
  // prompt is resolved. When it completes, the flag flips and the firing effect
  // below re-runs, but session history is still checked first.
  const { completed: tourCompleted, loaded: tourLoaded } = useProductTourFlag();

  useEffect(() => {
    let cancelled = false;

    const loadCoreModelConfig = async () => {
      try {
        const response = await configApi.get();
        if (!cancelled) {
          const coreSelection = response.data?.llm?.selections?.core;
          const contextWindow = coreSelection?.limits?.context_window;
          setCoreModelSupportsVision(Boolean(coreSelection?.capabilities?.vision));
          setCoreModelContextWindow(
            typeof contextWindow === 'number' && Number.isFinite(contextWindow) && contextWindow > 0
              ? contextWindow
              : null,
          );
          const prefs = response.data?.preferences;
          setAllowInterjection(prefs?.allow_interjection === true);
          setInterjectionSettingLoaded(true);
        }
      } catch {
        if (!cancelled) {
          setCoreModelSupportsVision(false);
          setCoreModelContextWindow(null);
          setAllowInterjection(false);
          setInterjectionSettingLoaded(true);
        }
      }
    };

    void loadCoreModelConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const requestHistory = useCallback(async (
    sessionId: string,
    options: HistoryRequestOptions = {},
  ): Promise<HistoryBootstrapState> => {
    if (!sessionId) {
      return {
        loaded: false,
        hasUserMessage: false,
        messages: [],
        historyVersion: null,
      };
    }
    const historyGuard = captureChatHistoryGuard(sessionId);

    if (!options.force && hasFreshCachedHistory(sessionId)) {
      const messages = useConversationStore.getState().messagesBySession[sessionId] || [];
      return {
        loaded: true,
        hasUserMessage: messages.some((message) => message.role === 'user'),
        messages,
        historyVersion: normalizeHistoryVersion(
          useConversationStore.getState().historyVersionBySession[sessionId],
        ),
      };
    }

    const maxAttempts = Math.max(
      1,
      Math.floor(options.maxAttempts ?? HISTORY_LOAD_MAX_ATTEMPTS),
    );
    const messagesAtRequestStart = (
      useConversationStore.getState().messagesBySession[sessionId] || []
    );
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const history = await messagesApi.getHistory(USER_ID, sessionId);
        if (!isChatHistoryGuardCurrent(historyGuard)) {
          return {
            loaded: false,
            hasUserMessage: false,
            messages: [],
            historyVersion: null,
          };
        }
        const rawMessages = Array.isArray(history.messages) ? history.messages : [];
        const normalizedMessages = normalizeHistoryMessages(rawMessages);
        const messagesAfterRequest = (
          useConversationStore.getState().messagesBySession[sessionId] || []
        );
        const concurrentMessages = messagesAfterRequest.filter(
          (message) => !messagesAtRequestStart.includes(message),
        );
        const messagesToCommit = options.commit === false
          ? normalizedMessages
          : concurrentMessages.reduce(
            (messages, message) => upsertTimelineMessage(messages, message),
            normalizedMessages,
          );
        const responseVersion = normalizeHistoryVersion(history.history_version);
        const fallbackVersion = normalizeHistoryVersion(
          useConversationStore.getState().sessionsById[sessionId]?.history_version,
        );
        const historyVersion = responseVersion ?? fallbackVersion;
        if (options.commit !== false) {
          useConversationStore.getState().receiveHistory(
            sessionId,
            messagesToCommit,
            historyVersion,
          );
          if (history.context_usage) {
            useContextUsageStore.getState().update(
              sessionId,
              history.context_usage,
            );
          } else {
            useContextUsageStore.getState().clear(sessionId);
          }
        }
        return {
          loaded: true,
          hasUserMessage: messagesToCommit.some((message) => message.role === 'user'),
          messages: messagesToCommit,
          historyVersion,
        };
      } catch {
        if (!isChatHistoryGuardCurrent(historyGuard)) {
          return {
            loaded: false,
            hasUserMessage: false,
            messages: [],
            historyVersion: null,
          };
        }
        if (attempt + 1 < maxAttempts) {
          await new Promise<void>((resolve) => {
            window.setTimeout(resolve, HISTORY_LOAD_RETRY_DELAY_MS);
          });
          if (!isChatHistoryGuardCurrent(historyGuard)) {
            return {
              loaded: false,
              hasUserMessage: false,
              messages: [],
              historyVersion: null,
            };
          }
        }
      }
    }
    if (options.showError !== false) {
      toast.error(translate('chat.loadHistoryFailed'));
    }
    return {
      loaded: false,
      hasUserMessage: false,
      messages: [],
      historyVersion: null,
    };
  }, [translate]);

  const reconcileTurnFromHistory = useCallback(async (
    sessionId: string,
    turnId: string,
  ): Promise<PendingTurnHistoryResolution> => {
    const historyState = await requestHistory(sessionId, {
      force: true,
      maxAttempts: HISTORY_LOAD_MAX_ATTEMPTS,
      showError: false,
      commit: false,
    });
    if (!historyState.loaded) {
      return { resolved: false };
    }
    const resolution = resolvePendingTurnFromHistory(
      historyState.messages,
      turnId,
    );
    if (resolution.safeToCommitHistory) {
      useConversationStore.getState().receiveHistory(
        sessionId,
        historyState.messages,
        historyState.historyVersion,
      );
    }
    return resolution;
  }, [requestHistory]);

  const ensureSessionHistoryReady = useCallback((
    sessionId: string,
  ): Promise<HistoryBootstrapState> => {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      return Promise.resolve({
        loaded: false,
        hasUserMessage: false,
        messages: [],
        historyVersion: null,
      });
    }
    const existing = initialHistoryRequestsRef.current.get(
      normalizedSessionId,
    );
    if (existing) {
      return existing;
    }
    const request = requestHistory(normalizedSessionId).finally(() => {
      if (
        initialHistoryRequestsRef.current.get(normalizedSessionId)
          === request
      ) {
        initialHistoryRequestsRef.current.delete(normalizedSessionId);
      }
    });
    initialHistoryRequestsRef.current.set(normalizedSessionId, request);
    return request;
  }, [requestHistory]);

  const loadPersonality = useCallback(async (
    sessionId: string,
    historyStatePromise: Promise<HistoryBootstrapState>,
    isCancelled: () => boolean,
  ) => {
    try {
      const personasResponse = await personasApi.list({ includeDeleted: true });
      const personaItems = Array.isArray(personasResponse.data)
        ? personasResponse.data as PersonaSummary[]
        : [];
      if (!isCancelled()) {
        setAssistantPersonas(Object.fromEntries(personaItems.map((item) => [
          item.persona_id,
          {
            name: item.name || 'AI',
            avatar: personasApi.getAvatarUrl(item.avatar_path || ''),
          },
        ])));
      }
    } catch {
      if (!isCancelled()) {
        setAssistantPersonas({});
      }
    }

    try {
      const response = await personasApi.getGreeting();
      const data = response.data as {
        greeting?: string;
        name?: string;
        avatar?: string;
        needs_bootstrap?: boolean;
        needs_bootstrap_init?: boolean;
      } | undefined;

      if (!data || isCancelled()) {
        return;
      }

      setAiName(data.name || 'AI');
      setAiAvatar(data.avatar || '');

      const needsBootstrap = Boolean(data.needs_bootstrap_init ?? data.needs_bootstrap);
      if (
        !needsBootstrap
        || !tourLoaded
        || !tourCompleted
        || !sessionId
        || bootstrappedSessionIdRef.current === sessionId
      ) {
        return;
      }

      const historyState = await historyStatePromise;
      if (isCancelled()) {
        return;
      }
      const hasUserMessage = historyState.hasUserMessage || sessionHasUserMessage(sessionId);
      if (
        !shouldFireBootstrap({
          needsBootstrap,
          tourLoaded,
          tourCompleted,
          historyLoaded: historyState.loaded,
          hasUserMessage,
        })
        || bootstrappedSessionIdRef.current === sessionId
      ) {
        return;
      }

      bootstrappedSessionIdRef.current = sessionId;
      const bootstrapPendingMessage: ChatTimelineMessage = {
        id: BOOTSTRAP_PENDING_MESSAGE_ID,
        messageId: BOOTSTRAP_PENDING_MESSAGE_ID,
        role: 'assistant',
        kind: 'status',
        content: translate('chat.bootstrapInit.preparing', {
          name: data.name || translate('chat.personaFallbackName'),
        }),
        timestamp: Date.now(),
        turnId: BOOTSTRAP_PENDING_TURN_ID,
        traceAvailable: false,
      };
      upsertMessage(sessionId, bootstrapPendingMessage);

      try {
        await personasApi.bootstrapInit(sessionId, USER_ID);
        void requestHistory(sessionId, { force: true });
      } catch {
        if (bootstrappedSessionIdRef.current === sessionId) {
          bootstrappedSessionIdRef.current = null;
        }
      } finally {
        removeMessage(sessionId, BOOTSTRAP_PENDING_MESSAGE_ID);
      }
    } catch {
      // Non-critical — keep default AI name.
    }
  }, [removeMessage, requestHistory, translate, tourCompleted, tourLoaded, upsertMessage]);

  const requestHistoryRef = useRef(requestHistory);
  const ensureSessionHistoryReadyRef = useRef(ensureSessionHistoryReady);
  const loadPersonalityRef = useRef(loadPersonality);

  useEffect(() => {
    requestHistoryRef.current = requestHistory;
  }, [requestHistory]);

  useEffect(() => {
    ensureSessionHistoryReadyRef.current = ensureSessionHistoryReady;
  }, [ensureSessionHistoryReady]);

  useEffect(() => {
    loadPersonalityRef.current = loadPersonality;
  }, [loadPersonality]);

  useEffect(() => {
    if (!currentSessionId) {
      return;
    }

    let cancelled = false;
    const historyStatePromise = ensureSessionHistoryReadyRef.current(
      currentSessionId,
    );
    void loadPersonalityRef.current(currentSessionId, historyStatePromise, () => cancelled);
    void (async () => {
      const initialState = await historyStatePromise;
      if (initialState.loaded || cancelled) {
        return;
      }
      for (const delayMs of HISTORY_BACKGROUND_RETRY_DELAYS_MS) {
        await new Promise<void>((resolve) => {
          window.setTimeout(resolve, delayMs);
        });
        if (cancelled) {
          return;
        }
        const recovered = await requestHistoryRef.current(currentSessionId, {
          force: true,
          maxAttempts: 1,
          showError: false,
        });
        if (recovered.loaded) {
          return;
        }
      }
    })();
    // tourCompleted/tourLoaded are deps so this same effect also re-evaluates the
    // deferred bootstrap opening once the first-run context prompt resolves.
    // Every evaluation waits for history first to avoid racing a real user turn.
    return () => {
      cancelled = true;
    };
  }, [currentSessionId, tourCompleted, tourLoaded]);

  const clearSessionLifecycleState = useCallback((sessionId?: string) => {
    const normalizedSessionId = String(sessionId || '').trim();
    if (!normalizedSessionId) {
      bootstrappedSessionIdRef.current = null;
      initialHistoryRequestsRef.current.clear();
      return;
    }
    initialHistoryRequestsRef.current.delete(normalizedSessionId);
    if (bootstrappedSessionIdRef.current === normalizedSessionId) {
      bootstrappedSessionIdRef.current = null;
    }
  }, []);

  return {
    aiName,
    aiAvatar,
    assistantPersonas,
    coreModelSupportsVision,
    coreModelContextWindow,
    allowInterjection,
    interjectionSettingLoaded,
    clearSessionLifecycleState,
    ensureSessionHistoryReady,
    reconcileTurnFromHistory,
  };
}
