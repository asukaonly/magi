import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, History, Loader2, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toApiClientError } from '@/api/client';
import {
  memoryApi,
  type MemoryCorrectionHistoryResponse,
  type MemoryCorrectionKind,
  type MemoryCorrectionRecord,
} from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  createMemoryCorrectionRequestId,
  canRevertMemoryCorrection,
  formatMemoryCorrectionValue,
  type MemoryCorrectionUiTarget,
} from './memoryCorrectionModel';
import {
  correctionLocale,
  formatCorrectionScope,
  formatCorrectionTime,
} from './memoryCorrectionPresentation';

interface MemoryCorrectionHistoryProps {
  target: MemoryCorrectionUiTarget;
  refreshKey?: number;
  onReverted?: () => void | Promise<void>;
  onConflict?: () => void | Promise<void>;
}

const EMPTY_CONTEXT_LABELS: Readonly<Record<string, string>> = {};

export function MemoryCorrectionHistory({
  target,
  refreshKey = 0,
  onReverted,
  onConflict,
}: MemoryCorrectionHistoryProps) {
  const { t, i18n } = useTranslation('app');
  const [history, setHistory] = useState<MemoryCorrectionHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [revertingId, setRevertingId] = useState<string | null>(null);
  const [revertAttempt, setRevertAttempt] = useState<{ correctionId: string; requestId: string } | null>(null);
  const loadRequestRef = useRef(0);
  const revertInFlightRef = useRef(false);
  const historyTitleRef = useRef<HTMLHeadingElement | null>(null);
  const revertButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const revertCancelButtonRef = useRef<HTMLButtonElement | null>(null);
  const locale = correctionLocale(i18n.resolvedLanguage || i18n.language);
  const historyLoadFailed = t('memory.correction.history.loadFailed', {
    defaultValue: '暂时没能读取修改记录。',
  });

  const loadHistory = useCallback(async () => {
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    setLoading(true);
    setError(null);
    try {
      const nextHistory = await memoryApi.getCorrectionHistory(target.kind, target.id);
      if (requestId !== loadRequestRef.current) return;
      setHistory(nextHistory);
    } catch {
      if (requestId !== loadRequestRef.current) return;
      setHistory(null);
      setError(historyLoadFailed);
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, [historyLoadFailed, target.id, target.kind]);

  useEffect(() => {
    setConfirmingId(null);
    setRevertAttempt(null);
    void loadHistory();
    return () => {
      loadRequestRef.current += 1;
    };
  }, [loadHistory, refreshKey]);

  useEffect(() => {
    if (confirmingId) revertCancelButtonRef.current?.focus();
  }, [confirmingId]);

  const corrections = useMemo(
    () => [...(history?.corrections ?? [])].sort((left, right) => right.created_at - left.created_at),
    [history]
  );
  const contextLabels = history?.context_labels ?? EMPTY_CONTEXT_LABELS;

  const focusRevertControl = (correctionId: string) => {
    const focus = () => {
      const trigger = revertButtonRefs.current.get(correctionId);
      if (trigger && !trigger.disabled) {
        trigger.focus();
        return;
      }
      historyTitleRef.current?.focus();
    };
    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(focus);
    } else {
      window.setTimeout(focus, 0);
    }
  };

  const beginRevertConfirmation = (correctionId: string) => {
    setConfirmingId(correctionId);
    setRevertAttempt((current) => (
      current?.correctionId === correctionId
        ? current
        : { correctionId, requestId: createMemoryCorrectionRequestId() }
    ));
  };

  const cancelRevertConfirmation = (correctionId: string) => {
    setConfirmingId(null);
    setRevertAttempt(null);
    focusRevertControl(correctionId);
  };

  const handleRevert = async (correction: MemoryCorrectionRecord) => {
    if (revertInFlightRef.current) return;
    revertInFlightRef.current = true;
    const requestId = revertAttempt?.correctionId === correction.correction_id
      ? revertAttempt.requestId
      : createMemoryCorrectionRequestId();
    if (revertAttempt?.correctionId !== correction.correction_id) {
      setRevertAttempt({ correctionId: correction.correction_id, requestId });
    }
    setRevertingId(correction.correction_id);
    setError(null);
    try {
      try {
        await memoryApi.revertCorrection(correction.correction_id, requestId);
      } catch (caught) {
        const clientError = toApiClientError(caught);
        if (clientError.status === 409 || clientError.status === 404) {
          setConfirmingId(null);
          setRevertAttempt(null);
          await loadHistory();
          setError(t('memory.correction.history.revertConflict', {
            defaultValue: '这条记忆已经发生变化或不再存在。我们已重新读取最新记录，请从最新内容重新操作。',
          }));
          await runHistoryCallback(
            onConflict,
            'Failed to refresh memory after correction revert conflict'
          );
        } else {
          setConfirmingId(null);
          setError(t('memory.correction.history.revertFailed', {
            defaultValue: '暂时没能撤销这次修正，请稍后重试。',
          }));
        }
        return;
      }

      setConfirmingId(null);
      setRevertAttempt(null);
      await loadHistory();
      await runHistoryCallback(
        onReverted,
        'Failed to refresh memory after successful correction revert'
      );
    } finally {
      revertInFlightRef.current = false;
      setRevertingId((current) => (
        current === correction.correction_id ? null : current
      ));
      focusRevertControl(correction.correction_id);
    }
  };

  return (
    <section className="border-t border-[hsl(var(--memory-divider)/0.46)] py-5" aria-labelledby="memory-correction-history-title">
      <div className="flex items-center justify-between gap-3">
        <h3
          ref={historyTitleRef}
          id="memory-correction-history-title"
          tabIndex={-1}
          className="flex items-center gap-2 rounded-sm text-sm font-semibold text-[hsl(var(--memory-title))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.18)]"
        >
          <History className="h-4 w-4" aria-hidden="true" />
          {t('memory.correction.history.title', { defaultValue: '修正记录' })}
        </h3>
        {corrections.length > 0 ? (
          <span className="text-xs text-[hsl(var(--memory-muted))]">
            {t('memory.correction.history.count', { defaultValue: '{{count}} 次', count: corrections.length })}
          </span>
        ) : null}
      </div>

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-[hsl(var(--memory-muted))]" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t('memory.correction.history.loading', { defaultValue: '正在读取修改记录…' })}
        </div>
      ) : corrections.length === 0 && !error ? (
        <p className="mt-3 text-sm leading-6 text-[hsl(var(--memory-muted))]">
          {t('memory.correction.history.empty', { defaultValue: '还没有修正过这条记忆。' })}
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          {corrections.map((correction, index) => {
            const canRevert = canRevertMemoryCorrection(correction, corrections);
            const isConfirming = confirmingId === correction.correction_id;
            const isReverting = revertingId === correction.correction_id;
            const confirmationId = `memory-correction-revert-confirmation-${index}`;
            const confirmationTitleId = `${confirmationId}-title`;
            const confirmationDescriptionId = `${confirmationId}-description`;
            const isScheduled = correction.state === 'active'
              && Boolean(correction.effective_at && correction.effective_at > Date.now() / 1000);
            return (
              <article key={correction.correction_id} className="min-w-0 rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.46)] px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                      {kindLabel(correction.correction_kind, t)}
                    </div>
                    <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                      {formatCorrectionTime(correction.created_at, locale)}
                    </div>
                  </div>
                  <span className={cn(
                    'rounded-full px-2 py-1 text-[11px] font-medium',
                    isScheduled
                      ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-300'
                      : correction.state === 'active'
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/35 dark:text-emerald-300'
                      : 'bg-muted text-muted-foreground'
                  )}>
                    {isScheduled
                      ? t('memory.correction.history.scheduled', { defaultValue: '等待生效' })
                      : correction.state === 'active'
                      ? t('memory.correction.history.active', { defaultValue: '当前有效' })
                      : t('memory.correction.history.reverted', { defaultValue: '已撤销' })}
                  </span>
                </div>

                <CorrectionChangeSummary
                  target={target}
                  correction={correction}
                  locale={locale}
                  contextLabels={contextLabels}
                />

                {correction.reason ? (
                  <p className="mt-2 break-words text-xs leading-5 text-[hsl(var(--memory-body))]">
                    {t('memory.correction.history.reason', { defaultValue: '说明：{{reason}}', reason: correction.reason })}
                  </p>
                ) : null}

                {canRevert ? (
                  <div className="mt-3 border-t border-[hsl(var(--memory-divider)/0.45)] pt-3">
                    {isConfirming ? (
                      <div
                        id={confirmationId}
                        role="alertdialog"
                        aria-labelledby={confirmationTitleId}
                        aria-describedby={confirmationDescriptionId}
                        className="flex flex-wrap items-center justify-between gap-2"
                      >
                        <p id={confirmationTitleId} className="sr-only">
                          {t('memory.correction.history.confirmRevertTitle', {
                            defaultValue: '确认撤销这次修正？',
                          })}
                        </p>
                        <p id={confirmationDescriptionId} className="text-xs leading-5 text-[hsl(var(--memory-body))]">
                          {t('memory.correction.history.confirmRevert', {
                            defaultValue: '撤销后会恢复到这次修正之前的理解。',
                          })}
                        </p>
                        <div className="flex gap-2">
                          <Button
                            ref={revertCancelButtonRef}
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="min-h-9"
                            onClick={() => cancelRevertConfirmation(correction.correction_id)}
                            disabled={revertingId !== null}
                          >
                            {t('memory.correction.cancel', { defaultValue: '取消' })}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="min-h-9"
                            onClick={() => void handleRevert(correction)}
                            disabled={revertingId !== null}
                          >
                            {isReverting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                            {t('memory.correction.history.confirmRevertAction', { defaultValue: '确认撤销' })}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <Button
                        ref={(node) => {
                          if (node) revertButtonRefs.current.set(correction.correction_id, node);
                          else revertButtonRefs.current.delete(correction.correction_id);
                        }}
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="min-h-9 px-2 text-[hsl(var(--memory-body))]"
                        aria-controls={confirmationId}
                        aria-haspopup="dialog"
                        onClick={() => beginRevertConfirmation(correction.correction_id)}
                        disabled={revertingId !== null}
                      >
                        <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
                        {t('memory.correction.history.revert', { defaultValue: '撤销这次修正' })}
                      </Button>
                    )}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      )}

      {history?.versions && history.versions.length > 0 ? (
        <details className="group mt-4">
          <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between rounded-lg text-sm text-[hsl(var(--memory-body))] outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.14)]">
            <span>{t('memory.correction.history.versions', { defaultValue: '查看内容变化' })}</span>
            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <ol className="mt-2 space-y-2 border-l border-[hsl(var(--memory-divider)/0.65)] pl-4">
            {history.versions.map((version, index) => (
              <li key={versionKey(version, index)} className="text-xs leading-5 text-[hsl(var(--memory-body))]">
                <div className="break-words font-medium text-[hsl(var(--memory-title))]">
                  {versionSummary(target, version, t)}
                </div>
                <div className="mt-0.5 break-words text-[hsl(var(--memory-muted))]">
                  {versionMeta(version, t, locale, contextLabels)}
                </div>
              </li>
            ))}
          </ol>
        </details>
      ) : null}

      {error ? (
        <div role="alert" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm leading-5 text-red-700 dark:bg-red-950/30 dark:text-red-300">
          <span>{error}</span>
          {!loading && !history ? (
            <Button type="button" size="sm" variant="ghost" className="min-h-10" onClick={() => void loadHistory()}>
              {t('memory.correction.history.retry', { defaultValue: '重试' })}
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function CorrectionChangeSummary({
  target,
  correction,
  locale,
  contextLabels,
}: {
  target: MemoryCorrectionUiTarget;
  correction: MemoryCorrectionRecord;
  locale?: string;
  contextLabels: Readonly<Record<string, string>>;
}) {
  const { t } = useTranslation('app');
  const before = correctionValue(target, correction.before, t);
  const after = correction.replacement
    ? correctionValue(target, correction.replacement, t)
    : t('memory.correction.history.noLongerUsed', { defaultValue: '不再使用这条内容' });
  const scope = formatCorrectionScope(correction.scope, t, contextLabels);

  const isScopeRefinement = correction.correction_kind === 'scope_refinement';

  return (
    <div className="mt-3 space-y-1 break-words text-xs leading-5 text-[hsl(var(--memory-body))]">
      {!isScopeRefinement ? (
        <>
          <div>
            <span className="text-[hsl(var(--memory-muted))]">{t('memory.correction.history.before', { defaultValue: '原来：' })}</span>
            {before}
          </div>
          <div>
            <span className="text-[hsl(var(--memory-muted))]">{t('memory.correction.history.after', { defaultValue: '改为：' })}</span>
            {after}
          </div>
        </>
      ) : null}
      {correction.effective_at ? (
        <div>
          <span className="text-[hsl(var(--memory-muted))]">{t('memory.correction.history.effectiveAt', { defaultValue: '从：' })}</span>
          {formatCorrectionTime(correction.effective_at, locale)}
        </div>
      ) : null}
      {scope ? (
        <div>
          <span className="text-[hsl(var(--memory-muted))]">{t('memory.correction.history.scope', { defaultValue: '适用于：' })}</span>
          {scope}
        </div>
      ) : null}
    </div>
  );
}

async function runHistoryCallback(
  callback: (() => void | Promise<void>) | undefined,
  failureMessage: string
): Promise<void> {
  if (!callback) return;
  try {
    await callback();
  } catch (error) {
    console.error(failureMessage, error);
  }
}

function kindLabel(kind: MemoryCorrectionKind, t: ReturnType<typeof useTranslation<'app'>>['t']): string {
  if (kind === 'record_error') return t('memory.correction.kinds.record_error.title', { defaultValue: '这条记忆本来就不对' });
  if (kind === 'situation_changed') return t('memory.correction.kinds.situation_changed.title', { defaultValue: '以前是这样，现在变了' });
  return t('memory.correction.kinds.scope_refinement.title', { defaultValue: '只在某些情况下是这样' });
}

function correctionValue(
  target: MemoryCorrectionUiTarget,
  value: Record<string, unknown>,
  t: ReturnType<typeof useTranslation<'app'>>['t']
): string {
  if (target.kind === 'assertion') {
    return formatMemoryCorrectionValue(
      value.value ?? value.trait_value ?? target.currentValue,
      target.displayValue ?? formatMemoryCorrectionValue(target.currentValue, target.currentValue)
    );
  }
  const objectId = String(value.object_id ?? target.relationship.objectId).trim();
  const naturalSummary = String(value.natural_summary ?? '').trim();
  const knownObjectName = target.entityOptions.find((entity) => entity.id === objectId)?.name
    ?? (objectId === target.relationship.objectId ? target.relationship.objectName : null);
  if (knownObjectName) {
    return `${target.relationship.subjectName} ${target.relationship.predicateLabel} ${knownObjectName}`;
  }
  if (naturalSummary) return naturalSummary;
  const objectName = t('memory.correction.history.anotherObject', {
    defaultValue: '另一个对象',
  });
  return `${target.relationship.subjectName} ${target.relationship.predicateLabel} ${objectName}`;
}

function versionSummary(
  target: MemoryCorrectionUiTarget,
  version: Record<string, unknown>,
  t: ReturnType<typeof useTranslation<'app'>>['t']
): string {
  return correctionValue(target, version, t);
}

function versionMeta(
  version: Record<string, unknown>,
  t: ReturnType<typeof useTranslation<'app'>>['t'],
  locale: string | undefined,
  contextLabels: Readonly<Record<string, string>>
): string {
  const status = String(version.status ?? version.validation_state ?? '').toLowerCase();
  const from = optionalNumber(version.valid_from ?? version.first_inferred_at ?? version.first_observed_at);
  const to = optionalNumber(version.valid_to);
  const now = Date.now() / 1000;
  let statusText: string;
  if (to !== null && (to <= now || (from !== null && to <= from))) {
    statusText = t('memory.correction.history.pastVersion', { defaultValue: '历史版本' });
  } else if (from !== null && from > now) {
    statusText = t('memory.correction.history.plannedVersion', { defaultValue: '计划生效' });
  } else if (from !== null || to !== null) {
    statusText = (from === null || from <= now) && (to === null || to > now)
      ? t('memory.correction.history.currentVersion', { defaultValue: '当前版本' })
      : t('memory.correction.history.pastVersion', { defaultValue: '历史版本' });
  } else {
    statusText = ['active', 'valid', 'stable', 'corroborated'].includes(status)
      ? t('memory.correction.history.currentVersion', { defaultValue: '当前版本' })
      : t('memory.correction.history.pastVersion', { defaultValue: '历史版本' });
  }
  let meta: string;
  if (from && to) {
    meta = t('memory.correction.history.versionPeriod', {
      defaultValue: '{{status}} · {{from}} 至 {{to}}',
      status: statusText,
      from: formatCorrectionTime(from, locale),
      to: formatCorrectionTime(to, locale),
    });
  } else {
    meta = from
      ? t('memory.correction.history.versionFrom', {
          defaultValue: '{{status}} · 从 {{from}} 开始',
          status: statusText,
          from: formatCorrectionTime(from, locale),
        })
      : statusText;
  }
  const scope = version.scope && typeof version.scope === 'object' && !Array.isArray(version.scope)
    ? formatCorrectionScope(version.scope as Record<string, unknown>, t, contextLabels)
    : null;
  return scope
    ? t('memory.correction.history.versionScope', {
        defaultValue: '{{meta}} · {{scope}}',
        meta,
        scope,
      })
    : meta;
}

function versionKey(version: Record<string, unknown>, index: number): string {
  return String(
    version.version_id
      ?? version._governed_version_id
      ?? version.assertion_id
      ?? `${String(version.triple_id ?? 'version')}:${String(version.created_at ?? version.updated_at ?? index)}:${index}`
  );
}

function optionalNumber(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export default MemoryCorrectionHistory;
