import React, { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SettingsPage } from '@/components/settings/SettingsContent';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import type { SettingsPageHandle } from '@/types/settings';

interface SettingsCenterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SettingsCenterDialog: React.FC<SettingsCenterDialogProps> = ({ open, onOpenChange }) => {
  const { t } = useTranslation('app');
  const pageRef = useRef<SettingsPageHandle>(null);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);

  const requestClose = async () => {
    if (pageRef.current?.hasUnsavedChanges()) {
      setDiscardDialogOpen(true);
      return;
    }
    onOpenChange(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      onOpenChange(true);
      return;
    }
    void requestClose();
  };

  const handleDiscardAndClose = async () => {
    await pageRef.current?.discardChanges();
    setDiscardDialogOpen(false);
    onOpenChange(false);
  };

  const shouldIgnoreOutsideInteraction = (target: EventTarget | null): boolean =>
    target instanceof HTMLElement && Boolean(target.closest('[data-select-field-menu]'));

  return (
    <>
      <Dialog open={open} modal={false} onOpenChange={handleOpenChange}>
        <DialogContent
          hideClose
          onInteractOutside={(event) => {
            if (shouldIgnoreOutsideInteraction(event.target)) {
              event.preventDefault();
            }
          }}
          onPointerDownOutside={(event) => {
            if (shouldIgnoreOutsideInteraction(event.target)) {
              event.preventDefault();
            }
          }}
          className="settings-theme-surface h-[88vh] max-w-6xl p-0"
        >
          <DialogHeader className="sr-only">
            <DialogTitle>{t('settings.title')}</DialogTitle>
            <DialogDescription>{t('settings.subtitle')}</DialogDescription>
          </DialogHeader>
          <div data-testid="settings-center-shell" className="h-full overflow-hidden rounded-[inherit]">
            <ErrorBoundary
              resetKey={open}
              fallback={
                <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
                  <div>
                    <h2 className="text-base font-semibold text-foreground">{t('settings.errorTitle')}</h2>
                    <p className="mt-2 max-w-md text-sm text-muted-foreground">{t('settings.errorDescription')}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                      {t('settings.actions.close')}
                    </Button>
                    <Button type="button" onClick={() => window.location.reload()}>
                      {t('settings.refresh')}
                    </Button>
                  </div>
                </div>
              }
            >
              <SettingsPage ref={pageRef} onRequestClose={() => void requestClose()} />
            </ErrorBoundary>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <DialogContent
          hideClose
          overlayClassName="bg-[hsl(var(--foreground)/0.2)] backdrop-blur-[3px]"
          className="settings-theme-surface max-w-[420px] overflow-hidden rounded-xl border-0 bg-[hsl(var(--settings-shell-elevated))] p-0 shadow-[0_28px_80px_hsl(var(--foreground)/0.18),inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.18)]"
        >
          <DialogHeader className="px-6 pb-4 pt-6">
            <div className="flex items-start gap-4">
              <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary)/0.1)] text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.16)]">
                <AlertTriangle className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <DialogTitle className="text-[18px] font-semibold leading-7 text-foreground">
                  {t('settings.closeConfirm.title')}
                </DialogTitle>
                <DialogDescription className="mt-1 text-sm leading-6 text-muted-foreground">
                  {t('settings.closeConfirm.description')}
                </DialogDescription>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setDiscardDialogOpen(false)}
                className="-mr-2 -mt-2 h-8 w-8 rounded-md text-muted-foreground hover:bg-[hsl(var(--settings-nav-hover)/0.72)] hover:text-foreground"
                aria-label={t('settings.closeConfirm.cancel')}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </DialogHeader>
          <DialogFooter className="border-0 px-6 pb-6 pt-1">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setDiscardDialogOpen(false)}
              className="h-9 rounded-lg px-4 text-muted-foreground hover:bg-[hsl(var(--settings-nav-hover)/0.78)] hover:text-foreground"
            >
              {t('settings.closeConfirm.cancel')}
            </Button>
            <Button type="button" onClick={() => void handleDiscardAndClose()} className="h-9 rounded-lg px-4">
              {t('settings.closeConfirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default SettingsCenterDialog;
