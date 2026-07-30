import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { ProtectedImage } from '@/components/media/ProtectedImage';

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
      <DialogContent
        aria-describedby={undefined}
        hideClose
        overlayClassName="bg-foreground/65 backdrop-blur-md"
        className="w-auto max-w-[min(94vw,1280px)] overflow-visible border-0 bg-transparent p-0 shadow-none outline-none"
      >
        <DialogTitle className="sr-only">{preview?.name || t('chat.attachments.previewTitle')}</DialogTitle>
        {preview ? (
          <ProtectedImage
            src={preview.url}
            alt={preview.name}
            eager
            className="block max-h-[min(88vh,980px)] max-w-[min(94vw,1280px)] rounded-[18px] object-contain shadow-[0_28px_90px_hsl(var(--foreground)/0.42)]"
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
};
