/**
 * ClearMemoryDialog - Dialog for confirming memory clear operation
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

interface ClearMemoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  confirmText: string;
  onConfirmTextChange: (text: string) => void;
  clearing: boolean;
  onConfirm: () => Promise<void>;
}

export const ClearMemoryDialog: React.FC<ClearMemoryDialogProps> = ({
  open,
  onOpenChange,
  confirmText,
  onConfirmTextChange,
  clearing,
  onConfirm,
}) => {
  const { t } = useTranslation('app');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            {t('memory.clearConfirm.title')}
          </DialogTitle>
          <DialogDescription>{t('memory.clearConfirm.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <ul className="text-sm space-y-1">
            <li>{t('memory.clearConfirm.l0')}</li>
            <li>{t('memory.clearConfirm.l1')}</li>
            <li>{t('memory.clearConfirm.l2')}</li>
            <li>{t('memory.clearConfirm.l3')}</li>
            <li>{t('memory.clearConfirm.l4')}</li>
            <li>{t('memory.clearConfirm.chatContext')}</li>
          </ul>
          <div>
            <label className="text-sm font-medium">{t('memory.clearConfirm.typePrompt')}</label>
            <input
              type="text"
              className="w-full mt-1 px-3 py-2 border rounded-md"
              value={confirmText}
              onChange={(e) => onConfirmTextChange(e.target.value)}
              placeholder="CLEAR"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={confirmText !== 'CLEAR' || clearing}
          >
            {clearing ? <LoadingSpinner /> : t('memory.clearConfirm.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ClearMemoryDialog;
