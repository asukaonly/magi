import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useChatShellStore } from '@/stores';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  cancelExitRequest,
  confirmExitApp,
  registerDesktopShellHandlers,
} from '@/runtime/desktop';
import SettingsCenterDialog from './SettingsCenterDialog';

const getSettingsReturnPath = (state: unknown): string | null => {
  if (!state || typeof state !== 'object') return null;
  const candidate = (state as { returnTo?: unknown }).returnTo;
  if (typeof candidate !== 'string') return null;
  if (!candidate.startsWith('/') || candidate.startsWith('//')) return null;
  if (candidate.startsWith('/settings')) return null;
  return candidate;
};

const ShellOverlays = () => {
  const { t } = useTranslation('app');
  const location = useLocation();
  const navigate = useNavigate();
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const clearSettingsNavigationIntent = useChatShellStore((state) => state.clearSettingsNavigationIntent);
  const [quitConfirmOpen, setQuitConfirmOpen] = useState(false);

  const handleSettingsOpenChange = useCallback((open: boolean) => {
    if (open) {
      setActivePanel('settings');
      return;
    }
    setActivePanel('none');
    clearSettingsNavigationIntent();
    if (location.pathname === '/settings') {
      navigate(getSettingsReturnPath(location.state) ?? '/chat');
    }
  }, [clearSettingsNavigationIntent, location.pathname, location.state, navigate, setActivePanel]);

  useEffect(() => {
    let dispose: (() => void | Promise<void>) | undefined;

    const registerHandlers = async () => {
      dispose = await registerDesktopShellHandlers({
        onOpenSettings: () => {
          clearSettingsNavigationIntent();
          setActivePanel('settings');
          if (location.pathname !== '/settings') {
            navigate('/settings', {
              state: { returnTo: `${location.pathname}${location.search}${location.hash}` },
            });
          }
        },
        onRequestQuit: () => {
          setQuitConfirmOpen(true);
        },
      });
    };

    void registerHandlers();

    return () => {
      void dispose?.();
    };
  }, [clearSettingsNavigationIntent, location.hash, location.pathname, location.search, navigate, setActivePanel]);

  const handleCancelQuit = useCallback(async () => {
    await cancelExitRequest();
    setQuitConfirmOpen(false);
  }, []);

  const handleConfirmQuit = useCallback(async () => {
    await confirmExitApp();
    setQuitConfirmOpen(false);
  }, []);

  return (
    <>
      <SettingsCenterDialog
        open={activePanel === 'settings'}
        onOpenChange={handleSettingsOpenChange}
      />

      <Dialog open={quitConfirmOpen} onOpenChange={setQuitConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('desktop.quitConfirm.title')}</DialogTitle>
            <DialogDescription>{t('desktop.quitConfirm.description')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => void handleCancelQuit()}>
              {t('desktop.quitConfirm.cancel')}
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleConfirmQuit()}>
              {t('desktop.quitConfirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default ShellOverlays;
