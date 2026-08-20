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
        overlayClassName="bg-foreground/35 backdrop-blur-[3px]"
        className="w-[calc(100vw-2rem)] max-w-[440px] overflow-hidden rounded-xl border-border/60 bg-card/95 p-0 shadow-[0_28px_80px_hsl(var(--foreground)/0.2)]"
      >
        <div className="px-6 pb-5 pt-6">
          <div className="flex items-start gap-4">
            <span className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-destructive/10 text-destructive shadow-[inset_0_0_0_1px_hsl(var(--destructive)/0.16)]">
              <Power className="h-5 w-5" aria-hidden="true" />
            </span>
            <DialogHeader className="min-w-0 flex-1 space-y-1 px-0 pb-0 pt-0">
              <DialogTitle className="text-[19px] font-semibold leading-7 text-foreground">
                {t('desktop.quitConfirm.title')}
              </DialogTitle>
              <DialogDescription className="text-sm leading-6 text-muted-foreground">
                {t('desktop.quitConfirm.description')}
              </DialogDescription>
            </DialogHeader>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => void handleCancel()}
              className="-mr-2 -mt-2 h-8 w-8 rounded-md text-muted-foreground hover:bg-muted/70 hover:text-foreground"
              aria-label={t('desktop.quitConfirm.closeLabel')}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          <div className="mt-5 rounded-lg border border-destructive/15 bg-destructive/5 px-4 py-3 text-sm leading-6 text-destructive">
            {t('desktop.quitConfirm.warning')}
          </div>
        </div>

        <div className="border-t border-border/55 bg-muted/20 px-6 py-4">
          <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border/45 bg-background/75 px-3.5 py-3 text-sm text-muted-foreground transition-colors hover:bg-background">
            <input
              type="checkbox"
              checked={skipFutureConfirm}
              onChange={(event) => setSkipFutureConfirm(event.target.checked)}
              className="peer sr-only"
            />
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border bg-background text-background transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-ring/25 peer-checked:border-foreground peer-checked:bg-foreground">
              <Check
                className={skipFutureConfirm ? 'h-3 w-3 opacity-100' : 'h-3 w-3 opacity-0'}
                aria-hidden="true"
              />
            </span>
            <span className="min-w-0 flex-1">{t('desktop.quitConfirm.dontAskAgain')}</span>
          </label>

          <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="ghost"
              onClick={() => void handleCancel()}
              className="h-9 rounded-lg px-4 text-muted-foreground hover:bg-background hover:text-foreground"
            >
              {t('desktop.quitConfirm.cancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void handleConfirm()}
              className="h-9 rounded-lg px-4"
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
