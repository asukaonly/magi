import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Database,
  MessageSquarePlus,
  Settings2,
  Sparkles,
  UserRound,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { messagesApi, type ChatSessionListItem } from '@/api';
import { useChatShellStore } from '@/stores';

const USER_ID = 'web_user';
const SESSION_EVENT = 'magi-session-sync';

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

const Sidebar: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const navigate = useNavigate();
  const currentSessionId = useChatShellStore((state) => state.currentSessionId);
  const setCurrentSessionId = useChatShellStore((state) => state.setCurrentSessionId);
  const sidebarCollapsed = useChatShellStore((state) => state.sidebarCollapsed);
  const toggleSidebarCollapsed = useChatShellStore((state) => state.toggleSidebarCollapsed);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);

  const [sessions, setSessions] = useState<ChatSessionListItem[]>([]);
  const [loading, setLoading] = useState(false);

  const refreshSessions = useCallback(async () => {
    setLoading(true);
    try {
      const response = await messagesApi.listSessions(USER_ID, 50);
      setSessions(response.sessions || []);
      if (!currentSessionId && response.current_session_id) {
        setCurrentSessionId(response.current_session_id);
      }
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, [currentSessionId, setCurrentSessionId]);

  useEffect(() => {
    void refreshSessions();
    const timer = window.setInterval(() => {
      void refreshSessions();
    }, 8000);
    const handleSync = () => {
      void refreshSessions();
    };
    window.addEventListener(SESSION_EVENT, handleSync as EventListener);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener(SESSION_EVENT, handleSync as EventListener);
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

  const handleOpenPanel = (panel: 'settings' | 'personality' | 'memory') => {
    setActivePanel(panel);
    if (panel === 'settings') {
      navigate('/settings');
      return;
    }
    if (panel === 'personality') {
      navigate('/personality');
      return;
    }
    navigate('/events');
  };

  const sessionRows = useMemo(() => {
    if (sessions.length > 0) {
      return sessions;
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
  }, [currentSessionId, sessions, t]);

  return (
    <aside
      className={cn(
        'desktop-panel flex h-full min-h-0 flex-col overflow-hidden border-r border-border/30 transition-all duration-200',
        sidebarCollapsed ? 'w-[72px]' : 'w-[280px]'
      )}
    >
      <div className={cn('shrink-0 flex items-center border-b border-border/30 px-3 py-3', sidebarCollapsed ? 'justify-center' : 'justify-between')}>
        {!sidebarCollapsed && (
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/20 text-primary eva-glow">
              <Sparkles className="h-4 w-4" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-medium text-foreground/90">Magi</div>
              <div className="text-[11px] text-muted-foreground">{t('shell.clientMode')}</div>
            </div>
          </div>
        )}
        <Button
          size="icon"
          variant="ghost"
          onClick={toggleSidebarCollapsed}
          className="h-8 w-8 rounded-lg text-foreground/60 hover:text-foreground hover:bg-white/5"
        >
          {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </div>

      <div className="shrink-0 p-2">
        <Button
          onClick={handleCreateSession}
          className="w-full justify-start gap-2 rounded-xl bg-primary/15 text-primary border border-primary/20 hover:bg-primary/25"
        >
          <MessageSquarePlus className="h-4 w-4" />
          {!sidebarCollapsed && <span>{t('shell.newChat')}</span>}
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        {!sidebarCollapsed && sessionRows.length === 0 && (
          <div className="rounded-xl border border-dashed border-border/40 p-3 text-xs text-muted-foreground">
            {loading ? t('shell.loadingSessions') : t('shell.emptySessions')}
          </div>
        )}

        <div className="space-y-1">
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
                className={cn(
                  'w-full rounded-xl border px-3 py-2 text-left transition-all duration-200',
                  active
                    ? 'border-primary/40 bg-primary/15 text-foreground shadow-[0_0_12px_rgba(45,212,191,0.15)]'
                    : 'border-transparent hover:border-border/40 hover:bg-white/5',
                  sidebarCollapsed && 'flex justify-center px-2'
                )}
                title={session.title}
              >
                {sidebarCollapsed ? (
                  <span className="text-xs font-medium">{session.title.slice(0, 1)}</span>
                ) : (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{session.title || t('shell.newChatTitle')}</span>
                      <span className="shrink-0 text-[11px] text-muted-foreground">
                        {formatSessionTime(session.last_timestamp, i18n.language)}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      {session.last_message_preview || t('shell.noPreview')}
                    </div>
                  </>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="shrink-0 border-t border-border/30 p-2">
        <div className="space-y-1">
          <Button
            variant="ghost"
            className="w-full justify-start gap-2 rounded-xl text-foreground/60 hover:text-foreground hover:bg-white/5"
            onClick={() => handleOpenPanel('personality')}
          >
            <UserRound className="h-4 w-4" />
            {!sidebarCollapsed && <span>{t('shell.personality')}</span>}
          </Button>
          <Button
            variant="ghost"
            className="w-full justify-start gap-2 rounded-xl text-foreground/60 hover:text-foreground hover:bg-white/5"
            onClick={() => handleOpenPanel('memory')}
          >
            <Database className="h-4 w-4" />
            {!sidebarCollapsed && <span>{t('shell.memory')}</span>}
          </Button>
          <Button
            variant="ghost"
            className="w-full justify-start gap-2 rounded-xl text-foreground/60 hover:text-foreground hover:bg-white/5"
            onClick={() => handleOpenPanel('settings')}
          >
            <Settings2 className="h-4 w-4" />
            {!sidebarCollapsed && <span>{t('shell.settings')}</span>}
          </Button>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
