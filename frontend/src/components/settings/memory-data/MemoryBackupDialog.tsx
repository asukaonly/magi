import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, LockKeyhole } from 'lucide-react';

import {
  memoryPortabilityApi,
  type MemoryPortabilityOperation,
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
import { Switch } from '@/components/ui/switch';
import { pickDirectory } from '@/runtime/desktop';

interface MemoryBackupDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (operation: MemoryPortabilityOperation) => void;
}

export function MemoryBackupDialog({
  open,
  onOpenChange,
  onStarted,
}: MemoryBackupDialogProps) {
  const { t } = useTranslation('app');
  const [destinationDirectory, setDestinationDirectory] = useState('');
  const [passwordProtected, setPasswordProtected] = useState(true);
  const [password, setPassword] = useState('');
  const [passwordConfirmation, setPasswordConfirmation] = useState('');
  const [plaintextConfirmed, setPlaintextConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pickingDirectory, setPickingDirectory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setDestinationDirectory('');
    setPasswordProtected(true);
    setPassword('');
    setPasswordConfirmation('');
    setPlaintextConfirmed(false);
    setSubmitting(false);
    setPickingDirectory(false);
    setError(null);
  }, [open]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (submitting && !nextOpen) {
      return;
    }
    if (!nextOpen) {
      setPassword('');
      setPasswordConfirmation('');
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
      setError(t('settings.memory.dataManagement.backup.errors.destinationRequired'));
      return;
    }
    if (passwordProtected && !password) {
      setError(t('settings.memory.dataManagement.backup.errors.passwordRequired'));
      return;
    }
    if (passwordProtected && password !== passwordConfirmation) {
      setError(t('settings.memory.dataManagement.backup.errors.passwordMismatch'));
      return;
    }
    if (!passwordProtected && !plaintextConfirmed) {
      setError(t('settings.memory.dataManagement.backup.errors.plaintextConfirmationRequired'));
      return;
    }

    const submittedPassword = passwordProtected ? password : undefined;
    setPassword('');
    setPasswordConfirmation('');
    setSubmitting(true);
    try {
      const operation = await memoryPortabilityApi.createBackup({
        destinationDirectory,
        encryption: passwordProtected ? 'password' : 'none',
        password: submittedPassword,
      });
      onStarted(operation);
      onOpenChange(false);
    } catch (requestError) {
      setError(portabilityErrorMessage(t, requestError));
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
            <LockKeyhole className="h-5 w-5 text-[hsl(var(--settings-nav-active))]" />
            {t('settings.memory.dataManagement.backup.dialogTitle')}
          </DialogTitle>
          <DialogDescription>
            {t('settings.memory.dataManagement.backup.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 px-6 pb-5">
          <div className="space-y-2">
            <label htmlFor="memory-backup-destination" className="text-sm font-medium text-foreground">
              {t('settings.memory.dataManagement.common.destinationDirectory')}
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="memory-backup-destination"
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

          <div className="rounded-xl border border-border/70 bg-muted/25 px-4 py-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-medium text-foreground">
                  {t('settings.memory.dataManagement.backup.passwordProtection')}
                </div>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t('settings.memory.dataManagement.backup.passwordProtectionDescription')}
                </p>
              </div>
              <Switch
                checked={passwordProtected}
                disabled={submitting}
                onCheckedChange={(checked) => {
                  setPasswordProtected(checked);
                  setPlaintextConfirmed(false);
                  setPassword('');
                  setPasswordConfirmation('');
                  setError(null);
                }}
                aria-label={t('settings.memory.dataManagement.backup.passwordProtection')}
              />
            </div>
          </div>

          {passwordProtected ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label htmlFor="memory-backup-password" className="text-sm font-medium text-foreground">
                  {t('settings.memory.dataManagement.backup.password')}
                </label>
                <Input
                  id="memory-backup-password"
                  type="password"
                  autoComplete="new-password"
                  spellCheck={false}
                  value={password}
                  disabled={submitting}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="memory-backup-password-confirmation" className="text-sm font-medium text-foreground">
                  {t('settings.memory.dataManagement.backup.confirmPassword')}
                </label>
                <Input
                  id="memory-backup-password-confirmation"
                  type="password"
                  autoComplete="new-password"
                  spellCheck={false}
                  value={passwordConfirmation}
                  disabled={submitting}
                  onChange={(event) => setPasswordConfirmation(event.target.value)}
                />
              </div>
              <p className="text-xs leading-5 text-muted-foreground sm:col-span-2">
                {t('settings.memory.dataManagement.backup.passwordRecoveryWarning')}
              </p>
            </div>
          ) : (
            <label className="flex items-start gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-sm">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-input accent-[hsl(var(--settings-nav-active))]"
                checked={plaintextConfirmed}
                disabled={submitting}
                onChange={(event) => setPlaintextConfirmed(event.target.checked)}
              />
              <span className="leading-6 text-foreground/90">
                {t('settings.memory.dataManagement.backup.plaintextConfirmation')}
              </span>
            </label>
          )}

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
              ? t('settings.memory.dataManagement.backup.starting')
              : t('settings.memory.dataManagement.backup.start')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
