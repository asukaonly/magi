import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { configApi } from '@/api/modules/config';
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
  syncSkipQuitConfirmationPreference,
} from '@/runtime/desktop';
import SettingsCenterDialog from './SettingsCenterDialog';

const ShellOverlays = () => {
  const { t } = useTranslation('app');
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const clearSettingsNavigationIntent = useChatShellStore((state) => state.clearSettingsNavigationIntent);
  const [quitConfirmOpen, setQuitConfirmOpen] = useState(false);
  const [skipFutureConfirm, setSkipFutureConfirm] = useState(false);

  const handleSettingsOpenChange = useCallback((open: boolean) => {
    if (open) {
      setActivePanel('settings');
      return;
    }
    setActivePanel('none');
    clearSettingsNavigationIntent();
  }, [clearSettingsNavigationIntent, setActivePanel]);

  useEffect(() => {
    let dispose: (() => void | Promise<void>) | undefined;

    const registerHandlers = async () => {
      dispose = await registerDesktopShellHandlers({
        onOpenSettings: () => {
          clearSettingsNavigationIntent();
          setActivePanel('settings');
        },
        onRequestQuit: () => {
          setSkipFutureConfirm(false);
          setQuitConfirmOpen(true);
        },
      });
    };

    void registerHandlers();

    return () => {
      void dispose?.();
    };
  }, [clearSettingsNavigationIntent, setActivePanel]);

  const handleCancelQuit = useCallback(async () => {
    await cancelExitRequest();
    setQuitConfirmOpen(false);
  }, []);

  const handleConfirmQuit = useCallback(async () => {
    if (skipFutureConfirm) {
      // Update the in-process Rust state first so we always honor the choice,
      // then best-effort persist to backend config so it survives restart.
      await syncSkipQuitConfirmationPreference(true);
      try {
        const response = await configApi.get();
        const current = response.data;
        if (current) {
          const next = structuredClone(current);
          next.preferences.skip_quit_confirmation = true;
          await configApi.update(next);
        }
      } catch {
        // Backend may already be shutting down; in-process state still applies.
      }
    }
    await confirmExitApp();
    setQuitConfirmOpen(false);
  }, [skipFutureConfirm]);

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
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={skipFutureConfirm}
              onChange={(event) => setSkipFutureConfirm(event.target.checked)}
            />
            <span>{t('desktop.quitConfirm.dontAskAgain')}</span>
          </label>
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
