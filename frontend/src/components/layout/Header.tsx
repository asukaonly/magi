import React, { useEffect, useState } from 'react';
import { Database, Settings2, Sparkles, UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useChatShellStore } from '@/stores';

const CONNECTION_EVENT = 'magi-chat-connection';

const Header: React.FC = () => {
  const { t } = useTranslation('app');
  const navigate = useNavigate();
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const handleConnection = (event: Event) => {
      const customEvent = event as CustomEvent<{ connected: boolean }>;
      setConnected(!!customEvent.detail?.connected);
    };
    window.addEventListener(CONNECTION_EVENT, handleConnection as EventListener);
    return () => {
      window.removeEventListener(CONNECTION_EVENT, handleConnection as EventListener);
    };
  }, []);

  const openPanel = (panel: 'settings' | 'personality' | 'memory') => {
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

  return (
    <header className="flex h-[52px] items-center justify-between border-b border-border/30 px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-medium tracking-wide text-foreground/80">{t('shell.headerTitle')}</h1>
        <Badge
          variant={connected ? 'default' : 'secondary'}
          className={connected ? 'bg-primary/20 text-primary border-primary/30' : ''}
        >
          {connected ? t('chat.connected') : t('chat.disconnected')}
        </Badge>
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="rounded-xl text-foreground/60 hover:text-foreground hover:bg-muted/50"
          onClick={() => openPanel('personality')}
          aria-label={t('shell.personality')}
        >
          <UserRound className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="rounded-xl text-foreground/60 hover:text-foreground hover:bg-muted/50"
          onClick={() => openPanel('memory')}
          aria-label={t('shell.memory')}
        >
          <Database className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="rounded-xl text-foreground/60 hover:text-foreground hover:bg-muted/50"
          onClick={() => openPanel('settings')}
          aria-label={t('shell.settings')}
        >
          <Settings2 className="h-4 w-4" />
        </Button>
        <div className="ml-1 flex h-8 items-center rounded-xl border border-primary/20 bg-primary/5 px-2.5 text-[11px] text-primary">
          <Sparkles className="mr-1.5 h-3.5 w-3.5" />
          {t('shell.desktopMode')}
        </div>
      </div>
    </header>
  );
};

export default Header;

