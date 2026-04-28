import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';

interface LLMEmbeddingDimensionConfirmDialogProps {
  open: boolean;
  previousDimension: number | null;
  nextDimension: number | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export function LLMEmbeddingDimensionConfirmDialog({
  open,
  previousDimension,
  nextDimension,
  onCancel,
  onConfirm,
}: LLMEmbeddingDimensionConfirmDialogProps) {
  const { t } = useTranslation('onboarding');

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onCancel();
        }
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            {t('llm.embeddingDimensionConfirm.title')}
          </DialogTitle>
          <DialogDescription>
            {t('llm.embeddingDimensionConfirm.description', {
              current: previousDimension ?? '',
              next: nextDimension ?? '',
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="px-6 pb-2">
          <div className="rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm leading-6 text-muted-foreground">
            {t('llm.embeddingDimensionConfirm.warning')}
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t('llm.embeddingDimensionConfirm.cancel')}
          </Button>
          <Button type="button" variant="destructive" onClick={onConfirm}>
            {t('llm.embeddingDimensionConfirm.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}