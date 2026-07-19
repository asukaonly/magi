import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

const CLEAR_CONFIRM_COUNTDOWN_SECONDS = 3;

interface ClearMemoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clearing: boolean;
  onConfirm: () => Promise<void>;
}

export const ClearMemoryDialog: React.FC<ClearMemoryDialogProps> = ({
  open,
  onOpenChange,
  clearing,
  onConfirm,
}) => {
  const { t } = useTranslation('app');
  const [countdown, setCountdown] = useState(CLEAR_CONFIRM_COUNTDOWN_SECONDS);

  useEffect(() => {
    if (!open) {
      setCountdown(CLEAR_CONFIRM_COUNTDOWN_SECONDS);
      return undefined;
    }

    setCountdown(CLEAR_CONFIRM_COUNTDOWN_SECONDS);
    const timer = window.setInterval(() => {
      setCountdown((current) => {
        if (current <= 1) {
          window.clearInterval(timer);
          return 0;
        }
        return current - 1;
      });
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            {t('memory.clearConfirm.title')}
          </DialogTitle>
          <DialogDescription>{t('memory.clearConfirm.description')}</DialogDescription>
        </DialogHeader>
        <div data-testid="clear-memory-dialog-body" className="space-y-4 px-6 pb-2">
          <div className="rounded-xl border border-border/70 bg-muted/35 px-4 py-3">
            <ol className="list-decimal space-y-1 pl-5 text-sm text-foreground/88">
              <li>{t('memory.clearConfirm.conversations')}</li>
              <li>{t('memory.clearConfirm.events')}</li>
              <li>{t('memory.clearConfirm.relationships')}</li>
              <li>{t('memory.clearConfirm.summaries')}</li>
              <li>{t('memory.clearConfirm.learnedSkills')}</li>
              <li>{t('memory.clearConfirm.currentContext')}</li>
              <li>{t('memory.clearConfirm.pendingNotifications')}</li>
            </ol>
          </div>
          <p className="text-sm leading-6 text-muted-foreground">
            {t('memory.clearConfirm.preservedSettings')}
          </p>
          <div className="rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-muted-foreground">
            {countdown > 0
              ? t('memory.clearConfirm.countdownHint', { seconds: countdown })
              : t('memory.clearConfirm.readyHint')}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('memory.clearConfirm.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={countdown > 0 || clearing}
          >
            {clearing ? (
              <LoadingSpinner />
            ) : countdown > 0 ? (
              t('memory.clearConfirm.confirmCountdown', { seconds: countdown })
            ) : (
              t('memory.clearConfirm.confirm')
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ClearMemoryDialog;
