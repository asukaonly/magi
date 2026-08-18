import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, LockKeyhole, RotateCcw } from 'lucide-react';

import {
  memoryPortabilityApi,
  type MemoryPortabilityOperation,
  type MemoryRestoreInspection,
  type ReadyMemoryRestoreInspection,
} from '@/api/modules/memoryPortability';
import {
  formatPortabilityTimestamp,
  portabilityErrorMessage,
} from '@/components/settings/memory-data/presentation';
import {
  MemoryRecordCounts,
  MemoryRestoreScope,
  MemoryRestoreWarnings,
} from '@/components/settings/memory-data/MemoryPortabilityDetails';
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

interface MemoryRestoreDialogProps {
  open: boolean;
  sourcePath: string | null;
  onOpenChange: (open: boolean) => void;
  onStarted: (operation: MemoryPortabilityOperation) => void;
}

function discardCandidate(candidateId: string | null): void {
  if (!candidateId) {
    return;
  }
  void memoryPortabilityApi.discardRestoreCandidate(candidateId).catch(() => {
    // Restore candidates expire automatically; closing must remain responsive.
  });
}

export function MemoryRestoreDialog({
  open,
  sourcePath,
  onOpenChange,
  onStarted,
}: MemoryRestoreDialogProps) {
  const { t, i18n } = useTranslation('app');
  const [inspection, setInspection] = useState<MemoryRestoreInspection | null>(null);
  const [password, setPassword] = useState('');
  const [replaceConfirmed, setReplaceConfirmed] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestVersionRef = useRef(0);
  const candidateIdRef = useRef<string | null>(null);
  const confirmedRef = useRef(false);

  useEffect(() => {
    if (!open || !sourcePath) {
      return undefined;
    }

    let active = true;
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    candidateIdRef.current = null;
    confirmedRef.current = false;
    setInspection(null);
    setPassword('');
    setReplaceConfirmed(false);
    setInspecting(true);
    setConfirming(false);
    setError(null);

    void memoryPortabilityApi.inspectRestore({ sourcePath })
      .then((result) => {
        if (!active || requestVersionRef.current !== requestVersion) {
          discardCandidate(result.state === 'ready' ? result.candidate_id : null);
          return;
        }
        candidateIdRef.current = result.state === 'ready' ? result.candidate_id : null;
        setInspection(result);
      })
      .catch((requestError) => {
        if (active && requestVersionRef.current === requestVersion) {
          setError(portabilityErrorMessage(t, requestError));
        }
      })
      .finally(() => {
        if (active && requestVersionRef.current === requestVersion) {
          setInspecting(false);
        }
      });

    return () => {
      active = false;
      requestVersionRef.current += 1;
      if (!confirmedRef.current) {
        discardCandidate(candidateIdRef.current);
      }
      candidateIdRef.current = null;
    };
  }, [open, sourcePath, t]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && confirming) {
      return;
    }
    if (!nextOpen) {
      setPassword('');
      requestVersionRef.current += 1;
    }
    onOpenChange(nextOpen);
  };

  const handlePasswordSubmit = async () => {
    if (!sourcePath || !password) {
      setError(t('settings.memory.dataManagement.restore.errors.passwordRequired'));
      return;
    }

    const submittedPassword = password;
    setPassword('');
    setError(null);
    setInspecting(true);
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    try {
      const result = await memoryPortabilityApi.inspectRestore({
        sourcePath,
        password: submittedPassword,
      });
      if (requestVersionRef.current !== requestVersion) {
        discardCandidate(result.state === 'ready' ? result.candidate_id : null);
        return;
      }
      candidateIdRef.current = result.state === 'ready' ? result.candidate_id : null;
      setInspection(result);
    } catch (requestError) {
      if (requestVersionRef.current === requestVersion) {
        setError(portabilityErrorMessage(t, requestError));
      }
    } finally {
      if (requestVersionRef.current === requestVersion) {
        setInspecting(false);
      }
    }
  };

  const handleRetryInspection = async () => {
    if (!sourcePath) {
      return;
    }
    setError(null);
    setInspecting(true);
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    try {
      const result = await memoryPortabilityApi.inspectRestore({ sourcePath });
      if (requestVersionRef.current !== requestVersion) {
        discardCandidate(result.state === 'ready' ? result.candidate_id : null);
        return;
      }
      candidateIdRef.current = result.state === 'ready' ? result.candidate_id : null;
      setInspection(result);
    } catch (requestError) {
      if (requestVersionRef.current === requestVersion) {
        setError(portabilityErrorMessage(t, requestError));
      }
    } finally {
      if (requestVersionRef.current === requestVersion) {
        setInspecting(false);
      }
    }
  };

  const handleConfirm = async (readyInspection: ReadyMemoryRestoreInspection) => {
    if (!replaceConfirmed) {
      setError(t('settings.memory.dataManagement.restore.errors.replaceConfirmationRequired'));
      return;
    }

    setConfirming(true);
    setError(null);
    try {
      const operation = await memoryPortabilityApi.confirmRestore(readyInspection.candidate_id);
      confirmedRef.current = true;
      candidateIdRef.current = null;
      onStarted(operation);
      onOpenChange(false);
    } catch (requestError) {
      setError(portabilityErrorMessage(t, requestError));
    } finally {
      setConfirming(false);
    }
  };

  const readyInspection = inspection?.state === 'ready' ? inspection : null;
  const compatible = readyInspection
    ? readyInspection.compatibility !== 'unsupported'
    : false;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-h-[90vh] max-w-2xl overflow-y-auto"
        closeLabel={t('settings.memory.dataManagement.common.close')}
        hideClose={confirming}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5 text-[hsl(var(--settings-nav-active))]" />
            {t('settings.memory.dataManagement.restore.dialogTitle')}
          </DialogTitle>
          <DialogDescription>
            {t('settings.memory.dataManagement.restore.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 px-6 pb-5">
          <div className="rounded-xl border border-border/70 bg-muted/25 px-4 py-3">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t('settings.memory.dataManagement.restore.selectedFile')}
            </div>
            <p className="mt-1 break-all text-sm leading-6 text-foreground [overflow-wrap:anywhere]">
              {sourcePath}
            </p>
          </div>

          {inspecting && !readyInspection ? (
            <div className="flex min-h-32 flex-col items-center justify-center gap-3 text-sm text-muted-foreground" role="status">
              <LoadingSpinner />
              {t('settings.memory.dataManagement.restore.inspecting')}
            </div>
          ) : null}

          {inspection?.state === 'password_required' ? (
            <div className="space-y-4 rounded-xl border border-border/70 px-4 py-4">
              <div className="flex items-start gap-3">
                <LockKeyhole className="mt-0.5 h-5 w-5 flex-none text-[hsl(var(--settings-nav-active))]" />
                <div>
                  <div className="text-sm font-medium text-foreground">
                    {t('settings.memory.dataManagement.restore.passwordRequiredTitle')}
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {t('settings.memory.dataManagement.restore.passwordRequiredDescription')}
                  </p>
                </div>
              </div>
              <div className="space-y-2">
                <label htmlFor="memory-restore-password" className="text-sm font-medium text-foreground">
                  {t('settings.memory.dataManagement.restore.password')}
                </label>
                <Input
                  id="memory-restore-password"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={password}
                  disabled={inspecting}
                  onChange={(event) => setPassword(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      void handlePasswordSubmit();
                    }
                  }}
                />
              </div>
              <Button type="button" disabled={inspecting} onClick={() => void handlePasswordSubmit()}>
                {inspecting ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
                {t('settings.memory.dataManagement.restore.unlockAndInspect')}
              </Button>
            </div>
          ) : null}

          {readyInspection ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-xs font-medium text-foreground">
                  {t(`settings.memory.dataManagement.restore.compatibility.${readyInspection.compatibility}`)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {readyInspection.encrypted
                    ? t('settings.memory.dataManagement.restore.encrypted')
                    : t('settings.memory.dataManagement.restore.unencrypted')}
                </span>
              </div>

              <dl className="grid gap-3 rounded-xl border border-border/70 px-4 py-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">{t('settings.memory.dataManagement.restore.createdAt')}</dt>
                  <dd className="mt-1 text-foreground">
                    {formatPortabilityTimestamp(readyInspection.created_at, i18n.language)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t('settings.memory.dataManagement.restore.expiresAt')}</dt>
                  <dd className="mt-1 text-foreground">
                    {formatPortabilityTimestamp(readyInspection.expires_at, i18n.language)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t('settings.memory.dataManagement.restore.magiVersion')}</dt>
                  <dd className="mt-1 text-foreground">{readyInspection.magi_version}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t('settings.memory.dataManagement.restore.formatVersion')}</dt>
                  <dd className="mt-1 text-foreground">{readyInspection.format_version}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-xs text-muted-foreground">{t('settings.memory.dataManagement.restore.fingerprint')}</dt>
                  <dd className="mt-1 break-all font-mono text-xs leading-5 text-foreground [overflow-wrap:anywhere]">
                    {readyInspection.source_fingerprint}
                  </dd>
                </div>
              </dl>

              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground">
                  {t('settings.memory.dataManagement.restore.scopeTitle')}
                </div>
                <MemoryRestoreScope scope={readyInspection.scope} />
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground">
                  {t('settings.memory.dataManagement.restore.recordCountsTitle')}
                </div>
                <MemoryRecordCounts counts={readyInspection.record_counts} />
              </div>

              <MemoryRestoreWarnings warnings={readyInspection.warnings} />

              {!compatible ? (
                <div role="alert" className="rounded-xl border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm leading-6 text-destructive">
                  {t('settings.memory.dataManagement.restore.unsupportedDescription')}
                </div>
              ) : (
                <label className="flex items-start gap-3 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-input accent-destructive"
                    checked={replaceConfirmed}
                    disabled={confirming}
                    onChange={(event) => setReplaceConfirmed(event.target.checked)}
                  />
                  <span className="leading-6 text-foreground/90">
                    {t('settings.memory.dataManagement.restore.replaceConfirmation')}
                  </span>
                </label>
              )}
            </div>
          ) : null}

          {error ? (
            <div className="space-y-3">
              <p role="alert" className="text-sm leading-6 text-destructive">
                {error}
              </p>
              {!inspection ? (
                <Button type="button" variant="outline" disabled={inspecting} onClick={() => void handleRetryInspection()}>
                  {t('settings.memory.dataManagement.common.retry')}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" disabled={confirming} onClick={() => handleOpenChange(false)}>
            {t('settings.memory.dataManagement.common.cancel')}
          </Button>
          {readyInspection ? (
            <Button
              type="button"
              variant="destructive"
              disabled={confirming || !compatible || !replaceConfirmed}
              onClick={() => void handleConfirm(readyInspection)}
            >
              {confirming ? <LoadingSpinner className="mr-2 h-4 w-4" /> : <AlertTriangle className="mr-2 h-4 w-4" />}
              {confirming
                ? t('settings.memory.dataManagement.restore.starting')
                : t('settings.memory.dataManagement.restore.confirmReplace')}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
