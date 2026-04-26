import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { normalizeHistoryMessages, type ChatTimelineMessage } from '@/domain/chat/state';
import { useConversationStore } from '@/stores';

const USER_ID = DEFAULT_USER_ID;
const BOOTSTRAP_PENDING_TURN_ID = 'bootstrap-init-pending';
const BOOTSTRAP_PENDING_MESSAGE_ID = 'bootstrap-init-pending';

type UseChatSessionLifecycleOptions = {
  currentSessionId: string | null;
  setCurrentSessionId: (sessionId: string | null) => void;
  resetConversation: () => void;
  resetTraceDrawer: () => void;
  upsertMessage: (sessionId: string, message: ChatTimelineMessage) => void;
  removeMessage: (sessionId: string, messageId: string) => void;
  translate: (key: string, options?: Record<string, unknown>) => string;
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
  const [coreModelSupportsVision, setCoreModelSupportsVision] = useState(false);
  const [allowInterjection, setAllowInterjection] = useState(true);
  const bootstrappedSessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadCoreModelCapabilities = async () => {
      try {
        const response = await configApi.get();
        if (!cancelled) {
          setCoreModelSupportsVision(Boolean(response.data?.llm?.selections?.core?.capabilities?.vision));
          const prefs = response.data?.preferences;
          if (prefs) {
            setAllowInterjection(prefs.allow_interjection !== false);
          }
        }
      } catch {
        if (!cancelled) {
          setCoreModelSupportsVision(false);
        }
      }
    };

    void loadCoreModelCapabilities();
    return () => {
      cancelled = true;
    };
  }, []);

  const requestHistory = useCallback(async (sessionId: string) => {
    if (!sessionId) {
      return;
    }

    try {
      const history = await messagesApi.getHistory(USER_ID, sessionId);
      const rawMessages = Array.isArray(history.messages) ? history.messages : [];
      useConversationStore.getState().receiveHistory(sessionId, normalizeHistoryMessages(rawMessages));
    } catch {
      toast.error(translate('chat.loadHistoryFailed'));
    }
  }, [translate]);

  const loadPersonality = useCallback(async () => {
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

      const shouldInitBootstrap = Boolean(data.needs_bootstrap_init ?? data.needs_bootstrap);
      if (!shouldInitBootstrap || !currentSessionId || bootstrappedSessionIdRef.current === currentSessionId) {
        return;
      }

      bootstrappedSessionIdRef.current = currentSessionId;
      const bootstrapPendingMessage: ChatTimelineMessage = {
        id: BOOTSTRAP_PENDING_MESSAGE_ID,
        messageId: BOOTSTRAP_PENDING_MESSAGE_ID,
        role: 'assistant',
        kind: 'status',
        content: translate('chat.bootstrapInit.preparing'),
        timestamp: Date.now(),
        turnId: BOOTSTRAP_PENDING_TURN_ID,
        traceAvailable: false,
      };
      upsertMessage(currentSessionId, bootstrapPendingMessage);

      try {
        await personasApi.bootstrapInit(currentSessionId, USER_ID);
        void requestHistory(currentSessionId);
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
  }, [currentSessionId, removeMessage, requestHistory, translate, upsertMessage]);

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
  }, [currentSessionId]);

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
    coreModelSupportsVision,
    allowInterjection,
  };
}