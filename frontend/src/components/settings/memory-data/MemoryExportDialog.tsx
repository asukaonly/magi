import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, FolderOpen } from 'lucide-react';

import {
  memoryPortabilityApi,
  type MemoryPortabilityOperation,
  type MemoryPortabilityOperationKind,
} from '@/api/modules/memoryPortability';
import { portabilityErrorMessage } from '@/components/settings/memory-data/presentation';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { pickDirectory } from '@/runtime/desktop';

interface MemoryExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (operation: MemoryPortabilityOperation) => void;
  onReconcileStarted: (
    kind: MemoryPortabilityOperationKind,
  ) => Promise<MemoryPortabilityOperation | null>;
}

export function MemoryExportDialog({
  open,
  onOpenChange,
  onStarted,
  onReconcileStarted,
}: MemoryExportDialogProps) {
  const { t } = useTranslation('app');
  const [destinationDirectory, setDestinationDirectory] = useState('');
  const [readabilityConfirmed, setReadabilityConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pickingDirectory, setPickingDirectory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setDestinationDirectory('');
    setReadabilityConfirmed(false);
    setSubmitting(false);
    setPickingDirectory(false);
    setError(null);
  }, [open]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && submitting) {
      return;
    }
    onOpenChange(nextOpen);
  };

  const handleChooseDirectory = async () => {
    setPickingDirectory(true);
    setError(null);
    try {
      const selected = await pickDirectory(destinationDirectory || undefined);
      if (selected) {
        setDestinationDirectory(selected);
      }
    } catch (pickerError) {
      setError(portabilityErrorMessage(t, pickerError));
    } finally {
      setPickingDirectory(false);
    }
  };

  const handleSubmit = async () => {
    setError(null);
    if (!destinationDirectory) {
      setError(t('settings.memory.dataManagement.export.errors.destinationRequired'));
      return;
    }
    if (!readabilityConfirmed) {
      setError(t('settings.memory.dataManagement.export.errors.readabilityConfirmationRequired'));
      return;
    }

    setSubmitting(true);
    try {
      const operation = await memoryPortabilityApi.createExport({ destinationDirectory });
      onStarted(operation);
      onOpenChange(false);
    } catch (requestError) {
      const accepted = await onReconcileStarted('export');
      if (accepted) {
        onOpenChange(false);
      } else {
        setError(portabilityErrorMessage(t, requestError));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-h-[88vh] max-w-xl overflow-y-auto"
        closeLabel={t('settings.memory.dataManagement.common.close')}
        hideClose={submitting}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-[hsl(var(--settings-nav-active))]" />
            {t('settings.memory.dataManagement.export.dialogTitle')}
          </DialogTitle>
          <DialogDescription>
            {t('settings.memory.dataManagement.export.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 px-6 pb-5">
          <div className="space-y-2">
            <label htmlFor="memory-export-destination" className="text-sm font-medium text-foreground">
              {t('settings.memory.dataManagement.common.destinationDirectory')}
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="memory-export-destination"
                readOnly
                value={destinationDirectory}
                placeholder={t('settings.memory.dataManagement.common.noDirectorySelected')}
                className="min-w-0 flex-1"
              />
              <Button
                type="button"
                variant="outline"
                disabled={submitting || pickingDirectory}
                onClick={() => void handleChooseDirectory()}
              >
                <FolderOpen className="mr-2 h-4 w-4" />
                {t('settings.memory.dataManagement.common.chooseDirectory')}
              </Button>
            </div>
            {destinationDirectory ? (
              <p className="break-all text-xs leading-5 text-muted-foreground">
                {destinationDirectory}
              </p>
            ) : null}
          </div>

          <div className="rounded-xl border border-border/70 bg-muted/25 px-4 py-3 text-xs leading-5 text-muted-foreground">
            {t('settings.memory.dataManagement.export.contentsDescription')}
          </div>

          <label className="flex items-start gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-sm">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-input accent-[hsl(var(--settings-nav-active))]"
              checked={readabilityConfirmed}
              disabled={submitting}
              onChange={(event) => setReadabilityConfirmed(event.target.checked)}
            />
            <span className="leading-6 text-foreground/90">
              {t('settings.memory.dataManagement.export.readabilityConfirmation')}
            </span>
          </label>

          {error ? (
            <p role="alert" className="text-sm leading-6 text-destructive">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" disabled={submitting} onClick={() => handleOpenChange(false)}>
            {t('settings.memory.dataManagement.common.cancel')}
          </Button>
          <Button type="button" disabled={submitting} onClick={() => void handleSubmit()}>
            {submitting ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
            {submitting
              ? t('settings.memory.dataManagement.export.starting')
              : t('settings.memory.dataManagement.export.start')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
