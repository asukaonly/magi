import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type MemoryFailureSummary } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { formatMemoryTimeRange } from '@/utils/memory-time';
import { useChatShellStore } from '@/stores/chat-shell';

export function MemoryFailureDetails({ revision, failed }: { revision: number; failed: number }) {
  const { t, i18n } = useTranslation('app');
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore((state) => state.setSettingsNavigationIntent);
  const [summary, setSummary] = useState<MemoryFailureSummary | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setSummary(null);
    setError(false);
    void memoryApi.getL2Failures().then((result) => {
      if (active) setSummary(result);
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [revision, failed, attempt]);

  if (error) return <div className="flex flex-wrap items-center gap-2 text-sm">
    <p role="alert">{t('memory.processing.details.loadFailed')}</p>
    <Button variant="ghost" size="sm" onClick={() => setAttempt((value) => value + 1)}>{t('common.retry')}</Button>
  </div>;
  if (!summary) return <p role="status" className="text-sm text-muted-foreground">{t('memory.processing.details.loading')}</p>;
  if (summary.total === 0) return <p className="text-sm text-muted-foreground">{t('memory.processing.details.empty')}</p>;

  return <div className="space-y-4">
    <ul className="divide-y divide-border/50">
      {summary.groups.map((group) => <li key={`${group.source}:${group.reason}`} className="py-3 first:pt-0 last:pb-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <p className="text-sm font-medium">{t(`memory.processing.reasons.${group.reason}.title`)}</p>
          <span className="text-xs text-muted-foreground">{getMemorySourceLabel(t, group.source)} · {t('memory.processing.details.count', { count: group.count })}</span>
        </div>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">{t(`memory.processing.reasons.${group.reason}.help`)}</p>
        {['auth', 'model_unavailable', 'invalid_parameter'].includes(group.reason) ? <Button className="mt-1" variant="ghost" size="sm" onClick={() => {
          setSettingsNavigationIntent({ section: 'llmModels' });
          setActivePanel('settings');
        }}>{t('memory.processing.details.modelSettings')}</Button> : null}
        <FailureTechnicalDetail error={group.error} time={formatMemoryTimeRange(group.last_failed_at, null, i18n.language)} />
      </li>)}
    </ul>
    {summary.other_count > 0 ? <p className="text-xs text-muted-foreground">{t('memory.processing.details.other', { count: summary.other_count })}</p> : null}
  </div>;
}

export function ConversationFailureDetails({ errorKinds }: { errorKinds: string[] }) {
  const { t } = useTranslation('app');
  return <ul className="space-y-3">
    {(errorKinds.length ? errorKinds : ['']).map((kind) => {
      const reason = kind === 'TimeoutError' || kind === 'APITimeoutError' ? 'timeout'
        : kind === 'LeaseExpired' ? 'interrupted' : 'unknown';
      return <li key={kind}>
        <p className="text-sm font-medium">{t(`memory.processing.reasons.${reason}.title`)}</p>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">{t(`memory.processing.reasons.${reason}.help`)}</p>
        <FailureTechnicalDetail error={kind || null} />
      </li>;
    })}
  </ul>;
}

function FailureTechnicalDetail({ error, time }: { error: string | null; time?: string }) {
  const { t } = useTranslation('app');
  return <details className="mt-2 text-xs text-muted-foreground">
    <summary className="w-fit cursor-pointer rounded-sm py-1 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring">{t('memory.processing.details.technical')}</summary>
    {time ? <p className="mt-1">{t('memory.processing.details.lastFailure', { time })}</p> : null}
    <p className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md bg-background/60 p-3 font-mono leading-5">{error || t('memory.processing.details.noError')}</p>
  </details>;
}
