import { useCallback, useEffect, useMemo, useState } from 'react';
import { Database, MessageSquarePlus, ScrollText, Settings2, UserRound } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { messagesApi, type ChatSessionListItem } from '@/api';
import { useChatShellStore, useConversationStore } from '@/stores';

const USER_ID = 'web_user';
const SESSION_EVENT = 'magi-session-sync';

interface SidebarProps {
  collapsed?: boolean;
}

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

export default function Sidebar({ collapsed = false }: SidebarProps) {
  const { t, i18n } = useTranslation('app');
  const navigate = useNavigate();
  const location = useLocation();
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
  const orderedSessionIds = useConversationStore((state) => state.orderedSessionIds);
  const sessionsById = useConversationStore((state) => state.sessionsById);
  const hydrateSessions = useConversationStore((state) => state.hydrateSessions);
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);

  const [loading, setLoading] = useState(false);

  const refreshSessions = useCallback(async () => {
    setLoading(true);
    try {
      const response = await messagesApi.listSessions(USER_ID, 50);
      hydrateSessions(response.sessions || [], response.current_session_id);
    } catch {
      hydrateSessions([], currentSessionId);
    } finally {
      setLoading(false);
    }
  }, [currentSessionId, hydrateSessions]);

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

  const handleCreateSession = async () => {
    try {
      const result = await messagesApi.createNewSession(USER_ID);
      if (result.session_id) {
        setCurrentSessionId(result.session_id);
        navigate('/chat');
        window.dispatchEvent(new Event(SESSION_EVENT));
      }
    } catch {
      // ignore at shell level, chat page will surface failure details
    }
  };

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

  const utilityActions = [
    {
      id: 'personality' as const,
      label: t('shell.personality'),
      icon: UserRound,
      path: '/personality',
    },
    {
      id: 'timeline' as const,
      label: t('shell.timeline'),
      icon: ScrollText,
      path: '/timeline',
    },
    {
      id: 'memory' as const,
      label: t('shell.memory'),
      icon: Database,
      path: '/events',
    },
    {
      id: 'settings' as const,
      label: t('shell.settings'),
      icon: Settings2,
      path: '/settings',
    },
  ];

  const handleOpenPanel = (panel: 'personality' | 'memory' | 'settings' | 'timeline', path: string) => {
    setActivePanel(panel);
    navigate(path);
  };

  if (collapsed) {
    return null;
  }

  return (
    <aside
      className="relative flex h-full min-h-0 flex-col overflow-hidden border-r border-border/18 bg-card/30 pt-[4.25rem]"
    >
      <div className="px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-medium text-muted-foreground/85">
            {t('nav.chat')}
          </div>
          <button
            type="button"
            onClick={() => {
              void handleCreateSession();
            }}
            className="flex h-8 w-8 items-center justify-center rounded-xl border border-transparent text-muted-foreground transition-colors hover:border-border/24 hover:bg-muted/50 hover:text-foreground"
            aria-label={t('shell.newChat')}
            title={t('shell.newChat')}
          >
            <MessageSquarePlus className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        {sessionRows.length === 0 && (
          <div className="rounded-xl border border-dashed border-border/40 p-3 text-xs text-muted-foreground">
            {loading ? t('shell.loadingSessions') : t('shell.emptySessions')}
          </div>
        )}

        <div className="space-y-2">
          {sessionRows.map((session) => {
            const active = currentSessionId === session.session_id;
            return (
              <button
                key={session.session_id}
                type="button"
                onClick={() => {
                  setCurrentSessionId(session.session_id);
                  navigate('/chat');
                }}
                aria-label={session.title || t('shell.newChatTitle')}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'w-full rounded-2xl px-3 py-2.5 text-left transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                  active
                    ? 'border border-primary/16 bg-primary/12 text-foreground'
                    : 'border border-transparent hover:bg-muted/50'
                )}
                title={session.title}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{session.title || t('shell.newChatTitle')}</span>
                  <span className="shrink-0 text-[11px] text-muted-foreground">
                    {formatSessionTime(session.last_timestamp, i18n.language)}
                  </span>
                </div>
                <div className="mt-1 truncate text-xs text-muted-foreground">
                  {session.last_message_preview || t('shell.noPreview')}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="shrink-0 px-3 py-3">
        <div className="grid gap-2">
          {utilityActions.map((action) => {
            const Icon = action.icon;
            const active =
              activePanel === action.id ||
              location.pathname === action.path;
            return (
              <button
                key={action.id}
                type="button"
                onClick={() => handleOpenPanel(action.id, action.path)}
                aria-label={action.label}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex w-full items-center gap-3 rounded-2xl border px-3 py-2.5 text-left transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                  active
                    ? 'border-primary/16 bg-primary/10 text-foreground'
                    : 'border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                )}
              >
                <span className={cn(
                  'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border',
                  active
                    ? 'border-primary/14 bg-primary/12 text-primary'
                    : 'border-border/30 bg-background/60'
                )}>
                  <Icon className="h-4 w-4" />
                </span>
                <span className="text-sm font-medium">{action.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
