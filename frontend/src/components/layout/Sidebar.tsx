import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Database,
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
import { messagesApi, type ChatSessionListItem } from '@/api';
import { CHAT_SESSION_KEY } from '@/constants';
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

const USER_ID = 'web_user';
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

const formatSessionTime = (timestamp: number, locale: string): string => {
  if (!timestamp) {
    return '';
  }
  try {
    return new Date(timestamp * 1000).toLocaleTimeString(locale === 'en' ? 'en-US' : 'zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
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

  const [loading, setLoading] = useState(false);
  const isConversationRoute = location.pathname === '/' || location.pathname === '/chat';
  const isMemoryRoute = location.pathname === '/events' || location.pathname.startsWith('/memory');
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
  const sessionMenuRef = useRef<HTMLDivElement>(null);

  const refreshSessions = useCallback(async () => {
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
      const loadSessions = async (allowCreate: boolean): Promise<void> => {
        const response = await messagesApi.listSessions(USER_ID, 50);
        const sessions = response.sessions || [];
        if (sessions.length === 0 && allowCreate) {
          const created = await messagesApi.createNewSession(USER_ID);
          if (created.session_id) {
            persistSessionId(created.session_id);
            setCurrentSessionId(created.session_id);
            await loadSessions(false);
            return;
          }
        }
        const sessionIds = sessions.map((session) => session.session_id);
        const persistedSessionId = readPersistedSessionId();
        const preferredSessionId = (
          (currentSessionId && sessionIds.includes(currentSessionId) ? currentSessionId : null)
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
      hydrateSessions([], currentSessionId);
    } finally {
      setLoading(false);
    }
  }, [currentSessionId, hydrateSessions, setCurrentSessionId]);

  useEffect(() => {
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
  }, [refreshSessions]);

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
        setCurrentSessionId(result.session_id);
        await refreshSessions();
        setActivePanel('conversation');
        setExpandedSection('conversation');
        navigate('/chat');
        window.dispatchEvent(new Event(SESSION_EVENT));
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
      window.dispatchEvent(new Event(SESSION_EVENT));
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
      window.dispatchEvent(new Event(SESSION_EVENT));
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

  if (collapsed) {
    return null;
  }

  const conversationActive = activePanel === 'conversation' || isConversationRoute;
  const timelineActive = activePanel === 'timeline' || location.pathname === '/timeline';
  const memoryActive = activePanel === 'memory' || isMemoryRoute;
  const settingsActive = activePanel === 'settings' || location.pathname === '/settings';
  const conversationExpanded = expandedSection === 'conversation';
  const memoryExpanded = expandedSection === 'memory';
  const sessionMenuSession = sessionMenu ? sessionsById[sessionMenu.sessionId] : null;

  const primaryButtonClass = (active: boolean) => cn(
    'flex w-full items-center gap-3 rounded-[20px] border px-3.5 py-3 text-left transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35',
    active
      ? 'border-primary/15 bg-primary/[0.08] text-foreground shadow-[0_10px_24px_rgba(109,92,77,0.08)]'
      : 'border-transparent text-muted-foreground hover:border-border/35 hover:bg-background/70 hover:text-foreground'
  );

  const iconWrapClass = (active: boolean) => cn(
    'flex h-9 w-9 shrink-0 items-center justify-center rounded-[14px] border transition-colors duration-200',
    active
      ? 'border-primary/16 bg-background/88 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.6)]'
      : 'border-border/28 bg-background/78 text-muted-foreground'
  );

  const nestedRailClass = 'mt-3 ml-4 flex flex-col gap-2 border-l border-border/55 pl-3';

  const secondaryButtonClass = (active: boolean) => cn(
    'flex w-full items-center gap-2 rounded-r-2xl border-l-2 border-transparent px-3 py-2.5 text-left text-sm transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30',
    active
      ? 'border-primary/60 bg-primary/[0.08] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.32)]'
      : 'text-muted-foreground hover:border-border/60 hover:bg-background/72 hover:text-foreground'
  );

  const toolButtonClass =
    'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/18 bg-background/78 text-muted-foreground shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition-all duration-200 ease-out hover:border-border/38 hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35';

  return (
    <aside
      className="relative flex h-full min-h-0 flex-col overflow-hidden border-r border-border/18 bg-card/45 pt-7"
    >
      {sessionMenu && sessionMenuSession ? (
        <div
          ref={sessionMenuRef}
          className="fixed z-[90] min-w-[160px] rounded-xl border border-border/70 bg-card/95 p-1.5 shadow-lg backdrop-blur-md"
          style={{ left: sessionMenu.x, top: sessionMenu.y }}
        >
          <button
            type="button"
            onClick={() => {
              setRenameTargetSession(sessionMenuSession);
              setRenameValue(getSessionDisplayLabel(sessionMenuSession, t('shell.newChatTitle')));
              setSessionMenu(null);
            }}
            className="flex w-full items-center rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
          >
            {t('shell.renameSession')}
          </button>
          <button
            type="button"
            onClick={() => {
              setDeleteTargetSession(sessionMenuSession);
              setSessionMenu(null);
            }}
            className="flex w-full items-center rounded-lg px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10"
          >
            {t('shell.deleteSession')}
          </button>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col px-3 py-3">
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
                  className="flex items-center gap-1.5"
                  data-testid="sidebar-conversation-tools"
                >
                  <div className="flex min-w-0 flex-1 items-center rounded-xl border border-border/18 bg-background/84 px-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.45)]">
                    <input
                      ref={conversationSearchInputRef}
                      type="search"
                      value={conversationSearch}
                      onChange={(event) => setConversationSearch(event.target.value)}
                      placeholder={t('shell.searchSessionsPlaceholder')}
                      aria-label={t('shell.searchSessions')}
                      className="h-9 w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground/85"
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
                    <div className="rounded-2xl border border-dashed border-border/40 bg-background/45 p-3 text-xs leading-5 text-muted-foreground">
                      {loading ? t('shell.loadingSessions') : t('shell.emptySessions')}
                    </div>
                  ) : filteredSessionRows.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-border/40 bg-background/45 p-3 text-xs leading-5 text-muted-foreground">
                      {t('shell.searchSessionsEmpty')}
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {filteredSessionRows.map((session) => {
                        const active = currentSessionId === session.session_id;
                        const unreadCount = unreadBySession[session.session_id] || 0;
                        const displayLabel = getSessionDisplayLabel(session, t('shell.newChatTitle'));
                        return (
                          <div
                            key={session.session_id}
                            className={cn(
                              'group/session flex items-center gap-1 rounded-r-2xl border-l-2 border-transparent transition-all duration-200 ease-out',
                              active
                                ? 'border-primary/60 bg-primary/[0.08] text-foreground'
                                : 'text-muted-foreground hover:border-border/60 hover:bg-background/72 hover:text-foreground'
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
                              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
                              title={displayLabel}
                            >
                              <span className="min-w-0 flex-1 truncate font-medium">{displayLabel}</span>
                              {unreadCount > 0 ? (
                                <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-primary/85 px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground">
                                  {Math.min(unreadCount, 99)}
                                </span>
                              ) : null}
                              <span className="shrink-0 text-[11px] text-muted-foreground/80">
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
                                'mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-transparent text-muted-foreground opacity-0 transition-all duration-200 ease-out focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 group-hover/session:opacity-100',
                                active
                                  ? 'hover:bg-primary/10 hover:text-primary'
                                  : 'hover:bg-background hover:text-foreground'
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
                  {MEMORY_DESTINATIONS.map((item) => {
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

        <div className="shrink-0 pt-4">
          <div className="mb-3 h-px bg-border/45" />
          <button
            type="button"
            onClick={() => {
              setActivePanel('settings');
              navigate('/settings');
            }}
            aria-label={t('shell.settings')}
            aria-current={settingsActive ? 'page' : undefined}
            className={primaryButtonClass(settingsActive)}
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
              className="h-11 w-full rounded-xl border border-border/55 bg-background px-3 text-sm outline-none transition-colors focus:border-primary/40"
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
