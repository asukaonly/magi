import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { MessageSquarePlus } from 'lucide-react';
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
      className="desktop-panel flex h-full min-h-0 flex-col overflow-hidden border-r border-border/30"
    >
      <div className="shrink-0 border-b border-border/30 p-3">
        <Button
          onClick={handleCreateSession}
          className="w-full justify-start gap-2 rounded-xl border border-primary/20 bg-primary/15 text-primary hover:bg-primary/25"
        >
          <MessageSquarePlus className="h-4 w-4" />
          <span>{t('shell.newChat')}</span>
        </Button>
      </div>

      <div className="border-b border-border/20 px-4 py-3">
        <div className="text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground/70">
          {t('nav.chat')}
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
                className={cn(
                  'w-full rounded-xl border px-3 py-2 text-left transition-all duration-200',
                  active
                    ? 'border-primary/40 bg-primary/15 text-foreground shadow-[0_0_12px_rgba(45,212,191,0.15)]'
                    : 'border-transparent hover:border-border/40 hover:bg-white/5'
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
    </aside>
  );
};

export default Sidebar;
