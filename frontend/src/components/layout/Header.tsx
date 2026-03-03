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
    <header className="flex h-[64px] items-center justify-between border-b px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-semibold tracking-wide text-slate-700">{t('shell.headerTitle')}</h1>
        <Badge variant={connected ? 'default' : 'secondary'}>
          {connected ? t('chat.connected') : t('chat.disconnected')}
        </Badge>
      </div>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" className="rounded-xl" onClick={() => openPanel('personality')}>
          <UserRound className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="rounded-xl" onClick={() => openPanel('memory')}>
          <Database className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="rounded-xl" onClick={() => openPanel('settings')}>
          <Settings2 className="h-4 w-4" />
        </Button>
        <div className="ml-1 flex h-8 items-center rounded-xl bg-muted px-2 text-[11px] text-muted-foreground">
          <Sparkles className="mr-1 h-3.5 w-3.5 text-primary" />
          {t('shell.desktopMode')}
        </div>
      </div>
    </header>
  );
};

export default Header;

