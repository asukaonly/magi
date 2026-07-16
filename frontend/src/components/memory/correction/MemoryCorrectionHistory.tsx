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

  const corrections = useMemo(
    () => [...(history?.corrections ?? [])].sort((left, right) => right.created_at - left.created_at),
    [history]
  );
  const latestActiveId = corrections.find((correction) => correction.state === 'active')?.correction_id ?? null;

  const handleRevert = async (correction: MemoryCorrectionRecord) => {
    const requestId = revertAttempt?.correctionId === correction.correction_id
      ? revertAttempt.requestId
      : createMemoryCorrectionRequestId();
    if (revertAttempt?.correctionId !== correction.correction_id) {
      setRevertAttempt({ correctionId: correction.correction_id, requestId });
    }
    setRevertingId(correction.correction_id);
    setError(null);
    try {
      await memoryApi.revertCorrection(correction.correction_id, requestId);
      setConfirmingId(null);
      setRevertAttempt(null);
      await loadHistory();
      await onReverted?.();
    } catch (caught) {
      const clientError = toApiClientError(caught);
      if (clientError.status === 409 || clientError.status === 404) {
        setConfirmingId(null);
        setRevertAttempt(null);
        await loadHistory();
        setError(t('memory.correction.history.revertConflict', {
          defaultValue: '这条记忆已经发生变化或不再存在。我们已重新读取最新记录，请从最新内容重新操作。',
        }));
        await onConflict?.();
      } else {
        setError(t('memory.correction.history.revertFailed', {
          defaultValue: '暂时没能撤销这次修正，请稍后重试。',
        }));
      }
    } finally {
      setRevertingId(null);
    }
  };

  return (
    <section className="border-t border-[hsl(var(--memory-divider)/0.46)] py-5" aria-labelledby="memory-correction-history-title">
      <div className="flex items-center justify-between gap-3">
        <h3 id="memory-correction-history-title" className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
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
          {corrections.map((correction) => {
            const canRevert = correction.correction_id === latestActiveId && correction.state === 'active';
            const isConfirming = confirmingId === correction.correction_id;
            const isReverting = revertingId === correction.correction_id;
            const isScheduled = correction.state === 'active'
              && Boolean(correction.effective_at && correction.effective_at > Date.now() / 1000);
            return (
              <article key={correction.correction_id} className="rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.46)] px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
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

                <CorrectionChangeSummary target={target} correction={correction} locale={locale} />

                {correction.reason ? (
                  <p className="mt-2 text-xs leading-5 text-[hsl(var(--memory-body))]">
                    {t('memory.correction.history.reason', { defaultValue: '说明：{{reason}}', reason: correction.reason })}
                  </p>
                ) : null}

                {canRevert ? (
                  <div className="mt-3 border-t border-[hsl(var(--memory-divider)/0.45)] pt-3">
                    {isConfirming ? (
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs leading-5 text-[hsl(var(--memory-body))]">
                          {t('memory.correction.history.confirmRevert', {
                            defaultValue: '撤销后会恢复到这次修正之前的理解。',
                          })}
                        </p>
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="min-h-9"
                            onClick={() => {
                              setConfirmingId(null);
                              setRevertAttempt(null);
                            }}
                            disabled={isReverting}
                          >
                            {t('memory.correction.cancel', { defaultValue: '取消' })}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="min-h-9"
                            onClick={() => void handleRevert(correction)}
                            disabled={isReverting}
                          >
                            {isReverting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                            {t('memory.correction.history.confirmRevertAction', { defaultValue: '确认撤销' })}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="min-h-9 px-2 text-[hsl(var(--memory-body))]"
                        onClick={() => {
                          setConfirmingId(correction.correction_id);
                          setRevertAttempt({
                            correctionId: correction.correction_id,
                            requestId: createMemoryCorrectionRequestId(),
                          });
                        }}
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
                <div className="font-medium text-[hsl(var(--memory-title))]">
                  {versionSummary(target, version, t)}
                </div>
                <div className="mt-0.5 text-[hsl(var(--memory-muted))]">
                  {versionMeta(version, t, locale)}
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
}: {
  target: MemoryCorrectionUiTarget;
  correction: MemoryCorrectionRecord;
  locale?: string;
}) {
  const { t } = useTranslation('app');
  const before = correctionValue(target, correction.before, t);
  const after = correction.replacement
    ? correctionValue(target, correction.replacement, t)
    : t('memory.correction.history.noLongerUsed', { defaultValue: '不再使用这条内容' });
  const scope = formatCorrectionScope(correction.scope, t);

  return (
    <div className="mt-3 space-y-1 break-words text-xs leading-5 text-[hsl(var(--memory-body))]">
      <div>
        <span className="text-[hsl(var(--memory-muted))]">{t('memory.correction.history.before', { defaultValue: '原来：' })}</span>
        {before}
      </div>
      <div>
        <span className="text-[hsl(var(--memory-muted))]">{t('memory.correction.history.after', { defaultValue: '改为：' })}</span>
        {after}
      </div>
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
    defaultValue: '对象 {{id}}',
    id: objectId,
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
  locale?: string
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
  if (from && to) {
    return t('memory.correction.history.versionPeriod', {
      defaultValue: '{{status}} · {{from}} 至 {{to}}',
      status: statusText,
      from: formatCorrectionTime(from, locale),
      to: formatCorrectionTime(to, locale),
    });
  }
  return from
    ? t('memory.correction.history.versionFrom', {
        defaultValue: '{{status}} · 从 {{from}} 开始',
        status: statusText,
        from: formatCorrectionTime(from, locale),
      })
    : statusText;
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
