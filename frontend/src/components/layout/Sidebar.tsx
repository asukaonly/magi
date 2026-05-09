import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Database,
  ListChecks,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Search,
  ScrollText,
  Settings2,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { configApi, messagesApi, type ChatSessionListItem } from '@/api';
import { CHAT_SESSION_KEY, DEFAULT_USER_ID } from '@/constants';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useChatShellStore, useConversationStore } from '@/stores';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { formatChatClockTime } from '@/domain/chat/timestamps';

const USER_ID = DEFAULT_USER_ID;
const SESSION_EVENT = 'magi-session-sync';

interface SidebarProps {
  collapsed?: boolean;
}

const MEMORY_DESTINATIONS = [
  { key: 'overview', path: '/memory/overview' },
  { key: 'workbench', path: '/memory/workbench' },
  { key: 'events', path: '/memory/events' },
  { key: 'knowledge', path: '/memory/knowledge' },
  { key: 'reflection', path: '/memory/reflection' },
  { key: 'skills', path: '/memory/skills' },
] as const;

const QUICK_MODE_MEMORY_DESTINATIONS = MEMORY_DESTINATIONS.filter((item) => item.key === 'overview');

const formatSessionTime = (timestamp: number, locale: string): string => {
  return formatChatClockTime(timestamp, locale);
};

const getSessionDisplayLabel = (
  session: ChatSessionListItem,
  fallbackTitle: string,
) => {
  if (session.title_overridden && session.title) {
    return session.title;
  }
  return session.last_user_message_preview || session.title || fallbackTitle;
};

const getSessionSearchText = (session: ChatSessionListItem) =>
  [
    session.title || '',
    session.last_user_message_preview || '',
    session.last_message_preview || '',
  ]
    .join(' ')
    .toLowerCase();

export default function Sidebar({ collapsed = false }: SidebarProps) {
  const { t, i18n } = useTranslation('app');
  const navigate = useNavigate();
  const location = useLocation();
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
  const orderedSessionIds = useConversationStore((state) => state.orderedSessionIds);
  const sessionsById = useConversationStore((state) => state.sessionsById);
  const hydrateSessions = useConversationStore((state) => state.hydrateSessions);
  const unreadBySession = useConversationStore((state) => state.unreadBySession);
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const clearSettingsNavigationIntent = useChatShellStore((state) => state.clearSettingsNavigationIntent);

  const [loading, setLoading] = useState(false);
  const isConversationRoute = location.pathname === '/' || location.pathname === '/chat';
  const isMemoryRoute = location.pathname === '/events' || location.pathname.startsWith('/memory');
  const shouldRefreshSessions = isConversationRoute;
  const [expandedSection, setExpandedSection] = useState<'conversation' | 'memory' | null>(
    isMemoryRoute ? 'memory' : isConversationRoute ? 'conversation' : null
  );
  const [conversationSearch, setConversationSearch] = useState('');
  const conversationSearchInputRef = useRef<HTMLInputElement>(null);
  const [sessionMenu, setSessionMenu] = useState<{
    sessionId: string;
    x: number;
    y: number;
  } | null>(null);
  const [renameTargetSession, setRenameTargetSession] = useState<ChatSessionListItem | null>(null);
  const [deleteTargetSession, setDeleteTargetSession] = useState<ChatSessionListItem | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [actionPending, setActionPending] = useState(false);
  const [userMode, setUserMode] = useState<'quick' | 'expert' | null>(null);
  const sessionMenuRef = useRef<HTMLDivElement>(null);
  const sessionCreatingRef = useRef(false);

  const refreshSessions = useCallback(async (preferredSessionId?: string | null) => {
    const sessionStorageKey = CHAT_SESSION_KEY(USER_ID);
    const readPersistedSessionId = () => {
      try {
        return window.localStorage.getItem(sessionStorageKey);
      } catch {
        return null;
      }
    };
    const persistSessionId = (sessionId: string | null) => {
      try {
        if (sessionId) {
          window.localStorage.setItem(sessionStorageKey, sessionId);
        } else {
          window.localStorage.removeItem(sessionStorageKey);
        }
      } catch {
        // ignore persistence failures and keep the in-memory selection
      }
    };

    setLoading(true);
    try {
      const loadSessions = async (
        allowCreate: boolean,
        requestedSessionId: string | null = preferredSessionId ?? null,
      ): Promise<void> => {
        const response = await messagesApi.listSessions(USER_ID, 50);
        const sessions = response.sessions || [];
        if (sessions.length === 0 && allowCreate && !sessionCreatingRef.current) {
          sessionCreatingRef.current = true;
          try {
            const created = await messagesApi.createNewSession(USER_ID);
            if (created.session_id) {
              persistSessionId(created.session_id);
              await loadSessions(false, created.session_id);
              return;
            }
          } finally {
            sessionCreatingRef.current = false;
          }
        }
        const sessionIds = sessions.map((session) => session.session_id);
        const latestSessionId = useConversationStore.getState().currentSessionId;
        const persistedSessionId = readPersistedSessionId();
        const preferredSessionId = (
          (requestedSessionId && sessionIds.includes(requestedSessionId) ? requestedSessionId : null)
          || (latestSessionId && sessionIds.includes(latestSessionId) ? latestSessionId : null)
          || (persistedSessionId && sessionIds.includes(persistedSessionId) ? persistedSessionId : null)
          || sessionIds[0]
          || null
        );
        hydrateSessions(sessions, preferredSessionId);
        setCurrentSessionId(preferredSessionId);
        persistSessionId(preferredSessionId);
      };

      await loadSessions(true);
    } catch {
      hydrateSessions([], useConversationStore.getState().currentSessionId);
    } finally {
      setLoading(false);
    }
  }, [hydrateSessions, setCurrentSessionId]);

  useEffect(() => {
    if (!shouldRefreshSessions) {
      return undefined;
    }

    void refreshSessions();
    const handleSync = () => {
      void refreshSessions();
    };
    const handleFocus = () => {
      void refreshSessions();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void refreshSessions();
      }
    };
    window.addEventListener(SESSION_EVENT, handleSync as EventListener);
    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener(SESSION_EVENT, handleSync as EventListener);
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [refreshSessions, shouldRefreshSessions]);

  useEffect(() => {
    let cancelled = false;

    const loadUserMode = async () => {
      try {
        const response = await configApi.get();
        if (!cancelled) {
          setUserMode(response.data?.preferences?.user_mode ?? null);
        }
      } catch {
        if (!cancelled) {
          setUserMode(null);
        }
      }
    };

    void loadUserMode();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (isMemoryRoute) {
      setExpandedSection('memory');
      return;
    }
    if (isConversationRoute) {
      setExpandedSection('conversation');
      return;
    }
    setExpandedSection(null);
  }, [isConversationRoute, isMemoryRoute]);

  useEffect(() => {
    if (!sessionMenu) {
      return undefined;
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (!sessionMenuRef.current?.contains(event.target as Node)) {
        setSessionMenu(null);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSessionMenu(null);
      }
    };
    const handleScroll = () => {
      setSessionMenu(null);
    };
    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [sessionMenu]);

  const handleCreateSession = async () => {
    try {
      const result = await messagesApi.createNewSession(USER_ID);
      if (result.session_id) {
        window.localStorage.setItem(CHAT_SESSION_KEY(USER_ID), result.session_id);
        await refreshSessions(result.session_id);
        setActivePanel('conversation');
        setExpandedSection('conversation');
        navigate('/chat');
      }
    } catch {
      // ignore at shell level, chat page will surface failure details
    }
  };

  const openSessionMenu = useCallback(
    (sessionId: string, anchorX: number, anchorY: number) => {
      setSessionMenu({
        sessionId,
        x: Math.max(16, anchorX),
        y: Math.max(16, anchorY),
      });
    },
    [],
  );

  const handleRenameSession = useCallback(async () => {
    if (!renameTargetSession) {
      return;
    }
    const nextTitle = renameValue.trim();
    if (!nextTitle) {
      return;
    }
    setActionPending(true);
    try {
      await messagesApi.renameSession(USER_ID, renameTargetSession.session_id, nextTitle);
      await refreshSessions();
      setRenameTargetSession(null);
    } finally {
      setActionPending(false);
    }
  }, [refreshSessions, renameTargetSession, renameValue]);

  const handleDeleteSession = useCallback(async () => {
    if (!deleteTargetSession) {
      return;
    }
    setActionPending(true);
    try {
      await messagesApi.deleteSession(USER_ID, deleteTargetSession.session_id);
      await refreshSessions();
      setDeleteTargetSession(null);
      setExpandedSection('conversation');
      setActivePanel('conversation');
      navigate('/chat');
    } finally {
      setActionPending(false);
    }
  }, [deleteTargetSession, navigate, refreshSessions, setActivePanel, setCurrentSessionId]);

  const sessionRows = useMemo(() => {
    if (orderedSessionIds.length > 0) {
      return orderedSessionIds
        .map((sessionId) => sessionsById[sessionId])
        .filter(Boolean) as ChatSessionListItem[];
    }
    if (currentSessionId) {
      return [
        {
          session_id: currentSessionId,
          title: t('shell.newChatTitle'),
          last_message_preview: '',
          last_timestamp: 0,
          message_count: 0,
        },
      ];
    }
    return [];
  }, [currentSessionId, orderedSessionIds, sessionsById, t]);

  const filteredSessionRows = useMemo(() => {
    const normalizedQuery = conversationSearch.trim().toLowerCase();
    if (!normalizedQuery) {
      return sessionRows;
    }
    return sessionRows.filter((session) => {
      return getSessionSearchText(session).includes(normalizedQuery);
    });
  }, [conversationSearch, sessionRows]);

  const visibleMemoryDestinations = userMode === 'quick'
    ? QUICK_MODE_MEMORY_DESTINATIONS
    : MEMORY_DESTINATIONS;

  const tasksActiveCount = useBackgroundTaskStore((state) => state.activeCount);

  if (collapsed) {
    return null;
  }

  const conversationActive = activePanel === 'conversation' || isConversationRoute;
  const timelineActive = activePanel === 'timeline' || location.pathname === '/timeline';
  const memoryActive = activePanel === 'memory' || isMemoryRoute;
  const settingsActive = activePanel === 'settings';
  const tasksActive = activePanel === 'tasks' || location.pathname === '/tasks';
  const conversationExpanded = expandedSection === 'conversation';
  const memoryExpanded = expandedSection === 'memory';
  const sessionMenuSession = sessionMenu ? sessionsById[sessionMenu.sessionId] : null;

  const primaryButtonClass = (active: boolean) => cn(
    'flex w-full items-center gap-3 rounded-md px-4 py-3 text-left transition-colors duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.25)]',
    active
      ? 'bg-[hsl(var(--sidebar-active))] text-[hsl(var(--sidebar-active-foreground))]'
      : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-active-foreground))]'
  );

  const iconWrapClass = (active: boolean) => cn(
    'flex h-5 w-5 shrink-0 items-center justify-center transition-colors duration-150',
    active
      ? 'text-[hsl(var(--sidebar-active-foreground))]'
      : 'text-[hsl(var(--sidebar-muted))]'
  );

  const nestedRailClass = 'mt-2 ml-5 flex flex-col gap-1.5';

  const secondaryButtonClass = (active: boolean) => cn(
    'flex w-full items-center gap-2 rounded-md px-3 py-2.5 text-left text-sm transition-colors duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.22)]',
    active
      ? 'bg-[hsl(var(--sidebar-subactive))] text-[hsl(var(--sidebar-active-foreground))]'
      : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-active-foreground))]'
  );

  const toolButtonClass =
    'flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--sidebar-tool))] text-[hsl(var(--sidebar-muted))] transition-colors duration-150 ease-out hover:bg-[hsl(var(--sidebar-tool-hover))] hover:text-[hsl(var(--sidebar-active-foreground))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]';

  return (
    <aside
      className="relative flex h-full min-h-0 flex-col overflow-hidden border-r border-[hsl(var(--sidebar-border))] bg-[linear-gradient(180deg,hsl(var(--sidebar-background-start))_0%,hsl(var(--sidebar-background-end))_100%)] pt-7"
    >
      {sessionMenu && sessionMenuSession ? (
        <div
          ref={sessionMenuRef}
          className="fixed z-[90] min-w-[160px] rounded-lg bg-[hsl(var(--sidebar-menu))] p-1.5 shadow-[0_14px_36px_hsl(var(--sidebar-shadow)/0.16)]"
          style={{ left: sessionMenu.x, top: sessionMenu.y }}
        >
          <button
            type="button"
            onClick={() => {
              setRenameTargetSession(sessionMenuSession);
              setRenameValue(getSessionDisplayLabel(sessionMenuSession, t('shell.newChatTitle')));
              setSessionMenu(null);
            }}
            className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-[hsl(var(--sidebar-active-foreground))] transition-colors hover:bg-[hsl(var(--sidebar-hover))]"
          >
            {t('shell.renameSession')}
          </button>
          <button
            type="button"
            onClick={() => {
              setDeleteTargetSession(sessionMenuSession);
              setSessionMenu(null);
            }}
            className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10"
          >
            {t('shell.deleteSession')}
          </button>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col px-4 py-3">
        <div className="flex min-h-0 flex-1 flex-col gap-2.5">
          <section className="shrink-0">
            <button
              type="button"
              onClick={() => {
                setActivePanel('conversation');
                if (!isConversationRoute) {
                  setExpandedSection('conversation');
                  navigate('/chat');
                  return;
                }
                setExpandedSection((current) => (current === 'conversation' ? null : 'conversation'));
              }}
              aria-label={t('shell.conversation')}
              aria-current={conversationActive ? 'page' : undefined}
              aria-expanded={conversationExpanded}
              className={primaryButtonClass(conversationActive)}
            >
              <span className={iconWrapClass(conversationActive)}>
                <MessageSquare className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1 text-sm font-medium">{t('shell.conversation')}</span>
              {conversationExpanded ? (
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              )}
            </button>

            {conversationExpanded ? (
              <div
                className={nestedRailClass}
                data-testid="sidebar-conversation-rail"
              >
                <div
                  className="flex items-center gap-1"
                  data-testid="sidebar-conversation-tools"
                >
                <div className="flex min-w-0 flex-1 items-center rounded-md bg-[hsl(var(--sidebar-tool))] px-2.5">
                  <input
                      ref={conversationSearchInputRef}
                      type="search"
                      value={conversationSearch}
                      onChange={(event) => setConversationSearch(event.target.value)}
                      placeholder={t('shell.searchSessionsPlaceholder')}
                      aria-label={t('shell.searchSessions')}
                      className="h-7 w-full bg-transparent text-[11px] text-[hsl(var(--sidebar-foreground))] outline-none placeholder:text-[hsl(var(--sidebar-muted))]"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      conversationSearchInputRef.current?.focus();
                      conversationSearchInputRef.current?.select();
                    }}
                    className={toolButtonClass}
                    aria-label={t('shell.searchSessionsAction')}
                    title={t('shell.searchSessionsAction')}
                  >
                    <Search className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleCreateSession();
                    }}
                    className={toolButtonClass}
                    aria-label={t('shell.newChat')}
                    title={t('shell.newChat')}
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="max-h-[22rem] overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                  {sessionRows.length === 0 ? (
                    <div className="bg-[hsl(var(--sidebar-tool))] px-3 py-2.5 text-xs leading-5 text-[hsl(var(--sidebar-muted))]">
                      {loading ? t('shell.loadingSessions') : t('shell.emptySessions')}
                    </div>
                  ) : filteredSessionRows.length === 0 ? (
                    <div className="bg-[hsl(var(--sidebar-tool))] px-3 py-2.5 text-xs leading-5 text-[hsl(var(--sidebar-muted))]">
                      {t('shell.searchSessionsEmpty')}
                    </div>
                  ) : (
                    <div className="space-y-0.5">
                      {filteredSessionRows.map((session) => {
                        const active = currentSessionId === session.session_id;
                        const unreadCount = unreadBySession[session.session_id] || 0;
                        const displayLabel = getSessionDisplayLabel(session, t('shell.newChatTitle'));
                        return (
                          <div
                            key={session.session_id}
                            className={cn(
                              'group/session flex items-center gap-1 rounded-md transition-colors duration-150 ease-out',
                              active
                                ? 'bg-[hsl(var(--sidebar-active))] text-[hsl(var(--sidebar-active-foreground))]'
                                : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover))] hover:text-[hsl(var(--sidebar-active-foreground))]'
                            )}
                          >
                            <button
                              type="button"
                              onClick={() => {
                                window.localStorage.setItem(CHAT_SESSION_KEY(USER_ID), session.session_id);
                                setCurrentSessionId(session.session_id);
                                setActivePanel('conversation');
                                navigate('/chat');
                              }}
                              onContextMenu={(event) => {
                                event.preventDefault();
                                openSessionMenu(session.session_id, event.clientX, event.clientY);
                              }}
                              aria-label={displayLabel}
                              aria-current={active ? 'page' : undefined}
                              className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]"
                              title={displayLabel}
                            >
                              <span className="min-w-0 flex-1 truncate font-medium">{displayLabel}</span>
                              {unreadCount > 0 ? (
                                <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1.5 py-0.5 text-[10px] font-medium text-[hsl(var(--sidebar-badge-foreground))]">
                                  {Math.min(unreadCount, 99)}
                                </span>
                              ) : null}
                              <span className="shrink-0 text-[11px] text-[hsl(var(--sidebar-muted))]">
                                {formatSessionTime(session.last_timestamp, i18n.language)}
                              </span>
                            </button>
                            <button
                              type="button"
                              onClick={(event) => {
                                const rect = event.currentTarget.getBoundingClientRect();
                                openSessionMenu(session.session_id, rect.right - 176, rect.bottom + 6);
                              }}
                              className={cn(
                                'mr-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[hsl(var(--sidebar-muted))] opacity-0 transition-all duration-150 ease-out focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)] group-hover/session:opacity-100',
                                active
                                  ? 'hover:bg-[hsl(var(--sidebar-subactive))] hover:text-[hsl(var(--sidebar-active-foreground))]'
                                  : 'hover:bg-[hsl(var(--sidebar-tool-hover))] hover:text-[hsl(var(--sidebar-active-foreground))]'
                              )}
                              aria-label={t('shell.sessionActions')}
                              title={t('shell.sessionActions')}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </section>

          <button
            type="button"
            onClick={() => {
              setExpandedSection(null);
              setActivePanel('timeline');
              navigate('/timeline');
            }}
            aria-label={t('shell.timeline')}
            aria-current={timelineActive ? 'page' : undefined}
            className={cn(primaryButtonClass(timelineActive), 'shrink-0')}
          >
            <span className={iconWrapClass(timelineActive)}>
              <ScrollText className="h-4 w-4" />
            </span>
            <span className="text-sm font-medium">{t('shell.timeline')}</span>
          </button>

          <section className={cn('shrink-0', memoryExpanded && 'flex min-h-0 flex-1 flex-col')}>
            <button
              type="button"
              onClick={() => {
                setActivePanel('memory');
                if (!isMemoryRoute) {
                  setExpandedSection('memory');
                  navigate('/memory/overview');
                  return;
                }
                setExpandedSection((current) => (current === 'memory' ? null : 'memory'));
              }}
              aria-label={t('shell.memory')}
              aria-current={memoryActive ? 'page' : undefined}
              aria-expanded={memoryExpanded}
              className={primaryButtonClass(memoryActive)}
            >
              <span className={iconWrapClass(memoryActive)}>
                <Database className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1 text-sm font-medium">{t('shell.memory')}</span>
              {memoryExpanded ? (
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              )}
            </button>

            {memoryExpanded ? (
              <div
                className={cn(nestedRailClass, 'min-h-0 flex-1')}
                data-testid="sidebar-memory-rail"
              >
                <div className="min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                  <div className="space-y-1">
                  {visibleMemoryDestinations.map((item) => {
                    const destinationActive =
                      location.pathname === item.path ||
                      (item.path === '/memory/overview' && location.pathname === '/events');
                    return (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => {
                          setExpandedSection('memory');
                          setActivePanel('memory');
                          navigate(item.path);
                        }}
                        aria-label={t(`memory.nav.${item.key}`)}
                        aria-current={destinationActive ? 'page' : undefined}
                        className={secondaryButtonClass(destinationActive)}
                      >
                        {t(`memory.nav.${item.key}`)}
                      </button>
                    );
                  })}
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        </div>

        <div className="shrink-0 pt-2">
          <button
            type="button"
            onClick={() => {
              setExpandedSection(null);
              setActivePanel('tasks');
              navigate('/tasks');
            }}
            aria-label={t('shell.tasks')}
            aria-current={tasksActive ? 'page' : undefined}
            className={primaryButtonClass(tasksActive)}
          >
            <span className={iconWrapClass(tasksActive)}>
              <ListChecks className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1 text-sm font-medium">{t('shell.tasks')}</span>
            {tasksActiveCount > 0 ? (
              <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1.5 py-0.5 text-[10px] font-medium text-[hsl(var(--sidebar-badge-foreground))]">
                {Math.min(tasksActiveCount, 99)}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            onClick={() => {
              clearSettingsNavigationIntent();
              setActivePanel('settings');
            }}
            aria-label={t('shell.settings')}
            aria-current={settingsActive ? 'page' : undefined}
            className={cn(primaryButtonClass(settingsActive), 'mt-1')}
          >
            <span className={iconWrapClass(settingsActive)}>
              <Settings2 className="h-4 w-4" />
            </span>
            <span className="text-sm font-medium">{t('shell.settings')}</span>
          </button>
        </div>
      </div>

      <Dialog
        open={Boolean(renameTargetSession)}
        onOpenChange={(open) => {
          if (!open && !actionPending) {
            setRenameTargetSession(null);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('shell.renameSessionTitle')}</DialogTitle>
            <DialogDescription>{t('shell.renameSessionDescription')}</DialogDescription>
          </DialogHeader>
          <div className="px-6 pb-2">
            <input
              type="text"
              value={renameValue}
              onChange={(event) => setRenameValue(event.target.value)}
              placeholder={t('shell.renameSessionPlaceholder')}
              className="h-11 w-full rounded-none border border-border/55 bg-background px-3 text-sm outline-none transition-colors focus:border-primary/40"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setRenameTargetSession(null)}
              disabled={actionPending}
            >
              {t('shell.cancel')}
            </Button>
            <Button
              type="button"
              onClick={() => {
                void handleRenameSession();
              }}
              disabled={actionPending || !renameValue.trim()}
            >
              {t('shell.saveRename')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(deleteTargetSession)}
        onOpenChange={(open) => {
          if (!open && !actionPending) {
            setDeleteTargetSession(null);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('shell.deleteSessionTitle')}</DialogTitle>
            <DialogDescription>{t('shell.deleteSessionDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteTargetSession(null)}
              disabled={actionPending}
            >
              {t('shell.cancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                void handleDeleteSession();
              }}
              disabled={actionPending}
            >
              {t('shell.confirmDeleteSession')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  );
}
