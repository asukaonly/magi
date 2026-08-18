import { useTranslation } from 'react-i18next';
import { CheckCircle2, LoaderCircle, RotateCcw, XCircle } from 'lucide-react';

import type { MemoryPortabilityOperation } from '@/api/modules/memoryPortability';
import { MemoryRecordCounts } from '@/components/settings/memory-data/MemoryPortabilityDetails';
import {
  formatPortabilityBytes,
  formatPortabilityTimestamp,
  indexRebuildLabel,
  operationErrorMessage,
  operationPhaseLabel,
} from '@/components/settings/memory-data/presentation';
import { Button } from '@/components/ui/button';

interface MemoryOperationProgressProps {
  operation: MemoryPortabilityOperation;
  pollingInterrupted: boolean;
  onDismiss: () => void;
}

export function MemoryOperationProgress({
  operation,
  pollingInterrupted,
  onDismiss,
}: MemoryOperationProgressProps) {
  const { t, i18n } = useTranslation('app');
  const active = operation.status === 'pending' || operation.status === 'running';
  const succeeded = operation.status === 'succeeded';
  const progress = Math.max(0, Math.min(100, operation.progress_percent));
  const fileSize = formatPortabilityBytes(operation.file_size_bytes);
  const createdAt = formatPortabilityTimestamp(operation.created_at, i18n.language);
  const completedAt = formatPortabilityTimestamp(operation.completed_at, i18n.language);

  return (
    <div
      className={`rounded-xl border px-4 py-4 ${
        active
          ? 'border-[hsl(var(--settings-nav-active)/0.24)] bg-[hsl(var(--settings-nav-active)/0.05)]'
          : succeeded
            ? 'border-emerald-500/20 bg-emerald-500/5'
            : 'border-destructive/20 bg-destructive/5'
      }`}
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          {active ? (
            <LoaderCircle className="mt-0.5 h-5 w-5 flex-none animate-spin text-[hsl(var(--settings-nav-active))]" />
          ) : succeeded ? (
            <CheckCircle2 className="mt-0.5 h-5 w-5 flex-none text-emerald-600 dark:text-emerald-400" />
          ) : (
            <XCircle className="mt-0.5 h-5 w-5 flex-none text-destructive" />
          )}
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">
              {t(`settings.memory.dataManagement.operation.title.${operation.kind}`)}
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {active
                ? operationPhaseLabel(t, operation.phase)
                : t(`settings.memory.dataManagement.operation.status.${operation.status}`)}
            </p>
          </div>
        </div>
        {!active ? (
          <Button type="button" variant="ghost" size="sm" className="h-8" onClick={onDismiss}>
            {t('settings.memory.dataManagement.operation.dismiss')}
          </Button>
        ) : null}
      </div>

      {active ? (
        <div className="mt-4 space-y-2">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{t(`settings.memory.dataManagement.operation.status.${operation.status}`)}</span>
            <span className="tabular-nums">{Math.round(progress)}%</span>
          </div>
          <div
            className="h-2 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-label={t('settings.memory.dataManagement.operation.progressLabel')}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
          >
            <div
              className="h-full rounded-full bg-[hsl(var(--settings-nav-active))] transition-[width] duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          {pollingInterrupted ? (
            <p role="status" className="text-xs leading-5 text-amber-700 dark:text-amber-300">
              {t('settings.memory.dataManagement.operation.reconnecting')}
            </p>
          ) : null}
        </div>
      ) : null}

      {!active && succeeded ? (
        <div className="mt-4 space-y-4">
          {operation.output_path ? (
            <div>
              <div className="text-xs text-muted-foreground">
                {t('settings.memory.dataManagement.operation.outputPath')}
              </div>
              <p className="mt-1 break-all text-sm leading-6 text-foreground [overflow-wrap:anywhere]">
                {operation.output_path}
              </p>
            </div>
          ) : null}
          {fileSize ? (
            <p className="text-xs text-muted-foreground">
              {t('settings.memory.dataManagement.operation.fileSize', { size: fileSize })}
            </p>
          ) : null}
          <MemoryRecordCounts counts={operation.record_counts} />
          {operation.kind === 'restore' ? (
            <div className="space-y-2 border-t border-border/60 pt-3 text-xs leading-5 text-muted-foreground">
              {operation.safety_backup_path ? (
                <div>
                  <span className="font-medium text-foreground">
                    {t('settings.memory.dataManagement.operation.safetyBackup')}
                  </span>
                  <p className="mt-1 break-all [overflow-wrap:anywhere]">{operation.safety_backup_path}</p>
                </div>
              ) : null}
              {operation.index_rebuild_status ? (
                <p>
                  {t('settings.memory.dataManagement.operation.indexRebuildLabel', {
                    status: indexRebuildLabel(t, operation.index_rebuild_status),
                  })}
                </p>
              ) : null}
              <p className="flex items-start gap-2">
                <RotateCcw className="mt-0.5 h-3.5 w-3.5 flex-none" />
                {t('settings.memory.dataManagement.operation.restoreRestartHint')}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      {!active && !succeeded ? (
        <div className="mt-4 space-y-3">
          <p role="alert" className="text-sm leading-6 text-destructive">
            {operationErrorMessage(t, operation.error_code, operation.error_message)}
          </p>
          {operation.rollback_performed ? (
            <p className="text-xs leading-5 text-muted-foreground">
              {t('settings.memory.dataManagement.operation.rollbackSucceeded')}
            </p>
          ) : null}
          {operation.error_code === 'rollback_failed' || operation.error_code === 'restore_rollback_failed' ? (
            <p className="text-xs font-medium leading-5 text-destructive">
              {t('settings.memory.dataManagement.operation.rollbackFailedHelp')}
            </p>
          ) : null}
          {operation.safety_backup_path ? (
            <div className="text-xs leading-5 text-muted-foreground">
              <span className="font-medium text-foreground">
                {t('settings.memory.dataManagement.operation.safetyBackup')}
              </span>
              <p className="mt-1 break-all [overflow-wrap:anywhere]">{operation.safety_backup_path}</p>
            </div>
          ) : null}
        </div>
      ) : null}

      {!active && (createdAt || completedAt) ? (
        <p className="mt-4 border-t border-border/60 pt-3 text-xs text-muted-foreground">
          {createdAt ? t('settings.memory.dataManagement.operation.startedAt', { time: createdAt }) : null}
          {createdAt && completedAt ? ' · ' : null}
          {completedAt ? t('settings.memory.dataManagement.operation.completedAt', { time: completedAt }) : null}
        </p>
      ) : null}
    </div>
  );
}
