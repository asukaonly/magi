import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Database,
  MessageSquare,
  Plus,
  Search,
  ScrollText,
  Settings2,
} from 'lucide-react';
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

  const handleCreateSession = async () => {
    try {
      const result = await messagesApi.createNewSession(USER_ID);
      if (result.session_id) {
        setCurrentSessionId(result.session_id);
        setActivePanel('conversation');
        setExpandedSection('conversation');
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

  const filteredSessionRows = useMemo(() => {
    const normalizedQuery = conversationSearch.trim().toLowerCase();
    if (!normalizedQuery) {
      return sessionRows;
    }
    return sessionRows.filter((session) => {
      const haystack = `${session.title || ''} ${session.last_message_preview || ''}`.toLowerCase();
      return haystack.includes(normalizedQuery);
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

  const primaryButtonClass = (active: boolean) => cn(
    'flex w-full items-center gap-3 rounded-2xl border px-3 py-2.5 text-left transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
    active
      ? 'border-primary/16 bg-primary/10 text-foreground'
      : 'border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground'
  );

  const iconWrapClass = (active: boolean) => cn(
    'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border',
    active
      ? 'border-primary/14 bg-primary/12 text-primary'
      : 'border-border/30 bg-background/60'
  );

  return (
    <aside
      className="relative flex h-full min-h-0 flex-col overflow-hidden border-r border-border/18 bg-card/30 pt-14"
    >
      <div className="flex min-h-0 flex-1 flex-col px-3 py-3">
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          <section className={cn('shrink-0', conversationExpanded && 'flex min-h-0 flex-1 flex-col')}>
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
              <div className="mt-2 flex min-h-0 flex-1 flex-col gap-2">
                <div className="flex items-center gap-2">
                  <div className="flex min-w-0 flex-1 items-center rounded-2xl border border-border/25 bg-background/75 px-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                    <input
                      ref={conversationSearchInputRef}
                      type="search"
                      value={conversationSearch}
                      onChange={(event) => setConversationSearch(event.target.value)}
                      placeholder={t('shell.searchSessionsPlaceholder')}
                      aria-label={t('shell.searchSessions')}
                      className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      conversationSearchInputRef.current?.focus();
                      conversationSearchInputRef.current?.select();
                    }}
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-border/25 bg-background/70 text-muted-foreground transition-colors hover:border-border/45 hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    aria-label={t('shell.searchSessionsAction')}
                    title={t('shell.searchSessionsAction')}
                  >
                    <Search className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleCreateSession();
                    }}
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-border/25 bg-background/70 text-muted-foreground transition-colors hover:border-border/45 hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    aria-label={t('shell.newChat')}
                    title={t('shell.newChat')}
                  >
                    <Plus className="h-4 w-4" />
                  </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                  {sessionRows.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-border/40 p-3 text-xs text-muted-foreground">
                      {loading ? t('shell.loadingSessions') : t('shell.emptySessions')}
                    </div>
                  ) : filteredSessionRows.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-border/40 p-3 text-xs text-muted-foreground">
                      {t('shell.searchSessionsEmpty')}
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {filteredSessionRows.map((session) => {
                        const active = currentSessionId === session.session_id;
                        const unreadCount = unreadBySession[session.session_id] || 0;
                        return (
                          <button
                            key={session.session_id}
                            type="button"
                            onClick={() => {
                              setCurrentSessionId(session.session_id);
                              setActivePanel('conversation');
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
                              <span className="min-w-0 truncate text-sm font-medium">
                                {session.title || t('shell.newChatTitle')}
                              </span>
                              <div className="flex shrink-0 items-center gap-2">
                                {unreadCount > 0 ? (
                                  <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[11px] font-medium text-primary-foreground">
                                    {Math.min(unreadCount, 99)}
                                  </span>
                                ) : null}
                                <span className="text-[11px] text-muted-foreground">
                                  {formatSessionTime(session.last_timestamp, i18n.language)}
                                </span>
                              </div>
                            </div>
                            <div className="mt-1 truncate text-xs text-muted-foreground">
                              {session.last_message_preview || t('shell.noPreview')}
                            </div>
                          </button>
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
              <div className="mt-2 min-h-0 flex-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                <div className="space-y-1 pl-3">
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
                        className={cn(
                          'flex w-full items-center rounded-xl px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35',
                          destinationActive
                            ? 'bg-primary/10 text-primary'
                            : 'text-muted-foreground hover:bg-muted/45 hover:text-foreground'
                        )}
                      >
                        {t(`memory.nav.${item.key}`)}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </section>
        </div>

        <div className="shrink-0 pt-3">
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
    </aside>
  );
}
