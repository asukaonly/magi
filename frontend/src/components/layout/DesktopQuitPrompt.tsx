import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Power, X } from 'lucide-react';

import { configApi } from '@/api/modules/config';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  cancelExitRequest,
  confirmExitApp,
  registerDesktopQuitHandler,
  syncSkipQuitConfirmationPreference,
} from '@/runtime/desktop';

const DesktopQuitPrompt = () => {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(false);
  const [skipFutureConfirm, setSkipFutureConfirm] = useState(false);

  useEffect(() => {
    let dispose: (() => void | Promise<void>) | undefined;
    let cancelled = false;

    const registerHandler = async () => {
      const nextDispose = await registerDesktopQuitHandler(() => {
        setSkipFutureConfirm(false);
        setOpen(true);
      });
      if (cancelled) {
        await nextDispose();
        return;
      }
      dispose = nextDispose;
    };

    void registerHandler();

    return () => {
      cancelled = true;
      void dispose?.();
    };
  }, []);

  const handleCancel = useCallback(async () => {
    await cancelExitRequest();
    setOpen(false);
  }, []);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    if (nextOpen) {
      setOpen(true);
      return;
    }
    void handleCancel();
  }, [handleCancel]);

  const handleConfirm = useCallback(async () => {
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
        // Startup may have failed; the in-process state still applies.
      }
    }
    await confirmExitApp();
    setOpen(false);
  }, [skipFutureConfirm]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        hideClose
        overlayClassName="bg-foreground/30 backdrop-blur-md"
        className="w-[calc(100vw-2.5rem)] max-w-[400px] gap-0 rounded-2xl border-border/40 bg-card/95 p-6 shadow-[0_24px_64px_-16px_hsl(var(--foreground)/0.28)] backdrop-blur-xl"
      >
        <div className="flex items-start gap-3.5">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <Power className="h-4 w-4" aria-hidden="true" />
          </span>
          <DialogHeader className="min-w-0 flex-1 space-y-1.5 px-0 pb-0 pt-0">
            <DialogTitle className="text-base font-semibold leading-6 text-foreground">
              {t('desktop.quitConfirm.title')}
            </DialogTitle>
            <DialogDescription className="text-[13px] leading-5 text-muted-foreground">
              {t('desktop.quitConfirm.description')}
            </DialogDescription>
          </DialogHeader>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => void handleCancel()}
            className="-mr-2 -mt-2 h-7 w-7 rounded-full text-muted-foreground/70 hover:bg-muted/70 hover:text-foreground"
            aria-label={t('desktop.quitConfirm.closeLabel')}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <label className="flex cursor-pointer select-none items-center gap-2 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
            <input
              type="checkbox"
              checked={skipFutureConfirm}
              onChange={(event) => setSkipFutureConfirm(event.target.checked)}
              className="peer sr-only"
            />
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[5px] border border-border/80 bg-background transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-ring/25 peer-checked:border-foreground peer-checked:bg-foreground">
              <Check
                className={skipFutureConfirm ? 'h-3 w-3 text-background opacity-100' : 'h-3 w-3 text-background opacity-0'}
                aria-hidden="true"
              />
            </span>
            {t('desktop.quitConfirm.dontAskAgain')}
          </label>

          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => void handleCancel()}
              className="h-8 rounded-full px-3.5 text-[13px] text-muted-foreground hover:bg-muted/70 hover:text-foreground"
            >
              {t('desktop.quitConfirm.cancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void handleConfirm()}
              className="h-8 rounded-full px-4 text-[13px] shadow-none hover:shadow-[0_6px_16px_hsl(var(--destructive)/0.22)]"
            >
              {t('desktop.quitConfirm.confirm')}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default DesktopQuitPrompt;
