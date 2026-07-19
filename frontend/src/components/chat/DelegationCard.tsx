import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ExternalLink,
  X as XIcon,
  Trash2,
} from 'lucide-react';

import { codeAgentApi } from '@/api/modules/codeAgent';
import type { RunEvent } from '@/api/modules/codeAgent';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { MarkdownBlock } from '@/components/ui/markdown-block';
import { useDelegationHydration } from '@/hooks/useDelegationHydration';
import { selectDelegationCard, useDelegationsStore } from '@/stores/delegations-store';
import { cn } from '@/lib/utils';

import { UnifiedDiffViewer } from './UnifiedDiffViewer';


interface DelegationCardProps {
  sessionId: string;
  delegationId: string;
  turnId: string;
  workspace: string | null;
}




export function DelegationCard({
  sessionId,
  delegationId,
  turnId,
  workspace,
}: DelegationCardProps): JSX.Element | null {
  const { t } = useTranslation('app');
  const card = useDelegationsStore(selectDelegationCard(sessionId, delegationId));
  const setApplyOutcome = useDelegationsStore((s) => s.setApplyOutcome);
  const setLifecycle = useDelegationsStore((s) => s.setLifecycle);
  useDelegationHydration(sessionId, delegationId, turnId, workspace);

  const [busy, setBusy] = useState<'cancel' | 'apply' | 'discard' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const lifecycle = card?.lifecycle ?? 'started';
  const result = card?.result ?? null;
  const events = card?.events ?? [];
  const applyOutcome = card?.applyOutcome ?? null;
  const diffText = card?.diffText ?? '';

  const eventsTail = useMemo(() => events.slice(-50), [events]);

  if (!card) {
    return (
      <div className="rounded-md border border-border/60 bg-card/40 px-3 py-2 text-xs text-muted-foreground">
        <Loader2 className="inline h-3 w-3 animate-spin mr-1" />
        {t('chat.delegation.loading')}
      </div>
    );
  }

  const onCancel = async () => {
    if (!workspace) return;
    setBusy('cancel');
    setActionError(null);
    try {
      await codeAgentApi.cancelDelegation(sessionId, delegationId, workspace);
      setLifecycle(sessionId, delegationId, 'cancelled');
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const onApply = async () => {
    if (!workspace) return;
    setBusy('apply');
    setActionError(null);
    try {
      const { outcome } = await codeAgentApi.applyDelegation(sessionId, delegationId, workspace);
      setApplyOutcome(sessionId, delegationId, outcome);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const onDiscard = async () => {
    if (!workspace) return;
    setBusy('discard');
    setActionError(null);
    try {
      await codeAgentApi.discardDelegation(sessionId, delegationId, workspace);
      setLifecycle(sessionId, delegationId, 'discarded');
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const headerIcon = (() => {
    if (lifecycle === 'started' || lifecycle === 'running') {
      return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
    }
    if (lifecycle === 'finished' || lifecycle === 'applied') {
      return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
    }
    if (lifecycle === 'failed') {
      return <XCircle className="h-4 w-4 text-rose-600" />;
    }
    if (lifecycle === 'cancelled') {
      return <AlertTriangle className="h-4 w-4 text-amber-600" />;
    }
    if (lifecycle === 'discarded') {
      return <Trash2 className="h-4 w-4 text-muted-foreground" />;
    }
    return null;
  })();

  const adapterName = result?.adapter === 'claude_code' ? 'Claude Code' : result?.adapter === 'codex' ? 'Codex' : 'External Coder';

  const summary = result?.summary ?? null;
  const errorMessage = result?.error ?? null;
  const filesChanged = result?.files_changed ?? [];
  const cost = result?.cost ?? null;

  const showRunningPanel = lifecycle === 'started' || lifecycle === 'running';
  const showResultPanel =
    lifecycle === 'finished' ||
    lifecycle === 'cancelled' ||
    lifecycle === 'failed' ||
    lifecycle === 'applied';
  const showActions = showResultPanel && lifecycle === 'finished';  // Only show actions for successfully finished delegations

  return (
    <div
      className={cn(
        'rounded-md border bg-card/60 px-3 py-2 text-xs',
        lifecycle === 'failed' && 'border-rose-300/60',
        lifecycle === 'finished' || lifecycle === 'applied' ? 'border-emerald-300/60' : 'border-border/60',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {headerIcon}
          <span className="font-medium text-sm">
            {t('chat.delegation.title', { adapter: adapterName })}
          </span>
          <Badge variant="outline" className="text-[10px] font-mono">
            {delegationId.slice(0, 8)}…
          </Badge>
          <Badge variant="outline" className="text-[10px]">
            {t(`chat.delegation.lifecycle.${lifecycle}`)}
          </Badge>
        </div>
        {showRunningPanel && workspace && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={busy !== null}
            className="h-7 px-2 text-xs"
          >
            {busy === 'cancel' ? <Loader2 className="h-3 w-3 animate-spin" /> : <XIcon className="h-3 w-3" />}
            {t('chat.delegation.cancel')}
          </Button>
        )}
      </div>

      {actionError && (
        <div className="mt-2 rounded border border-rose-300/40 bg-rose-50/40 px-2 py-1 text-rose-700">
          {actionError}
        </div>
      )}

      {showRunningPanel && (
        <div className="mt-2 space-y-1">
          <div className="text-muted-foreground">{t('chat.delegation.activity')}</div>
          <ul className="max-h-40 overflow-auto rounded border border-border/40 bg-background/60 px-2 py-1 font-mono text-[11px]">
            {eventsTail.length === 0 && (
              <li className="text-muted-foreground/80">{t('chat.delegation.noActivity')}</li>
            )}
            {eventsTail.slice().reverse().map((event, idx) => (
              <li key={`${event.ts_ms}-${idx}`} className="truncate">
                · {renderEventLabel(event)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {showResultPanel && (
        <div className="mt-2 space-y-2">
          {summary && (
            <div className="rounded bg-muted/40 px-2 py-1.5 text-foreground">
              <div className="max-h-40 overflow-y-auto">
                <MarkdownBlock className="text-sm">{summary}</MarkdownBlock>
              </div>
            </div>
          )}
          {errorMessage && (
            <div className="rounded border border-rose-300/40 bg-rose-50/40 px-2 py-1.5 text-rose-800">
              <div>{errorMessage}</div>
              {errorMessage.toLowerCase().includes('not a git repository') && (
                <div className="mt-1 text-rose-700/90">
                  {t('chat.delegation.notAGitRepoHint')}
                  <a
                    className="ml-1 inline-flex items-center gap-1 underline"
                    href="?section=codeAgent"
                  >
                    {t('chat.delegation.openSettings')}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              )}
              {errorMessage.toLowerCase().includes('binary not found') && (
                <a
                  className="ml-2 inline-flex items-center gap-1 underline"
                  href="?section=codeAgent"
                >
                  {t('chat.delegation.openSettings')}
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
          )}
          {cost?.usd !== null && cost?.usd !== undefined && (
            <div className="text-muted-foreground">
              {t('chat.delegation.cost', { usd: cost.usd.toFixed(4) })}
            </div>
          )}
          {filesChanged.length > 0 && diffText && (
            <div className="space-y-1">
              <div className="text-muted-foreground">
                {t('chat.delegation.filesChanged', { count: filesChanged.length })}
              </div>
              <DiffPreview
                diffText={diffText}
                filesChanged={filesChanged}
              />
            </div>
          )}
          {applyOutcome && !applyOutcome.applied && applyOutcome.rejects.length > 0 && (
            <div className="rounded border border-rose-300/40 bg-rose-50/40 px-2 py-1.5 text-rose-800">
              <div className="font-medium mb-1">{t('chat.delegation.applyFailed')}</div>
              <ul className="list-disc pl-4 font-mono text-[11px]">
                {applyOutcome.rejects.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </div>
          )}
          {showActions && (
            <div className="flex gap-2 pt-1">
              {workspace && (
                <Button
                  type="button"
                  size="sm"
                  onClick={onApply}
                  disabled={busy !== null || filesChanged.length === 0}
                  className="h-7 px-3 text-xs"
                >
                  {busy === 'apply' && <Loader2 className="h-3 w-3 animate-spin" />}
                  {t('chat.delegation.apply')}
                </Button>
              )}
              {workspace && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onDiscard}
                  disabled={busy !== null}
                  className="h-7 px-3 text-xs"
                >
                  {busy === 'discard' && <Loader2 className="h-3 w-3 animate-spin" />}
                  {t('chat.delegation.discard')}
                </Button>
              )}
            </div>
          )}
          {lifecycle === 'applied' && (
            <div className="text-emerald-700 inline-flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />
              {t('chat.delegation.appliedNote', {
                count: applyOutcome?.files_applied?.length ?? filesChanged.length,
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function renderEventLabel(event: RunEvent): string {
  const payload = event.payload as Record<string, any>;
  if (event.kind === 'assistant_text' && typeof payload?.text === 'string') {
    return payload.text.slice(0, 80);
  }
  if (event.kind === 'tool_call' && typeof payload?.name === 'string') {
    return `tool: ${payload.name}`;
  }
  if (event.kind === 'status' && typeof payload?.event === 'string') {
    return `status: ${payload.event}`;
  }
  if (event.kind === 'error') {
    return `error: ${payload?.message ?? '(no message)'}`;
  }
  if (event.kind === 'stdout' && typeof payload?.line === 'string') {
    return payload.line.slice(0, 80);
  }
  return event.kind;
}


function DiffPreview({
  diffText,
  filesChanged,
}: {
  diffText: string;
  filesChanged: string[];
}): JSX.Element {
  const perFile = useMemo(() => splitUnifiedDiffByFile(diffText), [diffText]);
  return (
    <div className="space-y-1">
      {filesChanged.map((path) => (
        <UnifiedDiffViewer
          key={path}
          patchText={perFile[path] ?? ''}
          filename={path}
          collapsible
          defaultCollapsed
        />
      ))}
    </div>
  );
}


function splitUnifiedDiffByFile(unified: string): Record<string, string> {
  if (!unified.trim()) return {};
  const out: Record<string, string> = {};
  const lines = unified.split('\n');
  let current: string | null = null;
  let buf: string[] = [];
  const flush = () => {
    if (current !== null) {
      out[current] = buf.join('\n');
    }
  };
  for (const line of lines) {
    const m = /^diff --git a\/(.+?) b\/(.+?)$/.exec(line);
    if (m) {
      flush();
      current = m[2];
      buf = [line];
      continue;
    }
    if (current !== null) {
      buf.push(line);
    }
  }
  flush();
  return out;
}


export default DelegationCard;
