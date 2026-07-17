import { Loader2, TriangleAlert } from 'lucide-react';
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

export function ChatClearHistoryDialog({
  open,
  loading,
  error,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  loading: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation('app');

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!loading) onOpenChange(nextOpen);
      }}
    >
      <DialogContent
        className="max-w-md overflow-hidden p-0"
        closeLabel={t('chat.clearHistoryDialog.close')}
        hideClose={loading}
      >
        <DialogHeader className="border-b border-border/60 bg-red-50/60 px-6 pb-5 pt-6 dark:bg-red-950/20">
          <div className="flex items-start gap-3 pr-8">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300">
              <TriangleAlert className="h-4 w-4" aria-hidden="true" />
            </span>
            <div className="min-w-0 space-y-2">
              <DialogTitle className="text-base leading-6">
                {t('chat.clearHistoryDialog.title')}
              </DialogTitle>
              <DialogDescription className="break-words leading-6">
                {t('chat.clearHistoryDialog.description')}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4 px-6 py-5">
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-3 text-sm leading-6 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200">
            {t('chat.clearHistoryDialog.warning')}
          </p>
          {error ? (
            <p
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3.5 py-3 text-sm leading-5 text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"
            >
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter className="border-border/60 bg-muted/15 px-6 py-4">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            {t('chat.clearHistoryDialog.cancel')}
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={loading}>
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {error ? t('chat.clearHistoryDialog.retry') : t('chat.clearHistoryDialog.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
