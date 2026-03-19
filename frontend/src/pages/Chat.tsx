/**
 * Chat page - desktop-focused conversation workspace
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, Loader2, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { messagesApi } from '@/api';
import { getRuntimeConfig } from '@/runtime/config';
import { useRealtime } from '@/realtime/provider';
import { useChatTraceStore, useConversationStore, useRealtimeStore } from '@/stores';
import ToolchainDrawer from '@/components/chat/ToolchainDrawer';
import { shouldSubmitOnEnter } from './chat-route-helpers';
import {
  normalizeTraceSnapshot,
  normalizeTraceSummary,
  type ChatTimelineMessage,
} from './chat-state';

interface WSMessage {
  type?: string;
  data?: any;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
}

const MEMORY_CLEARED_EVENT = 'magi-memory-cleared';
const SESSION_EVENT = 'magi-session-sync';
const USER_ID = 'web_user';

const assistantMarkdownComponents: Components = {
  h1: ({ children }) => <h1 className="mb-3 mt-1 text-lg font-semibold leading-snug text-foreground">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-3 mt-5 text-base font-semibold leading-snug text-foreground first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-4 text-sm font-semibold leading-snug text-foreground">{children}</h3>,
  p: ({ children }) => <p className="mb-3 whitespace-pre-wrap text-sm leading-7 text-foreground last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 text-sm leading-7 text-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm leading-7 text-foreground">{children}</ol>,
  li: ({ children }) => <li className="pl-1 marker:text-muted-foreground">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="mb-3 border-l-2 border-border/80 pl-3 text-sm italic leading-7 text-muted-foreground">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-3 overflow-x-auto rounded-xl border border-border/60 bg-muted/40 p-3 text-xs leading-6 text-foreground">
      {children}
    </pre>
  ),
  a: ({ href, children }) => (
    <a href={href} className="text-primary underline decoration-primary/50 underline-offset-2" target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
};

const createClientTurnId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `turn_${crypto.randomUUID()}`;
  }
  return `turn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
};

export const ChatPage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const shouldReduceMotion = useReducedMotion();
  const { send, subscribe } = useRealtime();
  const connected = useRealtimeStore((state) => state.connected);
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
  const messages = useConversationStore((state) =>
    state.currentSessionId ? (state.messagesBySession[state.currentSessionId] || []) : []
  );
  const appendPendingTurn = useConversationStore((state) => state.appendPendingTurn);
  const receiveAgentResponse = useConversationStore((state) => state.receiveAgentResponse);
  const applyConversationTraceSummary = useConversationStore((state) => state.upsertTraceSummary);
  const resetConversation = useConversationStore((state) => state.reset);

  const drawerOpen = useChatTraceStore((state) => state.drawerOpen);
  const activeTurnId = useChatTraceStore((state) => state.activeTurnId);
  const summaries = useChatTraceStore((state) => state.summaries);
  const snapshots = useChatTraceStore((state) => state.snapshots);
  const upsertSummary = useChatTraceStore((state) => state.upsertSummary);
  const setSnapshot = useChatTraceStore((state) => state.setSnapshot);
  const openDrawer = useChatTraceStore((state) => state.openDrawer);
  const closeDrawer = useChatTraceStore((state) => state.closeDrawer);
  const resetTraceStore = useChatTraceStore((state) => state.reset);

  const [inputValue, setInputValue] = useState('');
  const [aiName, setAiName] = useState<string>('AI');
  const [aiAvatar, setAiAvatar] = useState<string>('');
  const [loadingTrace, setLoadingTrace] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastHistoryRequestRef = useRef<string | null>(null);
  const isComposingRef = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadTrace = useCallback(
    async (turnId: string) => {
      if (!currentSessionId || !turnId) return;
      setLoadingTrace(true);
      try {
        const result = await messagesApi.getTrace(USER_ID, currentSessionId, turnId);
        const snapshot = normalizeTraceSnapshot(result.trace || undefined);
        if (snapshot) {
          setSnapshot(result.trace!);
        }
      } catch {
        toast.error(t('chat.trace.loadFailed'));
      } finally {
        setLoadingTrace(false);
      }
    },
    [currentSessionId, setSnapshot, t]
  );

  const requestHistory = useCallback(
    (sessionId: string) => {
      if (!sessionId) return;
      lastHistoryRequestRef.current = sessionId;
      send({ type: 'get_history', session_id: sessionId });
    },
    [send]
  );

  const handleExecutionTraceUpdate = useCallback(
    (payload: any) => {
      const sessionId = String(payload?.session_id || currentSessionId || '').trim();
      const turnId = String(payload?.turn_id || '').trim();
      const summary = normalizeTraceSummary(payload?.trace_summary);
      if (!sessionId || !turnId || !summary) return;
      upsertSummary({
        turn_id: summary.turnId,
        mode: summary.mode,
        status: summary.status,
        headline: summary.headline,
        active_steps: summary.activeSteps,
        completed_steps: summary.completedSteps,
        failed_steps: summary.failedSteps,
        duration_seconds: summary.durationSeconds,
        trace_available: summary.traceAvailable,
        orchestration_id: summary.orchestrationId || null,
      });
      applyConversationTraceSummary(sessionId, turnId, summary);
      if (drawerOpen && activeTurnId === turnId) {
        void loadTrace(turnId);
      }
    },
    [activeTurnId, applyConversationTraceSummary, currentSessionId, drawerOpen, loadTrace, upsertSummary]
  );

  const handleAgentResponseEvent = useCallback(
    (payload: any) => {
      const turnId = String(payload?.turn_id || '').trim();
      const summary = normalizeTraceSummary(payload?.trace_summary);
      if (summary) {
        upsertSummary({
          turn_id: summary.turnId,
          mode: summary.mode,
          status: summary.status,
          headline: summary.headline,
          active_steps: summary.activeSteps,
          completed_steps: summary.completedSteps,
          failed_steps: summary.failedSteps,
          duration_seconds: summary.durationSeconds,
          trace_available: summary.traceAvailable,
          orchestration_id: summary.orchestrationId || null,
        });
      }
      window.dispatchEvent(new Event(SESSION_EVENT));
      if (drawerOpen && activeTurnId === turnId) {
        void loadTrace(turnId);
      }
    },
    [activeTurnId, drawerOpen, loadTrace, upsertSummary]
  );

  const handleWSMessage = useCallback(
    (data: WSMessage) => {
      switch (data.type) {
        case 'subscribed':
          if (currentSessionId) {
            requestHistory(currentSessionId);
          } else {
            send({ type: 'get_current_session' });
          }
          return;
        case 'current_session':
          if (data.data?.session_id) {
            const nextSession = String(data.data.session_id);
            localStorage.setItem(`chat_session_${USER_ID}`, nextSession);
            window.dispatchEvent(new Event(SESSION_EVENT));
            requestHistory(nextSession);
          }
          return;
        case 'history':
          if (data.data?.session_id) {
            send({ type: 'get_personality' });
          }
          return;
        case 'personality_info':
          if (data.data) {
            setAiName(data.data.name || 'AI');
            setAiAvatar(data.data.avatar || '');
            if (currentSessionId && messages.length === 0 && data.data.greeting) {
              receiveAgentResponse({
                sessionId: currentSessionId,
                response: String(data.data.greeting),
                timestamp: Date.now(),
              });
            }
          }
          return;
        case 'message_sent':
          if (data.data?.session_id) {
            setCurrentSessionId(String(data.data.session_id));
          }
          window.dispatchEvent(new Event(SESSION_EVENT));
          return;
        case 'error':
          toast.error(data.message || 'WebSocket error');
          return;
        default:
          break;
      }

      const eventName = data.event || data.type;

      if (eventName === 'execution_trace_update' && data.data) {
        handleExecutionTraceUpdate(data.data);
        return;
      }

      if (eventName === 'agent_response' && data.data) {
        handleAgentResponseEvent(data.data);
      }
    },
    [
      currentSessionId,
      handleAgentResponseEvent,
      handleExecutionTraceUpdate,
      messages.length,
      receiveAgentResponse,
      requestHistory,
      send,
    ]
  );

  useEffect(() => subscribe(handleWSMessage), [handleWSMessage, subscribe]);

  useEffect(() => {
    if (!connected || !currentSessionId) return;
    if (lastHistoryRequestRef.current === currentSessionId) return;
    requestHistory(currentSessionId);
    send({ type: 'get_personality' });
  }, [connected, currentSessionId, requestHistory, send]);

  useEffect(() => {
    const handleMemoryCleared = () => {
      setCurrentSessionId(null);
      lastHistoryRequestRef.current = null;
      resetTraceStore();
      resetConversation();
      if (connected) {
        send({ type: 'get_current_session' });
      }
    };

    window.addEventListener(MEMORY_CLEARED_EVENT, handleMemoryCleared);
    return () => window.removeEventListener(MEMORY_CLEARED_EVENT, handleMemoryCleared);
  }, [connected, resetConversation, resetTraceStore, send, setCurrentSessionId]);

  const handleSendMessage = () => {
    if (!inputValue.trim()) {
      toast.warning(t('chat.emptyInput'));
      return;
    }
    if (!connected) {
      toast.error(t('chat.wsNotConnected'));
      return;
    }

    const messageContent = inputValue.trim();
    const turnId = createClientTurnId();
    const now = Date.now();
    if (currentSessionId) {
      appendPendingTurn({
        sessionId: currentSessionId,
        input: messageContent,
        turnId,
        timestamp: now,
        pendingLabel: t('chat.trace.pending'),
      });
    }
    setInputValue('');
    send({
      type: 'send_message',
      user_id: USER_ID,
      session_id: currentSessionId,
      message: messageContent,
      client_turn_id: turnId,
    });
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (shouldSubmitOnEnter(event as React.KeyboardEvent<HTMLTextAreaElement>, isComposingRef.current)) {
      event.preventDefault();
      handleSendMessage();
    }
  };

  const getAvatar = (role: 'user' | 'assistant') => {
    if (role === 'user') {
      return (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
          <UserRound className="h-4 w-4" />
        </div>
      );
    }
    const initial = aiName?.charAt(0)?.toUpperCase() || 'A';
    let avatarSrc = aiAvatar;
    if (avatarSrc && avatarSrc.startsWith('/')) {
      const apiBaseUrl = getRuntimeConfig().apiBaseUrl;
      const baseUrl = apiBaseUrl.replace(/\/api\/?$/, '');
      avatarSrc = `${baseUrl}${avatarSrc}`;
    }
    if (avatarSrc && avatarSrc.startsWith('http')) {
      return (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary">
          <img src={avatarSrc} alt={aiName} className="h-full w-full object-cover" />
        </div>
      );
    }
    return (
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        {aiAvatar || initial}
      </div>
    );
  };

  const openTraceDrawer = useCallback((turnId: string) => {
    if (!turnId) return;
    window.setTimeout(() => {
      openDrawer(turnId);
      void loadTrace(turnId);
    }, 0);
  }, [loadTrace, openDrawer]);

  const renderTraceEntry = (message: ChatTimelineMessage) => {
    const turnId = message.turnId;
    const traceSummary = turnId ? summaries[turnId] : undefined;
    const canOpenTrace = Boolean(
      turnId &&
      (
        message.traceAvailable ||
        message.traceSummary?.traceAvailable ||
        traceSummary?.trace_available
      )
    );

    if (!turnId || !canOpenTrace) return null;

    return (
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          openTraceDrawer(turnId);
        }}
        className="text-[11px] font-medium text-muted-foreground transition-colors hover:text-primary"
      >
        {t('chat.trace.view')}
      </button>
    );
  };

  const renderStatusCard = (message: ChatTimelineMessage) => (
    <motion.div
      key={message.id}
      initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' }}
      className="mb-4 flex justify-start"
    >
      <div className="flex max-w-[76%] gap-3">
        {getAvatar('assistant')}
        <div className="rounded-2xl rounded-tl-md border border-border/30 bg-muted/50 px-4 py-3">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span className="text-sm font-medium text-foreground">{message.traceSummary?.headline || message.content}</span>
          </div>
          {message.traceSummary && (
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
              <span className="rounded-full bg-muted px-2.5 py-1">
                {t('chat.trace.active', { count: message.traceSummary.activeSteps })}
              </span>
              <span className="rounded-full bg-muted px-2.5 py-1">
                {t('chat.trace.done', { count: message.traceSummary.completedSteps })}
              </span>
              {message.traceSummary.failedSteps > 0 && (
                <span className="rounded-full bg-rose-50 px-2.5 py-1 text-rose-600">
                  {t('chat.trace.failedCount', { count: message.traceSummary.failedSteps })}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="relative flex h-full min-h-0 flex-col px-3 pb-3 pt-2"
    >
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        {messages.map((msg) => (
          msg.kind === 'status' ? (
            renderStatusCard(msg)
          ) : (
            <motion.div
              key={msg.id}
              initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' }}
              className={msg.role === 'user' ? 'mb-5 flex justify-end' : 'mb-5 flex justify-start'}
            >
              <div className={msg.role === 'user' ? 'flex max-w-[75%] flex-row-reverse gap-3' : 'flex max-w-[75%] gap-3'}>
                {getAvatar(msg.role)}
                <div className={msg.role === 'user' ? 'items-end' : 'items-start'}>
                  <div className="mb-1 flex items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      {msg.role === 'user' ? t('chat.you') : aiName}
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {new Date(msg.timestamp).toLocaleTimeString(i18n.language === 'en' ? 'en-US' : 'zh-CN')}
                    </span>
                    {msg.role === 'assistant' && renderTraceEntry(msg)}
                  </div>
                  <div
                    className={msg.role === 'user'
                      ? 'rounded-2xl rounded-tr-md bg-accent/90 px-4 py-3 text-accent-foreground'
                      : 'rounded-2xl rounded-tl-md border border-border/30 bg-muted/50 px-4 py-3'}
                  >
                    {msg.role === 'assistant' ? (
                      <div className="max-w-none text-current">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={assistantMarkdownComponents}>
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <p className="m-0 whitespace-pre-wrap text-sm">{msg.content}</p>
                    )}
                  </div>
                </div>
              </div>
            </motion.div>
          )
        ))}
        <AnimatePresence>
          {!connected && (
            <motion.div initial={shouldReduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={shouldReduceMotion ? undefined : { opacity: 0 }} className="text-center text-xs text-amber-700">
              {t('chat.connectingHint')}
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={messagesEndRef} />
      </div>

      <div className="mt-2 shrink-0">
        <div className="relative rounded-2xl bg-muted/40 px-3 py-3">
          <AutoResizeTextarea
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            placeholder={t('chat.inputPlaceholder')}
            onKeyDown={handleKeyPress}
            disabled={!connected}
            minHeight={120}
            className="max-h-72 resize-none rounded-2xl border border-transparent bg-transparent px-3 py-3 pr-20 text-sm shadow-none placeholder:text-muted-foreground/50 focus-visible:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
          />
          <button
            type="button"
            onClick={() => {
              void handleSendMessage();
            }}
            disabled={!connected}
            className="absolute bottom-4 right-4 flex h-12 w-12 items-center justify-center rounded-full bg-foreground text-background transition-colors hover:bg-foreground/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
            aria-label={t('chat.send')}
            title={t('chat.send')}
          >
            <ArrowUp className="h-5 w-5" />
          </button>
        </div>
      </div>

      <ToolchainDrawer
        open={drawerOpen}
        onOpenChange={(open) => !open && closeDrawer()}
        loading={loadingTrace}
        snapshot={normalizeTraceSnapshot(snapshots[activeTurnId || ''] || null)}
        title={t('chat.trace.title')}
        subtitle={t('chat.trace.subtitle')}
      />
    </motion.div>
  );

  };

export default ChatPage;
