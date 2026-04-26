import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';

type HistoryImagePreview = {
  name: string;
  url: string;
};

type HistoryImagePreviewDialogProps = {
  preview: HistoryImagePreview | null;
  onClose: () => void;
};

export const HistoryImagePreviewDialog = ({
  preview,
  onClose,
}: HistoryImagePreviewDialogProps) => {
  const { t } = useTranslation('app');

  return (
    <Dialog open={Boolean(preview)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl overflow-hidden border-border/70 bg-background/95 p-0">
        <DialogHeader className="sr-only">
          <DialogTitle>{preview?.name || t('chat.attachments.previewTitle')}</DialogTitle>
          <DialogDescription>{t('chat.attachments.previewDescription')}</DialogDescription>
        </DialogHeader>
        {preview ? (
          <div className="flex max-h-[85vh] flex-col">
            <div className="border-b border-border/60 px-6 py-4 pr-12">
              <div className="truncate text-sm font-medium text-foreground">{preview.name}</div>
            </div>
            <div className="flex min-h-0 flex-1 items-center justify-center bg-muted/30 p-4">
              <img
                src={preview.url}
                alt={preview.name}
                className="max-h-[70vh] w-auto max-w-full rounded-2xl object-contain shadow-sm"
              />
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
};