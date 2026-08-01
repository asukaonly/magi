import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Activity,
  Brain,
  BookOpen,
  CalendarClock,
  Database,
  History,
  Inbox,
  LayoutDashboard,
  ListChecks,
  MessageCircle,
  Search,
  Settings,
  SlidersHorizontal,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import {
  captureBrowserContentGeneration,
  isBrowserContentGenerationCurrent,
} from '@/lib/browserContentGeneration';
import { messagesApi, type ChatSessionListItem } from '@/api';
import { CHAT_SESSION_KEY, DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { completeChatSessionDeletion } from '@/hooks/chatRetryLifecycle';
import {
  activateRealtimeChatSession,
  activateRealtimeChatSessions,
} from '@/realtime/chat-projection-retirement';
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
import { useNotificationStore } from '@/stores/notifications';
import { useSchedulesStore } from '@/stores/schedules';
import { formatChatClockTime } from '@/domain/chat/timestamps';
import { PersonaHeader } from './PersonaHeader';
import { MoodCalendar } from '@/components/timeline/immersive/sidebar/MoodCalendar';
import { StandoutList } from '@/components/timeline/immersive/sidebar/StandoutList';

const USER_ID = DEFAULT_USER_ID;
interface SidebarProps {
  collapsed?: boolean;
}

type ActivityPanel = Exclude<ChatPanelType, 'none'>;

const MEMORY_DESTINATIONS = [
  { key: 'overview', path: '/memory/overview', icon: LayoutDashboard },
  { key: 'sources', path: '/memory/sources', icon: Database },
  { key: 'portrait', path: '/memory/portrait', icon: UserRound },
  { key: 'pending', path: '/memory/pending', icon: Inbox },
  { key: 'stories', path: '/memory/stories', icon: History },
  { key: 'episodes', path: '/memory/episodes', icon: BookOpen },
  { key: 'recall', path: '/memory/recall', icon: Search },
  { key: 'governance', path: '/memory/governance', icon: SlidersHorizontal },
] as const satisfies readonly { key: string; path: string; icon: LucideIcon }[];

const TASKS_DESTINATIONS = [
  { key: 'background', path: '/tasks/background', icon: ListChecks },
  { key: 'schedules', path: '/tasks/schedules', icon: CalendarClock },
  { key: 'activity', path: '/tasks/schedules/activity', icon: History },
] as const;

const isOpenProfileConflictNotification = (
  item: ReturnType<typeof useNotificationStore.getState>['items'][number],
): boolean => (
  item.payload?.conflict_type === 'profile_conflict' &&
  (item.status === 'unread' || item.status === 'read')
);

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
  const pendingMemoryConflictCount = useNotificationStore((state) => (
    state.items.filter(isOpenProfileConflictNotification).length
  ));

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
  const refreshRequestIdRef = useRef(0);
  const sessionCreationPromiseRef = useRef<Promise<string | null> | null>(null);

  const refreshSessions = useCallback(async (preferredSessionId?: string | null) => {
    const contentGeneration = captureBrowserContentGeneration();
    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;
    const requestIsCurrent = () => (
      refreshRequestIdRef.current === requestId
      && isBrowserContentGenerationCurrent(contentGeneration)
    );
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
        if (!requestIsCurrent()) {
          return;
        }
        const sessions = response.sessions || [];
        if (sessions.length === 0 && allowCreate) {
          if (!sessionCreationPromiseRef.current) {
            sessionCreationPromiseRef.current = messagesApi.createNewSession(USER_ID)
              .then((created) => String(created.session_id || '').trim() || null)
              .finally(() => {
                sessionCreationPromiseRef.current = null;
              });
          }
          const createdSessionId = await sessionCreationPromiseRef.current;
          if (!requestIsCurrent()) {
            return;
          }
          if (createdSessionId) {
            activateRealtimeChatSession(createdSessionId);
            persistSessionId(createdSessionId);
            await loadSessions(false, createdSessionId);
            return;
          }
        }
        if (!requestIsCurrent()) {
          return;
        }
        const sessionIds = sessions.map((session) => session.session_id);
        activateRealtimeChatSessions(sessionIds);
        const latestSessionId = useConversationStore.getState().currentSessionId;
        const persistedSessionId = readPersistedSessionId();
        const nextSessionId = (
          (requestedSessionId && sessionIds.includes(requestedSessionId) ? requestedSessionId : null)
          || (latestSessionId && sessionIds.includes(latestSessionId) ? latestSessionId : null)
          || (persistedSessionId && sessionIds.includes(persistedSessionId) ? persistedSessionId : null)
          || sessionIds[0]
          || null
        );
        hydrateSessions(sessions, nextSessionId);
        setCurrentSessionId(nextSessionId);
        persistSessionId(nextSessionId);
      };

      await loadSessions(true);
    } catch {
      if (requestIsCurrent()) {
        hydrateSessions([], useConversationStore.getState().currentSessionId);
      }
    } finally {
      if (refreshRequestIdRef.current === requestId) {
        setLoading(false);
      }
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
    window.addEventListener(APP_EVENTS.SESSION_SYNC, handleSync as EventListener);
    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      refreshRequestIdRef.current += 1;
      window.removeEventListener(APP_EVENTS.SESSION_SYNC, handleSync as EventListener);
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
    const contentGeneration = captureBrowserContentGeneration();
    const operationIsCurrent = () => (
      isBrowserContentGenerationCurrent(contentGeneration)
    );
    try {
      const result = await messagesApi.createNewSession(USER_ID);
      if (!operationIsCurrent()) {
        return;
      }
      if (result.session_id) {
        activateRealtimeChatSession(result.session_id);
        window.localStorage.setItem(CHAT_SESSION_KEY(USER_ID), result.session_id);
        await refreshSessions(result.session_id);
        if (!operationIsCurrent()) {
          return;
        }
        setActivePanel('conversation');
        setOpenPanel('conversation');
        navigate('/chat');
      }
    } catch {
      // Ignore at shell level; the chat page surfaces send/create failures.
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
    const contentGeneration = captureBrowserContentGeneration();
    const operationIsCurrent = () => (
      isBrowserContentGenerationCurrent(contentGeneration)
    );
    setActionPending(true);
    try {
      await messagesApi.renameSession(USER_ID, renameTargetSession.session_id, nextTitle);
      if (!operationIsCurrent()) {
        return;
      }
      await refreshSessions();
      if (!operationIsCurrent()) {
        return;
      }
      setRenameTargetSession(null);
    } finally {
      setActionPending(false);
    }
  }, [refreshSessions, renameTargetSession, renameValue]);

  const handleDeleteSession = useCallback(async () => {
    if (!deleteTargetSession) {
      return;
    }
    const targetSessionId = deleteTargetSession.session_id;
    const contentGeneration = captureBrowserContentGeneration();
    const operationIsCurrent = () => (
      isBrowserContentGenerationCurrent(contentGeneration)
    );
    setActionPending(true);
    let deleteConfirmed = false;
    let cleanupPending = false;
    try {
      const result = await messagesApi.deleteSession(USER_ID, targetSessionId);
      if (!operationIsCurrent()) {
        setActionPending(false);
        return;
      }
      if (
        !result.success
        || String(result.deleted_session_id || '').trim() !== targetSessionId
      ) {
        throw new Error('Session delete request was not completed');
      }
      deleteConfirmed = true;
      cleanupPending = result.cleanup_pending;
    } catch {
      if (operationIsCurrent()) {
        toast.error(t('shell.deleteSessionFailed'));
      }
    }
    if (!operationIsCurrent()) {
      setActionPending(false);
      return;
    }
    if (!deleteConfirmed) {
      setActionPending(false);
      return;
    }

    const wasCurrentSession = (
      useConversationStore.getState().currentSessionId === targetSessionId
    );
    completeChatSessionDeletion(targetSessionId);
    if (cleanupPending) {
      toast.warning(t('shell.deleteSessionCleanupPending'));
    }
    if (wasCurrentSession) {
      setCurrentSessionId(null);
      try {
        window.localStorage.removeItem(CHAT_SESSION_KEY(USER_ID));
      } catch {
        // Keep the in-memory selection authoritative when persistence fails.
      }
    }
    setDeleteTargetSession(null);
    setOpenPanel('conversation');
    setActivePanel('conversation');
    navigate('/chat');
    try {
      await refreshSessions();
    } catch {
      // The deletion is already committed locally; the next sync can refresh
      // the remaining session list without misreporting the delete as failed.
    } finally {
      setActionPending(false);
    }
  }, [deleteTargetSession, navigate, refreshSessions, setActivePanel, setCurrentSessionId, t]);

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
  const totalConversationUnread = useMemo(
    () => Object.values(unreadBySession).reduce((total, count) => total + Math.max(0, Number(count) || 0), 0),
    [unreadBySession],
  );

  const tasksActiveCount = useBackgroundTaskStore((state) => state.activeCount);
  const runningSchedulesCount = useSchedulesStore((state) => state.runningCount);

  if (collapsed) {
    return null;
  }

  const conversationActive = activePanel === 'conversation' || isConversationRoute;
  const timelineActive = activePanel === 'timeline' || location.pathname === '/timeline';
  const memoryActive = activePanel === 'memory' || isMemoryRoute;
  const settingsActive = activePanel === 'settings';
  const tasksActive = activePanel === 'tasks' || location.pathname.startsWith('/tasks');
  const sessionMenuSession = sessionMenu ? sessionsById[sessionMenu.sessionId] : null;

  const panelNavButtonClass = (active: boolean) => cn(
    'relative flex h-9 w-full items-center gap-2 rounded-lg px-3 text-left text-[13px] transition-colors duration-150 ease-out before:pointer-events-none before:absolute before:bottom-2 before:left-0 before:top-2 before:w-[2px] before:rounded-full before:bg-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]',
    active
      ? 'bg-[hsl(var(--sidebar-active)/0.52)] text-[hsl(var(--sidebar-active-foreground))] before:bg-[hsl(var(--primary))]'
      : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover)/0.68)] hover:text-[hsl(var(--sidebar-active-foreground))]'
  );

  const memoryNavButtonClass = (active: boolean) => cn(
    'group/session relative flex h-9 w-full items-center gap-2 rounded-md px-3 text-left text-[13px] transition-colors duration-150 ease-out before:pointer-events-none before:absolute before:bottom-2 before:left-0 before:top-2 before:w-[2px] before:rounded-full before:bg-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]',
    active
      ? 'text-[hsl(var(--sidebar-active-foreground))] before:bg-[hsl(var(--primary)/0.78)]'
      : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover)/0.46)] hover:text-[hsl(var(--sidebar-active-foreground))]'
  );

  const activityButtonClass = (active: boolean, open: boolean) => cn(
    'relative flex h-11 w-11 items-center justify-center rounded-lg text-[hsl(var(--sidebar-muted))] transition-colors duration-150 ease-out before:pointer-events-none before:absolute before:bottom-2 before:left-[-6px] before:top-2 before:w-[2px] before:rounded-full before:bg-transparent hover:bg-[hsl(var(--sidebar-hover)/0.62)] hover:text-[hsl(var(--sidebar-active-foreground))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.2)]',
    active && 'text-[hsl(var(--sidebar-active-foreground))] before:bg-[hsl(var(--primary))]',
    open && 'bg-[hsl(var(--sidebar-active)/0.52)] shadow-[0_10px_24px_hsl(var(--sidebar-shadow)/0.06)]'
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
        data-testid={`tour-target-${panel}`}
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

      <div className="flex min-h-0 flex-1 flex-col px-3 py-3">
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
                      'group/session relative flex h-9 items-center rounded-md transition-colors duration-150 ease-out before:pointer-events-none before:absolute before:bottom-2 before:left-0 before:top-2 before:w-[2px] before:rounded-full before:bg-transparent',
                      active
                        ? 'text-[hsl(var(--sidebar-active-foreground))] before:bg-[hsl(var(--primary)/0.78)]'
                        : 'text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-hover)/0.46)] hover:text-[hsl(var(--sidebar-active-foreground))]'
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
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-3 text-left text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]"
                      title={displayLabel}
                    >
                      <span className={cn('min-w-0 flex-1 truncate', active ? 'font-semibold' : 'font-medium')}>
                        {displayLabel}
                      </span>
                      {unreadCount > 0 ? (
                        <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1.5 py-0.5 text-[10px] font-medium text-[hsl(var(--sidebar-badge-foreground))]">
                          {Math.min(unreadCount, 99)}
                        </span>
                      ) : null}
                      <span className="shrink-0 text-[11px] text-[hsl(var(--sidebar-muted))]">
                        {formatSessionTime(session.last_timestamp, i18n.language)}
                      </span>
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
            const Icon = item.icon;
            const destinationActive =
              location.pathname === item.path ||
              (item.path === '/memory/sources' && location.pathname.startsWith('/memory/sources/')) ||
              (item.path === '/memory/stories' && location.pathname === '/events');
            const pendingCount = item.key === 'pending' ? pendingMemoryConflictCount : 0;
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
                className={memoryNavButtonClass(destinationActive)}
              >
                <Icon
                  aria-hidden="true"
                  data-testid={`sidebar-memory-icon-${item.key}`}
                  className={cn(
                    'h-3.5 w-3.5 shrink-0 transition-colors duration-150',
                    destinationActive
                      ? 'text-[hsl(var(--sidebar-active-foreground))]'
                      : 'text-[hsl(var(--sidebar-muted))] group-hover/session:text-[hsl(var(--sidebar-active-foreground))]'
                  )}
                />
                <span className="min-w-0 flex-1 truncate font-medium">
                  {t(`memory.nav.${item.key}`)}
                </span>
                {pendingCount > 0 ? (
                  <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1.5 py-0.5 text-[10px] font-medium text-[hsl(var(--sidebar-badge-foreground))]">
                    {Math.min(pendingCount, 99)}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );

  const renderTasksPanel = () => {
    const activeMap: Record<string, boolean> = {
      background:
        location.pathname === '/tasks/background' || location.pathname === '/tasks',
      schedules:
        location.pathname === '/tasks/schedules' ||
        location.pathname === '/tasks/schedules/',
      activity: location.pathname === '/tasks/schedules/activity',
    };
    const badgeFor: Record<string, number> = {
      background: tasksActiveCount,
      schedules: 0,
      activity: runningSchedulesCount,
    };
    return (
      <div className="flex min-h-0 flex-1 flex-col pt-2" data-testid="sidebar-tasks-panel">
        <div className="min-h-0 flex-1 overflow-y-auto px-2.5 py-2.5 pr-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          <div className="space-y-0.5">
            {TASKS_DESTINATIONS.map(({ key, path, icon: Icon }) => {
              const active = activeMap[key];
              const badge = badgeFor[key];
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    setActivePanel('tasks');
                    navigate(path);
                  }}
                  aria-label={t(`shell.tasks.${key}`)}
                  aria-current={active ? 'page' : undefined}
                  className={panelNavButtonClass(active)}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {t(`shell.tasks.${key}`)}
                  </span>
                  {badge > 0 ? (
                    <span className="inline-flex min-w-4 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1 text-[9px] font-medium leading-4 text-[hsl(var(--sidebar-badge-foreground))]">
                      {Math.min(badge, 99)}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    );
  };

  const renderTimelinePanel = () => (
    <div
      className="flex min-h-0 flex-1 flex-col pt-2"
      data-testid="sidebar-timeline-panel"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <MoodCalendar
          month={timelinePanel.monthForCalendar}
          days={timelinePanel.moodDays}
          scale={timelinePanel.scale}
          selectedRangeStart={timelinePanel.selectedRangeStart}
          selectedRangeEnd={timelinePanel.selectedRangeEnd}
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
    if (openPanel === 'tasks') {
      return renderTasksPanel();
    }
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
        'relative flex h-full min-h-0 overflow-hidden bg-[hsl(var(--app-chrome-surface))] shadow-[inset_-1px_0_0_hsl(var(--app-chrome-divider)/0.46)] transition-[width] duration-150 ease-out',
        openPanel === 'memory' ? 'w-[248px]' : openPanel ? 'w-[284px]' : 'w-14'
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
        className="flex w-14 shrink-0 flex-col bg-[hsl(var(--app-chrome-surface))] px-1.5 pb-3 pt-3 shadow-[inset_-1px_0_0_hsl(var(--app-chrome-divider)/0.34)]"
        data-testid="sidebar-activity-bar"
      >
        <div className="flex min-h-0 flex-1 flex-col items-center gap-1">
          {renderActivityButton(
            'conversation',
            t('shell.conversation'),
            <MessageCircle className="h-[18px] w-[18px]" />,
            conversationActive,
            totalConversationUnread,
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
            t('shell.tasks.label'),
            <ListChecks className="h-[18px] w-[18px]" />,
            tasksActive,
            tasksActiveCount + runningSchedulesCount,
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
        <div
          className={cn(
            'flex min-h-0 shrink-0 flex-col bg-[hsl(var(--app-chrome-surface))]',
            openPanel === 'memory' ? 'w-[192px]' : 'w-[228px]'
          )}
        >
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
