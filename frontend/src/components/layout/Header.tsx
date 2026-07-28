import React from 'react';
import { Activity, Brain, Settings2, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useChatShellStore } from '@/stores';

const Header: React.FC = () => {
  const { t } = useTranslation('app');
  const navigate = useNavigate();
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const clearSettingsNavigationIntent = useChatShellStore((state) => state.clearSettingsNavigationIntent);

  const openPanel = (panel: 'settings' | 'memory' | 'timeline') => {
    if (panel === 'settings') {
      clearSettingsNavigationIntent();
      setActivePanel('settings');
      return;
    }
    setActivePanel(panel);
    if (panel === 'timeline') {
      navigate('/timeline');
      return;
    }
    navigate('/memory/overview');
  };

  return (
    <header className="flex h-[52px] items-center justify-between border-b border-border/30 px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-medium tracking-wide text-foreground/80">{t('shell.headerTitle')}</h1>

      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="rounded-xl text-foreground/60 hover:text-foreground hover:bg-muted/50"
          onClick={() => openPanel('timeline')}
          aria-label={t('shell.timeline')}
        >
          <Activity className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="rounded-xl text-foreground/60 hover:text-foreground hover:bg-muted/50"
          onClick={() => openPanel('memory')}
          aria-label={t('shell.memory')}
        >
          <Brain className="h-4 w-4" />
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
