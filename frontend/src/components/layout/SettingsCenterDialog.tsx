import React, { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SettingsPage } from '@/pages/Settings';
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
            <SettingsPage ref={pageRef} onRequestClose={() => void requestClose()} />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('settings.closeConfirm.title')}</DialogTitle>
            <DialogDescription>{t('settings.closeConfirm.description')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDiscardDialogOpen(false)}>
              {t('settings.closeConfirm.cancel')}
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleDiscardAndClose()}>
              {t('settings.closeConfirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default SettingsCenterDialog;
