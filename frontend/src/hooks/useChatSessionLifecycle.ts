import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';
import { personasApi, type PersonaSummary } from '@/api/modules/personas';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { normalizeHistoryMessages, type ChatTimelineMessage } from '@/domain/chat/state';
import { useProductTourFlag } from '@/hooks/useProductTourFlag';
import { useConversationStore } from '@/stores';

const USER_ID = DEFAULT_USER_ID;
const BOOTSTRAP_PENDING_TURN_ID = 'bootstrap-init-pending';
const BOOTSTRAP_PENDING_MESSAGE_ID = 'bootstrap-init-pending';

/**
 * Pure gate deciding whether the persona's bootstrap opening may fire yet.
 *
 * The opening is deferred until the one-time first-run context prompt is
 * resolved: we hold it while that state is still loading or pending, and only
 * release it once the prompt is loaded AND completed (or skipped). Extracted
 * as a pure helper so the gate is unit-testable independently of the hook.
 */
export function shouldFireBootstrap(args: {
  needsBootstrap: boolean;
  tourLoaded: boolean;
  tourCompleted: boolean;
}): boolean {
  return args.needsBootstrap && args.tourLoaded && args.tourCompleted;
}

type UseChatSessionLifecycleOptions = {
  currentSessionId: string | null;
  setCurrentSessionId: (sessionId: string | null) => void;
  resetConversation: () => void;
  resetTraceDrawer: () => void;
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

export type ChatPersonaIdentity = {
  name: string;
  avatar: string;
};

export function useChatSessionLifecycle({
  currentSessionId,
  setCurrentSessionId,
  resetConversation,
  resetTraceDrawer,
  upsertMessage,
  removeMessage,
  translate,
}: UseChatSessionLifecycleOptions) {
  const [aiName, setAiName] = useState('AI');
  const [aiAvatar, setAiAvatar] = useState('');
  const [assistantPersonas, setAssistantPersonas] = useState<Record<string, ChatPersonaIdentity>>({});
  const [coreModelSupportsVision, setCoreModelSupportsVision] = useState(false);
  const [coreModelContextWindow, setCoreModelContextWindow] = useState<number | null>(null);
  const [allowInterjection, setAllowInterjection] = useState(true);
  const bootstrappedSessionIdRef = useRef<string | null>(null);
  // Defer the persona's bootstrap opening until the one-time first-run context
  // prompt is resolved. When it completes, the flag flips and the firing effect
  // below re-runs (re-fetching the greeting), releasing the held opening.
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
          if (prefs) {
            setAllowInterjection(prefs.allow_interjection !== false);
          }
        }
      } catch {
        if (!cancelled) {
          setCoreModelSupportsVision(false);
          setCoreModelContextWindow(null);
        }
      }
    };

    void loadCoreModelConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const requestHistory = useCallback(async (sessionId: string, options: { force?: boolean } = {}) => {
    if (!sessionId) {
      return;
    }

    if (!options.force && hasFreshCachedHistory(sessionId)) {
      return;
    }

    try {
      const history = await messagesApi.getHistory(USER_ID, sessionId);
      const rawMessages = Array.isArray(history.messages) ? history.messages : [];
      const responseVersion = normalizeHistoryVersion(history.history_version);
      const fallbackVersion = normalizeHistoryVersion(
        useConversationStore.getState().sessionsById[sessionId]?.history_version,
      );
      useConversationStore.getState().receiveHistory(
        sessionId,
        normalizeHistoryMessages(rawMessages),
        responseVersion ?? fallbackVersion,
      );
    } catch {
      toast.error(translate('chat.loadHistoryFailed'));
    }
  }, [translate]);

  const loadPersonality = useCallback(async () => {
    try {
      const personasResponse = await personasApi.list({ includeDeleted: true });
      const personaItems = Array.isArray(personasResponse.data)
        ? personasResponse.data as PersonaSummary[]
        : [];
      setAssistantPersonas(Object.fromEntries(personaItems.map((item) => [
        item.persona_id,
        {
          name: item.name || 'AI',
          avatar: personasApi.getAvatarUrl(item.avatar_path || ''),
        },
      ])));
    } catch {
      setAssistantPersonas({});
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

      if (!data) {
        return;
      }

      setAiName(data.name || 'AI');
      setAiAvatar(data.avatar || '');

      const needsBootstrap = Boolean(data.needs_bootstrap_init ?? data.needs_bootstrap);
      if (
        !shouldFireBootstrap({ needsBootstrap, tourLoaded, tourCompleted })
        || !currentSessionId
        || bootstrappedSessionIdRef.current === currentSessionId
      ) {
        return;
      }

      bootstrappedSessionIdRef.current = currentSessionId;
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
      upsertMessage(currentSessionId, bootstrapPendingMessage);

      try {
        await personasApi.bootstrapInit(currentSessionId, USER_ID);
        void requestHistory(currentSessionId, { force: true });
      } catch {
        if (bootstrappedSessionIdRef.current === currentSessionId) {
          bootstrappedSessionIdRef.current = null;
        }
      } finally {
        removeMessage(currentSessionId, BOOTSTRAP_PENDING_MESSAGE_ID);
      }
    } catch {
      // Non-critical — keep default AI name.
    }
  }, [currentSessionId, removeMessage, requestHistory, translate, tourCompleted, tourLoaded, upsertMessage]);

  const requestHistoryRef = useRef(requestHistory);
  const loadPersonalityRef = useRef(loadPersonality);

  useEffect(() => {
    requestHistoryRef.current = requestHistory;
  }, [requestHistory]);

  useEffect(() => {
    loadPersonalityRef.current = loadPersonality;
  }, [loadPersonality]);

  useEffect(() => {
    if (!currentSessionId) {
      return;
    }

    void requestHistoryRef.current(currentSessionId);
    void loadPersonalityRef.current();
    // tourCompleted/tourLoaded are deps so this same effect also re-evaluates the
    // *deferred* bootstrap opening once the first-run context prompt resolves:
    // loadPersonality re-fetches the greeting and shouldFireBootstrap then releases
    // the held opening. Folding it into this effect (rather than a second one)
    // avoids a redundant loadPersonality/getGreeting call on every session switch.
  }, [currentSessionId, tourCompleted, tourLoaded]);

  useEffect(() => {
    const handleMemoryCleared = () => {
      bootstrappedSessionIdRef.current = null;
      setCurrentSessionId(null);
      resetTraceDrawer();
      resetConversation();
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    };

    window.addEventListener(APP_EVENTS.MEMORY_CLEARED, handleMemoryCleared);
    return () => window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, handleMemoryCleared);
  }, [resetConversation, resetTraceDrawer, setCurrentSessionId]);

  return {
    aiName,
    aiAvatar,
    assistantPersonas,
    coreModelSupportsVision,
    coreModelContextWindow,
    allowInterjection,
  };
}
