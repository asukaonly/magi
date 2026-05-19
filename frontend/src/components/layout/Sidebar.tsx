import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Activity,
  Brain,
  ListChecks,
  MessageCircle,
  MoreHorizontal,
  Settings,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { messagesApi, type ChatSessionListItem } from '@/api';
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
import { useChatShellStore, useConversationStore, type ChatPanelType } from '@/stores';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { formatChatClockTime } from '@/domain/chat/timestamps';
import { PersonaHeader } from './PersonaHeader';
import { MoodCalendar } from '@/components/timeline/immersive/sidebar/MoodCalendar';
import { StandoutList } from '@/components/timeline/immersive/sidebar/StandoutList';

const USER_ID = DEFAULT_USER_ID;
const SESSION_EVENT = 'magi-session-sync';

interface SidebarProps {
  collapsed?: boolean;
}

type ActivityPanel = Exclude<ChatPanelType, 'none'>;

const MEMORY_DESTINATIONS = [
  { key: 'overview', path: '/memory/overview' },
  { key: 'workbench', path: '/memory/workbench' },
  { key: 'events', path: '/memory/events' },
  { key: 'knowledge', path: '/memory/knowledge' },
  { key: 'reflection', path: '/memory/reflection' },
  { key: 'skills', path: '/memory/skills' },
] as const;

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
  const timelinePanel = useChatShellStore((state) => state.timelinePanel);

  const [loading, setLoading] = useState(false);
  const isConversationRoute = location.pathname === '/' || location.pathname === '/chat';
  const isMemoryRoute = location.pathname === '/events' || location.pathname.startsWith('/memory');
  const shouldRefreshSessions = isConversationRoute;
  const [openPanel, setOpenPanel] = useState<ActivityPanel | null>(null);
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
        setOpenPanel('conversation');
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
      setOpenPanel('conversation');
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

  const tasksActiveCount = useBackgroundTaskStore((state) => state.activeCount);

  if (collapsed) {
    return null;
  }

  const conversationActive = activePanel === 'conversation' || isConversationRoute;
  const timelineActive = activePanel === 'timeline' || location.pathname === '/timeline';
  const memoryActive = activePanel === 'memory' || isMemoryRoute;
  const settingsActive = activePanel === 'settings';
  const tasksActive = activePanel === 'tasks' || location.pathname === '/tasks';
  const sessionMenuSession = sessionMenu ? sessionsById[sessionMenu.sessionId] : null;

  const panelNavButtonClass = (active: boolean) => cn(
    'relative flex h-8 w-full items-center gap-2 rounded-[5px] px-2.5 text-left text-[13px] transition-colors duration-150 ease-out before:pointer-events-none before:absolute before:bottom-1.5 before:left-0 before:top-1.5 before:w-[2px] before:rounded-full before:bg-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]',
    active
      ? 'bg-[hsl(var(--sidebar-active)/0.32)] text-[hsl(var(--sidebar-active-foreground))] before:bg-[hsl(var(--primary))]'
      : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover)/0.62)] hover:text-[hsl(var(--sidebar-active-foreground))]'
  );

  const activityButtonClass = (active: boolean, open: boolean) => cn(
    'relative flex h-11 w-11 items-center justify-center rounded-md text-[hsl(var(--sidebar-muted))] transition-colors duration-150 ease-out before:pointer-events-none before:absolute before:bottom-2 before:left-[-6px] before:top-2 before:w-[2px] before:rounded-full before:bg-transparent hover:bg-[hsl(var(--sidebar-hover)/0.58)] hover:text-[hsl(var(--sidebar-active-foreground))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.2)]',
    active && 'text-[hsl(var(--sidebar-active-foreground))] before:bg-[hsl(var(--primary))]',
    open && 'bg-[hsl(var(--sidebar-active)/0.34)]'
  );

  const handleActivityClick = (panel: ActivityPanel) => {
    if (panel === 'settings') {
      clearSettingsNavigationIntent();
      setActivePanel('settings');
      return;
    }

    if (openPanel === panel) {
      setOpenPanel(null);
      return;
    }

    setOpenPanel(panel);

    if (panel === 'conversation') {
      setActivePanel('conversation');
      if (!isConversationRoute) {
        navigate('/chat');
      }
      return;
    }

    if (panel === 'timeline') {
      setActivePanel('timeline');
      if (location.pathname !== '/timeline') {
        navigate('/timeline');
      }
      return;
    }

    if (panel === 'memory') {
      setActivePanel('memory');
      if (!isMemoryRoute) {
        navigate('/memory/overview');
      }
      return;
    }

    if (panel === 'tasks') {
      setActivePanel('tasks');
      if (location.pathname !== '/tasks') {
        navigate('/tasks');
      }
      return;
    }
  };

  const renderActivityButton = (
    panel: ActivityPanel,
    label: string,
    icon: ReactNode,
    active: boolean,
    badgeCount?: number,
  ) => {
    const open = openPanel === panel;
    return (
      <button
        type="button"
        onClick={() => handleActivityClick(panel)}
        aria-label={label}
        aria-current={active ? 'page' : undefined}
        aria-expanded={open}
        title={label}
        className={activityButtonClass(active, open)}
      >
        {icon}
        {typeof badgeCount === 'number' && badgeCount > 0 ? (
          <span className="absolute right-1 top-1 inline-flex min-w-4 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1 text-[9px] font-medium leading-4 text-[hsl(var(--sidebar-badge-foreground))]">
            {Math.min(badgeCount, 99)}
          </span>
        ) : null}
      </button>
    );
  };

  const renderConversationPanel = () => (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="sidebar-conversation-rail">
      <PersonaHeader onCreateChat={() => { void handleCreateSession(); }} />

      <div className="flex min-h-0 flex-1 flex-col px-2.5 py-2.5">
        <div className="min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          {sessionRows.length === 0 ? (
            <div className="rounded-md bg-[hsl(var(--sidebar-tool))] px-3 py-2.5 text-xs leading-5 text-[hsl(var(--sidebar-muted))]">
              {loading ? t('shell.loadingSessions') : t('shell.emptySessions')}
            </div>
          ) : (
            <div className="space-y-0.5">
              {sessionRows.map((session) => {
                const active = currentSessionId === session.session_id;
                const unreadCount = unreadBySession[session.session_id] || 0;
                const displayLabel = getSessionDisplayLabel(session, t('shell.newChatTitle'));
                return (
                  <div
                    key={session.session_id}
                    className={cn(
                      'group/session relative flex h-8 items-center gap-1 rounded-[5px] transition-colors duration-150 ease-out before:pointer-events-none before:absolute before:bottom-1.5 before:left-0 before:top-1.5 before:w-[2px] before:rounded-full before:bg-transparent',
                      active
                        ? 'bg-[hsl(var(--sidebar-active)/0.32)] text-[hsl(var(--sidebar-active-foreground))] before:bg-[hsl(var(--primary))]'
                        : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover)/0.62)] hover:text-[hsl(var(--sidebar-active-foreground))]'
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
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-[5px] px-2 text-left text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]"
                      title={displayLabel}
                    >
                      <span className="min-w-0 flex-1 truncate font-medium">{displayLabel}</span>
                      {unreadCount > 0 ? (
                        <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1.5 py-0.5 text-[10px] font-medium text-[hsl(var(--sidebar-badge-foreground))]">
                          {Math.min(unreadCount, 99)}
                        </span>
                      ) : null}
                      <span className="shrink-0 text-[10px] text-[hsl(var(--sidebar-muted))]">
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
    </div>
  );

  const renderMemoryPanel = () => (
    <div
      className="flex min-h-0 flex-1 flex-col pt-2"
      data-testid="sidebar-memory-panel"
    >
      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 py-2.5 pr-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        <div className="space-y-0.5">
          {MEMORY_DESTINATIONS.map((item) => {
            const destinationActive =
              location.pathname === item.path ||
              (item.path === '/memory/overview' && location.pathname === '/events');
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => {
                  setActivePanel('memory');
                  navigate(item.path);
                }}
                aria-label={t(`memory.nav.${item.key}`)}
                aria-current={destinationActive ? 'page' : undefined}
                className={panelNavButtonClass(destinationActive)}
              >
                <span className="min-w-0 flex-1 truncate font-medium">
                  {t(`memory.nav.${item.key}`)}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );

  const renderTimelinePanel = () => (
    <div
      className="flex min-h-0 flex-1 flex-col pt-2"
      data-testid="sidebar-timeline-panel"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <MoodCalendar
          month={timelinePanel.monthForCalendar}
          days={timelinePanel.moodDays}
          selectedDate={timelinePanel.selectedDate}
          onSelectDate={(d) => timelinePanel.onSelectDate?.(d)}
        />
        <StandoutList
          items={timelinePanel.standoutItems}
          onSelectEpisode={(id) => timelinePanel.onSelectStandoutEpisode?.(id)}
        />
      </div>
    </div>
  );

  const renderPanelContent = () => {
    if (openPanel === 'conversation') {
      return renderConversationPanel();
    }

    if (openPanel === 'memory') {
      return renderMemoryPanel();
    }

    if (openPanel === 'timeline') {
      return renderTimelinePanel();
    }

    if (!openPanel) {
      return null;
    }

    return (
      <div
        className="flex min-h-0 flex-1 flex-col pt-2"
        data-testid={`sidebar-${openPanel}-panel`}
      >
        <div className="min-h-0 flex-1" />
      </div>
    );
  };

  return (
    <aside
      className={cn(
        'relative flex h-full min-h-0 overflow-hidden border-r border-[hsl(var(--sidebar-border))] bg-[linear-gradient(180deg,hsl(var(--sidebar-background-start))_0%,hsl(var(--sidebar-background-end))_100%)] transition-[width] duration-150 ease-out',
        openPanel ? 'w-[284px]' : 'w-14'
      )}
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
      <div
        className="flex w-14 shrink-0 flex-col border-r border-[hsl(var(--sidebar-border))] px-1.5 pb-3 pt-3"
        data-testid="sidebar-activity-bar"
      >
        <div className="flex min-h-0 flex-1 flex-col items-center gap-1">
          {renderActivityButton(
            'conversation',
            t('shell.conversation'),
            <MessageCircle className="h-[18px] w-[18px]" />,
            conversationActive,
          )}
          {renderActivityButton(
            'timeline',
            t('shell.timeline'),
            <Activity className="h-[18px] w-[18px]" />,
            timelineActive,
          )}
          {renderActivityButton(
            'memory',
            t('shell.memory'),
            <Brain className="h-[18px] w-[18px]" />,
            memoryActive,
          )}
        </div>

        <div className="flex shrink-0 flex-col items-center gap-1">
          {renderActivityButton(
            'tasks',
            t('shell.tasks'),
            <ListChecks className="h-[18px] w-[18px]" />,
            tasksActive,
            tasksActiveCount,
          )}
          {renderActivityButton(
            'settings',
            t('shell.settings'),
            <Settings className="h-[18px] w-[18px]" />,
            settingsActive,
          )}
        </div>
      </div>

      {openPanel ? (
        <div className="flex min-h-0 w-[228px] shrink-0 flex-col bg-[hsl(var(--sidebar-background-end)/0.72)]">
          {renderPanelContent()}
        </div>
      ) : null}

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
