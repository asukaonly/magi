import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useRequestOwner } from '@/hooks/useRequestOwner';
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
import { cachedChatHistory, refreshChatHistory, pageCanLoadMore } from '@/runtime/chat-read-cache';

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

type PersonaSnapshotPurpose = 'display-refresh' | 'bootstrap-evaluation';

const normalizeHistoryVersion = (value: unknown): number | null => {
  if (typeof value !== 'number') return null;
  const version = Number(value);
  if (!Number.isFinite(version) || version < 0) {
    return null;
  }
  return Math.trunc(version);
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
  const [historyReadStates, setHistoryReadStates] = useState<Record<string, { checkedAt: number; stale: boolean; hasMore: boolean }>>({});
  const [loadingOlderSessions, setLoadingOlderSessions] = useState<Set<string>>(new Set());
  const loadingOlderRef = useRef(new Set<string>());
  const initialHistoryRequestsRef = useRef(
    new Map<string, Promise<HistoryBootstrapState>>(),
  );
  const bootstrappedSessionIdRef = useRef<string | null>(null);
  // Defer the persona's bootstrap opening until the one-time first-run context
  // prompt is resolved. When it completes, the flag flips and the firing effect
  // below re-runs, but session history is still checked first.
  const { completed: tourCompleted, loaded: tourLoaded } = useProductTourFlag();

  const beginRead = useRequestOwner('chat-lifecycle');
  const loadCoreModelConfig = useCallback(async () => {
    const isCurrent = beginRead('model-config');
    try {
      const response = await configApi.get();
      if (isCurrent()) {
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
      // Keep the last confirmed model policy when a background read fails.
      if (isCurrent()) setInterjectionSettingLoaded(true);
    }
  }, [beginRead]);
  useEffect(() => { void loadCoreModelConfig(); }, [loadCoreModelConfig]);

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

    const cached = cachedChatHistory(sessionId);
    if (!options.force && cached && options.commit !== false) {
      const messages = normalizeHistoryMessages(cached.data.messages);
      const state = useConversationStore.getState();
      if (!Object.prototype.hasOwnProperty.call(state.messagesBySession, sessionId)) {
        state.receiveHistory(sessionId, messages, cached.data.history_version);
      }
      setHistoryReadStates((current) => ({ ...current, [sessionId]: {
        checkedAt: cached.checkedAt, stale: cached.stale, hasMore: pageCanLoadMore(cached.data),
      } }));
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
        const snapshot = await refreshChatHistory(sessionId);
        const history = snapshot.data;
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
        const cachedVersion = normalizeHistoryVersion(useConversationStore.getState().historyVersionBySession[sessionId]);
        if ((responseVersion === null && (fallbackVersion !== null || cachedVersion !== null))
          || (responseVersion !== null && Math.max(fallbackVersion ?? 0, cachedVersion ?? 0) > responseVersion)) {
          if (attempt + 1 < maxAttempts) continue;
          return { loaded: false, hasUserMessage: false, messages: [], historyVersion: null };
        }
        const historyVersion = responseVersion ?? fallbackVersion;
        if (options.commit !== false) {
          setHistoryReadStates((current) => ({ ...current, [sessionId]: {
            checkedAt: snapshot.checkedAt, stale: false, hasMore: pageCanLoadMore(history),
          } }));
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
        setHistoryReadStates((current) => current[sessionId]
          ? { ...current, [sessionId]: { ...current[sessionId], stale: true } } : current);
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
    const owner = captureChatHistoryGuard(sessionId);
    try {
      const history = await messagesApi.getHistory(USER_ID, sessionId, { turn_id: turnId });
      if (!isChatHistoryGuardCurrent(owner)) return { resolved: false };
      const resolution = resolvePendingTurnFromHistory(normalizeHistoryMessages(history.messages), turnId);
      if (resolution.safeToCommitHistory) {
        const refreshed = await requestHistory(sessionId, { force: true, maxAttempts: 1, showError: false });
        if (!refreshed.loaded) return { resolved: false };
      }
      return resolution;
    } catch { return { resolved: false }; }
  }, [requestHistory]);

  const loadOlderHistory = useCallback(async (): Promise<void> => {
    if (!currentSessionId || loadingOlderRef.current.has(currentSessionId)) return;
    const sessionId = currentSessionId;
    const owner = captureChatHistoryGuard(sessionId);
    loadingOlderRef.current.add(sessionId);
    setLoadingOlderSessions(new Set(loadingOlderRef.current));
    const messagesAtStart = useConversationStore.getState().messagesBySession[sessionId] || [];
    try {
      const snapshot = await refreshChatHistory(sessionId, true);
      if (!isChatHistoryGuardCurrent(owner)) return;
      const state = useConversationStore.getState();
      const currentVersion = Math.max(state.historyVersionBySession[sessionId] ?? 0, state.sessionsById[sessionId]?.history_version ?? 0);
      if ((snapshot.data.history_version ?? 0) < currentVersion) {
        await requestHistory(sessionId, { force: true });
        return;
      }
      const concurrentMessages = (state.messagesBySession[sessionId] || []).filter((message) => !messagesAtStart.includes(message));
      const messages = concurrentMessages.reduce((items, message) => upsertTimelineMessage(items, message), normalizeHistoryMessages(snapshot.data.messages));
      state.receiveHistory(sessionId, messages, snapshot.data.history_version);
      setHistoryReadStates((current) => ({ ...current, [sessionId]: {
        checkedAt: snapshot.checkedAt, stale: false, hasMore: pageCanLoadMore(snapshot.data),
      } }));
    } catch {
      if (isChatHistoryGuardCurrent(owner)) toast.error(translate('chat.loadHistoryFailed'));
    } finally {
      loadingOlderRef.current.delete(sessionId);
      setLoadingOlderSessions(new Set(loadingOlderRef.current));
    }
  }, [currentSessionId, requestHistory, translate]);

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

  const loadPersonaSnapshot = useCallback(async (
    purpose: PersonaSnapshotPurpose,
  ) => {
    const isCurrent = beginRead(`persona-${purpose}`);
    const isCancelled = () => !isCurrent();
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
      // Retain the last confirmed persona registry on transient read errors.
    }

    try {
      const response = await personasApi.getGreeting();
      const data = response.data;
      if (!data || isCancelled()) return undefined;
      setAiName(data.name || 'AI');
      setAiAvatar(data.avatar || '');
      return data;
    } catch { return undefined; }
  }, [beginRead]);

  useCenterRefresh(loadCoreModelConfig, ['config']);
  useCenterRefresh(() => loadPersonaSnapshot('display-refresh'), ['personality', 'personas']);
  useCenterRefresh(() => currentSessionId
    ? requestHistory(currentSessionId, { force: true, maxAttempts: 1, showError: false })
    : Promise.resolve(), ['messages', 'chat', 'sessions']);

  const loadPersonality = useCallback(async (
    sessionId: string,
    historyStatePromise: Promise<HistoryBootstrapState>,
    isCancelled: () => boolean,
  ) => {
    try {
      const data = await loadPersonaSnapshot('bootstrap-evaluation');
      if (!data || isCancelled()) return;

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
  }, [loadPersonaSnapshot, removeMessage, requestHistory, translate, tourCompleted, tourLoaded, upsertMessage]);

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
      setHistoryReadStates({});
      bootstrappedSessionIdRef.current = null;
      initialHistoryRequestsRef.current.clear();
      return;
    }
    initialHistoryRequestsRef.current.delete(normalizedSessionId);
    setHistoryReadStates((current) => {
      const next = { ...current };
      delete next[normalizedSessionId];
      return next;
    });
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
    historyReadState: currentSessionId ? historyReadStates[currentSessionId] : undefined,
    loadingOlderHistory: Boolean(currentSessionId && loadingOlderSessions.has(currentSessionId)),
    loadOlderHistory,
  };
}
