import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { EmbeddingPreflightPrompt } from '@/hooks/useSettingsPersistence';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface EmbeddingPreflightConfirmDialogProps {
  prompt: EmbeddingPreflightPrompt | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export function EmbeddingPreflightConfirmDialog({
  prompt,
  onCancel,
  onConfirm,
}: EmbeddingPreflightConfirmDialogProps) {
  const { t } = useTranslation('app');
  const open = Boolean(prompt);

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onCancel();
        }
      }}
    >
      <DialogContent className="max-w-lg" hideClose>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            {t('settings.memory.vector.preflightStrongTitle')}
          </DialogTitle>
          <DialogDescription>
            {t('settings.memory.vector.preflightStrongDescription', {
              count: prompt?.readyTotal ?? 0,
              layers: prompt?.layers || t('settings.memory.vector.preflightUnknownLayers'),
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="px-6 pb-2">
          <div className="space-y-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm leading-6 text-muted-foreground">
            <p>{t('settings.memory.vector.preflightStrongBody')}</p>
            <p>{t('settings.memory.vector.preflightRebuildHint')}</p>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t('settings.memory.vector.preflightStrongCancel')}
          </Button>
          <Button type="button" variant="destructive" onClick={onConfirm}>
            {t('settings.memory.vector.preflightStrongSave')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
