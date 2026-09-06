import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, FileText, RotateCcw } from 'lucide-react';

import { MemoryBackupDialog } from '@/components/settings/memory-data/MemoryBackupDialog';
import { MemoryExportDialog } from '@/components/settings/memory-data/MemoryExportDialog';
import { MemoryOperationProgress } from '@/components/settings/memory-data/MemoryOperationProgress';
import { MemoryRestoreDialog } from '@/components/settings/memory-data/MemoryRestoreDialog';
import { portabilityErrorMessage } from '@/components/settings/memory-data/presentation';
import { Button } from '@/components/ui/button';
import { useMemoryPortabilityOperation } from '@/hooks/useMemoryPortabilityOperation';
import { pickMemoryBackupFile } from '@/runtime/desktop';

interface MemoryDataManagementSectionProps {
  onRestoreCompleted?: () => void;
}

interface DataActionRowProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  actionLabel: string;
  disabled: boolean;
  onAction: (event: React.MouseEvent<HTMLButtonElement>) => void;
}

function DataActionRow({
  icon,
  title,
  description,
  actionLabel,
  disabled,
  onAction,
}: DataActionRowProps) {
  return (
    <div className="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="flex min-w-0 items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-muted/65 text-muted-foreground">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground">{title}</div>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">{description}</p>
        </div>
      </div>
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={onAction}>
        {actionLabel}
      </Button>
    </div>
  );
}

export function MemoryDataManagementSection({
  onRestoreCompleted,
}: MemoryDataManagementSectionProps) {
  const { t } = useTranslation('app');
  const sectionRef = useRef<HTMLElement>(null);
  const actionTriggerRef = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = (event: Event) => {
    event.preventDefault();
    const trigger = actionTriggerRef.current;
    if (trigger?.isConnected && !trigger.disabled) trigger.focus();
    else sectionRef.current?.focus();
  };
  const [backupOpen, setBackupOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [restoreSourcePath, setRestoreSourcePath] = useState<string | null>(null);
  const [pickingRestoreFile, setPickingRestoreFile] = useState(false);
  const [pickerError, setPickerError] = useState<string | null>(null);
  const {
    operation,
    busy,
    loadingActiveOperation,
    pollingInterrupted,
    trackOperation,
    reconcileStartedOperation,
    clearOperation,
  } = useMemoryPortabilityOperation({ onRestoreSucceeded: onRestoreCompleted });
  const actionsDisabled = busy || loadingActiveOperation || pickingRestoreFile;

  const handleChooseRestoreFile = async () => {
    setPickingRestoreFile(true);
    setPickerError(null);
    try {
      const sourcePath = await pickMemoryBackupFile(
        t('settings.memory.dataManagement.restore.fileFilter'),
      );
      if (sourcePath) {
        setRestoreSourcePath(sourcePath);
      }
    } catch (error) {
      setPickerError(portabilityErrorMessage(t, error));
    } finally {
      setPickingRestoreFile(false);
    }
  };

  return (
    <section
      ref={sectionRef}
      tabIndex={-1}
      className="py-3"
      aria-labelledby="memory-data-management-title"
      aria-busy={busy || loadingActiveOperation}
      data-testid="memory-data-management-section"
    >
      <div className="space-y-1">
        <h3 id="memory-data-management-title" className="text-sm font-medium text-foreground">
          {t('settings.memory.dataManagement.title')}
        </h3>
        <p className="max-w-3xl text-xs leading-6 text-muted-foreground">
          {t('settings.memory.dataManagement.description')}
        </p>
      </div>

      <div className="mt-3 divide-y divide-border/60 border-y border-border/60">
        <DataActionRow
          icon={<Archive className="h-4 w-4" />}
          title={t('settings.memory.dataManagement.backup.title')}
          description={t('settings.memory.dataManagement.backup.description')}
          actionLabel={t('settings.memory.dataManagement.backup.action')}
          disabled={actionsDisabled}
          onAction={(event) => { actionTriggerRef.current = event.currentTarget; setBackupOpen(true); }}
        />
        <DataActionRow
          icon={<FileText className="h-4 w-4" />}
          title={t('settings.memory.dataManagement.export.title')}
          description={t('settings.memory.dataManagement.export.description')}
          actionLabel={t('settings.memory.dataManagement.export.action')}
          disabled={actionsDisabled}
          onAction={(event) => { actionTriggerRef.current = event.currentTarget; setExportOpen(true); }}
        />
        <DataActionRow
          icon={<RotateCcw className="h-4 w-4" />}
          title={t('settings.memory.dataManagement.restore.title')}
          description={t('settings.memory.dataManagement.restore.description')}
          actionLabel={pickingRestoreFile
            ? t('settings.memory.dataManagement.restore.choosingFile')
            : t('settings.memory.dataManagement.restore.action')}
          disabled={actionsDisabled}
          onAction={(event) => { actionTriggerRef.current = event.currentTarget; void handleChooseRestoreFile(); }}
        />
      </div>

      {loadingActiveOperation ? (
        <p role={pollingInterrupted ? 'alert' : 'status'} className="mt-3 text-xs leading-5 text-muted-foreground">
          {t(pollingInterrupted
            ? 'settings.memory.dataManagement.operation.discoveryFailed'
            : 'settings.memory.dataManagement.operation.checking')}
        </p>
      ) : null}

      {pickerError ? (
        <p role="alert" className="mt-3 text-sm leading-6 text-destructive">
          {pickerError}
        </p>
      ) : null}

      {operation && !(operation.kind === 'inspect' && restoreSourcePath !== null) ? (
        <div className="mt-4">
          <MemoryOperationProgress
            operation={operation}
            pollingInterrupted={pollingInterrupted}
            onDismiss={clearOperation}
          />
        </div>
      ) : null}

      <MemoryBackupDialog
        onCloseAutoFocus={restoreFocus}
        open={backupOpen}
        onOpenChange={setBackupOpen}
        onStarted={trackOperation}
        onReconcileStarted={reconcileStartedOperation}
      />
      <MemoryExportDialog
        onCloseAutoFocus={restoreFocus}
        open={exportOpen}
        onOpenChange={setExportOpen}
        onStarted={trackOperation}
        onReconcileStarted={reconcileStartedOperation}
      />
      <MemoryRestoreDialog
        onCloseAutoFocus={restoreFocus}
        open={restoreSourcePath !== null}
        sourcePath={restoreSourcePath}
        operation={operation}
        pollingInterrupted={pollingInterrupted}
        onOpenChange={(open) => {
          if (!open) {
            setRestoreSourcePath(null);
          }
        }}
        onStarted={trackOperation}
        onReconcileStarted={reconcileStartedOperation}
        onInspectionSettled={clearOperation}
      />
    </section>
  );
}
