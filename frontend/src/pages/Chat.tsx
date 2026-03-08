/**
 * Chat page - desktop-focused conversation workspace
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Send, Wrench, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnimatePresence, motion } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { messagesApi } from '@/api';
import { getRuntimeConfig } from '@/runtime/config';
import { useChatShellStore, useChatTraceStore, type ChatPanelType } from '@/stores';
import ToolchainDrawer from '@/components/chat/ToolchainDrawer';
import PersonalityModern from './PersonalityModern';
import EventsPage from './Events';
import SettingsCenterDialog from '@/components/layout/SettingsCenterDialog';
import {
  applyAgentResponse,
  createPendingTurn,
  normalizeHistoryMessages,
  normalizeTraceSnapshot,
  normalizeTraceSummary,
  type ChatTimelineMessage,
} from './chat-state';
import { upsertTraceSummary } from './chat-state';

interface WSMessage {
  type?: string;
  data?: any;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
}

const CONNECTION_EVENT = 'magi-chat-connection';
const MEMORY_CLEARED_EVENT = 'magi-memory-cleared';
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

export const panelByPathname = (pathname: string): ChatPanelType => {
  if (pathname === '/settings') return 'settings';
  if (pathname === '/personality') return 'personality';
  if (pathname === '/events') return 'memory';
  return 'none';
};

const createClientTurnId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `turn_${crypto.randomUUID()}`;
  }
  return `turn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
};

export const ChatPage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const location = useLocation();
  const navigate = useNavigate();
  const currentSessionId = useChatShellStore((state) => state.currentSessionId);
  const setCurrentSessionId = useChatShellStore((state) => state.setCurrentSessionId);
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);

  const drawerOpen = useChatTraceStore((state) => state.drawerOpen);
  const activeTurnId = useChatTraceStore((state) => state.activeTurnId);
  const summaries = useChatTraceStore((state) => state.summaries);
  const snapshots = useChatTraceStore((state) => state.snapshots);
  const upsertSummary = useChatTraceStore((state) => state.upsertSummary);
  const setSnapshot = useChatTraceStore((state) => state.setSnapshot);
  const openDrawer = useChatTraceStore((state) => state.openDrawer);
  const closeDrawer = useChatTraceStore((state) => state.closeDrawer);
  const resetTraceStore = useChatTraceStore((state) => state.reset);

  const [messages, setMessages] = useState<ChatTimelineMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [aiName, setAiName] = useState<string>('AI');
  const [aiAvatar, setAiAvatar] = useState<string>('');
  const [connected, setConnected] = useState(false);
  const [loadingTrace, setLoadingTrace] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectCountRef = useRef(0);
  const lastHistoryRequestRef = useRef<string | null>(null);

  const WS_CONFIG = {
    maxReconnectAttempts: 10,
    baseDelay: 1000,
    maxDelay: 30000,
  };

  useEffect(() => {
    setActivePanel(panelByPathname(location.pathname));
  }, [location.pathname, setActivePanel]);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent(CONNECTION_EVENT, { detail: { connected } }));
  }, [connected]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const closePanel = useCallback(() => {
    setActivePanel('none');
    if (location.pathname !== '/' && location.pathname !== '/chat') {
      navigate('/chat');
    }
  }, [location.pathname, navigate, setActivePanel]);

  const preloadTraceSummaries = useCallback(
    (historyMessages: ChatTimelineMessage[]) => {
      resetTraceStore();
      historyMessages.forEach((message) => {
        if (message.traceSummary) {
          upsertSummary({
            turn_id: message.traceSummary.turnId,
            mode: message.traceSummary.mode,
            status: message.traceSummary.status,
            headline: message.traceSummary.headline,
            active_steps: message.traceSummary.activeSteps,
            completed_steps: message.traceSummary.completedSteps,
            failed_steps: message.traceSummary.failedSteps,
            duration_seconds: message.traceSummary.durationSeconds,
            trace_available: message.traceSummary.traceAvailable,
            orchestration_id: message.traceSummary.orchestrationId || null,
          });
        }
      });
    },
    [resetTraceStore, upsertSummary]
  );

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

  const getReconnectDelay = useCallback(() => {
    const delay = Math.min(
      WS_CONFIG.baseDelay * Math.pow(2, reconnectCountRef.current),
      WS_CONFIG.maxDelay
    );
    return delay + Math.random() * 1000;
  }, []);

  const sendWS = useCallback((type: string, data?: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, ...data }));
    }
  }, []);

  const requestHistory = useCallback(
    (sessionId: string) => {
      if (!sessionId) return;
      lastHistoryRequestRef.current = sessionId;
      sendWS('get_history', { session_id: sessionId });
    },
    [sendWS]
  );

  const resolveWsUrl = useCallback(() => {
    const runtime = getRuntimeConfig();
    const base = `${runtime.wsBaseUrl}/ws`;
    if (!runtime.sessionToken) {
      return base;
    }
    const separator = base.includes('?') ? '&' : '?';
    return `${base}${separator}token=${encodeURIComponent(runtime.sessionToken)}`;
  }, []);

  const handleExecutionTraceUpdate = useCallback(
    (payload: any) => {
      const turnId = String(payload?.turn_id || '').trim();
      const summary = normalizeTraceSummary(payload?.trace_summary);
      if (!turnId || !summary) return;
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
      setMessages((prev) => upsertTraceSummary(prev, turnId, summary));
      if (drawerOpen && activeTurnId === turnId) {
        void loadTrace(turnId);
      }
    },
    [activeTurnId, drawerOpen, loadTrace, upsertSummary]
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
      setMessages((prev) =>
        applyAgentResponse(prev, {
          response: String(payload?.response || ''),
          timestamp: Number(payload?.timestamp || Date.now() / 1000) * 1000,
          turnId,
          traceSummary: summary,
          traceAvailable: Boolean(payload?.trace_available || summary?.traceAvailable),
        })
      );
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
            sendWS('get_current_session');
          }
          return;
        case 'current_session':
          if (data.data?.session_id) {
            const nextSession = String(data.data.session_id);
            setCurrentSessionId(nextSession);
            localStorage.setItem(`chat_session_${USER_ID}`, nextSession);
            requestHistory(nextSession);
          }
          return;
        case 'history':
          if (data.data?.session_id) {
            const resolvedSession = String(data.data.session_id);
            setCurrentSessionId(resolvedSession);
            const historyMessages = normalizeHistoryMessages(data.data.messages || []);
            preloadTraceSummaries(historyMessages);
            setMessages(historyMessages);
            sendWS('get_personality');
          }
          return;
        case 'personality_info':
          if (data.data) {
            setAiName(data.data.name || 'AI');
            setAiAvatar(data.data.avatar || '');
            setMessages((prev) => {
              if (prev.length === 0 && data.data.greeting) {
                return [
                  {
                    id: `welcome-${Date.now()}`,
                    role: 'assistant',
                    kind: 'assistant',
                    content: data.data.greeting,
                    timestamp: Date.now(),
                  },
                ];
              }
              return prev;
            });
          }
          return;
        case 'message_sent':
          if (data.data?.session_id) {
            setCurrentSessionId(String(data.data.session_id));
          }
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
      preloadTraceSummaries,
      requestHistory,
      sendWS,
      setCurrentSessionId,
    ]
  );

  const connectWebSocket = useCallback(() => {
    const room = `user_${USER_ID}`;

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const websocket = new WebSocket(resolveWsUrl());

    websocket.onopen = () => {
      setConnected(true);
      reconnectCountRef.current = 0;
      websocket.send(JSON.stringify({ type: 'subscribe', channel: room }));
    };

    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWSMessage(data);
      } catch {
        // ignore malformed payload
      }
    };

    websocket.onclose = (event) => {
      setConnected(false);
      if (event.code !== 1000 && reconnectCountRef.current < WS_CONFIG.maxReconnectAttempts) {
        const delay = getReconnectDelay();
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectCountRef.current++;
          connectWebSocket();
        }, delay);
      } else if (reconnectCountRef.current >= WS_CONFIG.maxReconnectAttempts) {
        toast.error(t('chat.reconnectFailed'));
      }
    };

    websocket.onerror = () => {
      setConnected(false);
    };

    wsRef.current = websocket;
  }, [getReconnectDelay, handleWSMessage, resolveWsUrl, t]);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounting');
      }
    };
  }, [connectWebSocket]);

  useEffect(() => {
    if (!connected || !currentSessionId) return;
    if (lastHistoryRequestRef.current === currentSessionId) return;
    requestHistory(currentSessionId);
    sendWS('get_personality');
  }, [connected, currentSessionId, requestHistory, sendWS]);

  useEffect(() => {
    const handleMemoryCleared = () => {
      setMessages([]);
      setCurrentSessionId(null);
      lastHistoryRequestRef.current = null;
      resetTraceStore();
      if (connected && wsRef.current?.readyState === WebSocket.OPEN) {
        sendWS('get_current_session');
      }
    };

    window.addEventListener(MEMORY_CLEARED_EVENT, handleMemoryCleared);
    return () => window.removeEventListener(MEMORY_CLEARED_EVENT, handleMemoryCleared);
  }, [connected, resetTraceStore, sendWS, setCurrentSessionId]);

  const handleSendMessage = () => {
    if (!inputValue.trim()) {
      toast.warning(t('chat.emptyInput'));
      return;
    }
    if (!connected || wsRef.current?.readyState !== WebSocket.OPEN) {
      toast.error(t('chat.wsNotConnected'));
      return;
    }

    const messageContent = inputValue.trim();
    const turnId = createClientTurnId();
    const now = Date.now();
    setMessages((prev) => [...prev, ...createPendingTurn(messageContent, turnId, now, t('chat.trace.pending'))]);
    setInputValue('');
    sendWS('send_message', {
      user_id: USER_ID,
      session_id: currentSessionId,
      message: messageContent,
      client_turn_id: turnId,
    });
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      handleSendMessage();
    }
  };

  const getAvatar = (role: 'user' | 'assistant') => {
    if (role === 'user') {
      return (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-white">
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
        <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/80 eva-glow">
          <img src={avatarSrc} alt={aiName} className="h-full w-full object-cover" />
        </div>
      );
    }
    return (
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/80 text-white eva-glow">
        {aiAvatar || initial}
      </div>
    );
  };

  const renderTraceButton = (message: ChatTimelineMessage) => {
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
          window.setTimeout(() => {
            openDrawer(turnId);
            void loadTrace(turnId);
          }, 0);
        }}
        className="mt-3 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/15"
      >
        <Wrench className="h-3.5 w-3.5" />
        {t('chat.trace.view')}
      </button>
    );
  };

  const renderStatusCard = (message: ChatTimelineMessage) => (
    <motion.div
      key={message.id}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className="mb-4 flex justify-start"
    >
      <div className="flex max-w-[76%] gap-3">
        {getAvatar('assistant')}
        <div className="rounded-2xl rounded-tl-md border border-border/50 bg-white px-4 py-3 shadow-sm">
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
          {renderTraceButton(message)}
        </div>
      </div>
    </motion.div>
  );

  return (
    <div className="relative flex h-full min-h-0 flex-col px-4 py-4">
      <div className="desktop-panel min-h-0 flex-1 overflow-y-auto rounded-2xl px-5 py-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        {messages.map((msg) => (
          msg.kind === 'status' ? (
            renderStatusCard(msg)
          ) : (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
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
                  </div>
                  <div
                    className={msg.role === 'user'
                      ? 'rounded-2xl rounded-tr-md bg-accent/90 px-4 py-3 text-white'
                      : 'rounded-2xl rounded-tl-md border border-border/50 bg-card/80 px-4 py-3 backdrop-blur-sm'}
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
                    {msg.role === 'assistant' && renderTraceButton(msg)}
                  </div>
                </div>
              </div>
            </motion.div>
          )
        ))}
        <AnimatePresence>
          {!connected && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-center text-xs text-amber-700">
              {t('chat.connectingHint')}
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={messagesEndRef} />
      </div>

      <div className="desktop-panel mt-3 shrink-0 rounded-2xl px-4 pb-3 pt-3">
        <div className="flex items-end gap-3">
          <AutoResizeTextarea
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            placeholder={t('chat.inputPlaceholder')}
            onKeyDown={handleKeyPress}
            disabled={!connected}
            minHeight={84}
            className="max-h-64 resize-none rounded-xl border-0 bg-muted/40 px-4 py-3 text-sm shadow-none placeholder:text-muted-foreground/50 focus-visible:ring-1 focus-visible:ring-primary/30"
          />
          <Button onClick={handleSendMessage} disabled={!connected} className="h-11 rounded-xl bg-primary px-5 text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            <Send className="mr-1 h-4 w-4" />
            {t('chat.send')}
          </Button>
        </div>
        <div className="mt-2 text-center text-xs text-muted-foreground/60">{t('chat.tip')}</div>
      </div>

      <ToolchainDrawer
        open={drawerOpen}
        onOpenChange={(open) => !open && closeDrawer()}
        loading={loadingTrace}
        snapshot={normalizeTraceSnapshot(snapshots[activeTurnId || ''] || null)}
        title={t('chat.trace.title')}
        subtitle={t('chat.trace.subtitle')}
      />

      <SettingsCenterDialog open={activePanel === 'settings'} onOpenChange={(open) => !open && closePanel()} />

      <Dialog open={activePanel === 'personality'} onOpenChange={(open) => !open && closePanel()}>
        <DialogContent className="h-[88vh] max-w-5xl overflow-hidden p-0">
          <div className="h-full overflow-y-auto p-4">
            <PersonalityModern />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={activePanel === 'memory'} onOpenChange={(open) => !open && closePanel()}>
        <DialogContent className="h-[88vh] max-w-5xl overflow-hidden p-0">
          <div className="h-full overflow-y-auto p-4">
            <EventsPage />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ChatPage;
