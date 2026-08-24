import React from 'react';
import type { TFunction } from 'i18next';
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Clock3,
  Hammer,
  Layers3,
  Loader2,
  MessageSquare,
  Search,
  Sparkles,
  Workflow,
  XCircle,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { flattenPlanningNodeForDisplay, type NormalizedExecutionTraceNode, type NormalizedExecutionTraceSnapshot } from '@/domain/chat/state';
import { cn } from '@/lib/utils';
import { formatTraceKind, formatTraceLabel, formatTraceStatus } from './traceDisplay';

interface ToolchainDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  loading: boolean;
  snapshot: NormalizedExecutionTraceSnapshot | null;
  title: string;
  subtitle: string;
}

type TraceTableRow = {
  node: NormalizedExecutionTraceNode;
  depth: number;
};

const statusTone: Record<string, string> = {
  completed: 'text-[hsl(var(--trace-status-completed-fg))] bg-[hsl(var(--trace-status-completed-bg))] border-[hsl(var(--trace-status-completed-border))]',
  running: 'text-[hsl(var(--trace-status-running-fg))] bg-[hsl(var(--trace-status-running-bg))] border-[hsl(var(--trace-status-running-border))]',
  pending: 'text-[hsl(var(--trace-status-pending-fg))] bg-[hsl(var(--trace-status-pending-bg))] border-[hsl(var(--trace-status-pending-border))]',
  failed: 'text-[hsl(var(--trace-status-failed-fg))] bg-[hsl(var(--trace-status-failed-bg))] border-[hsl(var(--trace-status-failed-border))]',
  blocked: 'text-[hsl(var(--trace-status-failed-fg))] bg-[hsl(var(--trace-status-failed-bg))] border-[hsl(var(--trace-status-failed-border))]',
  suspended: 'text-[hsl(var(--trace-status-pending-fg))] bg-[hsl(var(--trace-status-pending-bg))] border-[hsl(var(--trace-status-pending-border))]',
  cancelled: 'text-[hsl(var(--trace-status-pending-fg))] bg-[hsl(var(--trace-status-pending-bg))] border-[hsl(var(--trace-status-pending-border))]',
};

const formatDuration = (seconds: number): string => {
  if (!seconds) return '0.0s';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${(seconds % 60).toFixed(0)}s`;
};

const formatMilliseconds = (value: unknown): string => {
  const normalized = Number(value || 0);
  if (!normalized) return '--';
  if (normalized < 1000) return `${Math.round(normalized)}ms`;
  return formatDuration(normalized / 1000);
};

const toMilliseconds = (value?: number | null): number | null => {
  if (!value) return null;
  return value < 1_000_000_000_000 ? value * 1000 : value;
};

const formatTraceTime = (value?: number | null, locale?: string): string => {
  const normalized = toMilliseconds(value);
  if (!normalized) return '--';
  const formatted = new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(normalized));
  const milliseconds = String(new Date(normalized).getMilliseconds()).padStart(3, '0');
  return `${formatted}.${milliseconds}`;
};

const formatTokenCount = (input?: number, output?: number, reasoning?: number): string => {
  const parts: string[] = [];
  if (input) parts.push(`In ${input.toLocaleString()}`);
  if (output) parts.push(`Out ${output.toLocaleString()}`);
  if (reasoning) parts.push(`Think ${reasoning.toLocaleString()}`);
  return parts.length > 0 ? parts.join(' / ') : '--';
};

const formatCacheTokens = (read?: number, write?: number): string =>
  // Always show both counts (incl. 0) so a cache MISS is visible and
  // distinguishable from "no data" — the whole point of the panel (#98).
  `Read ${(read ?? 0).toLocaleString()} / Write ${(write ?? 0).toLocaleString()}`;

const asRecord = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
);

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const asStringArray = (value: unknown): string[] => (
  asArray(value)
    .map((item) => String(item || '').trim())
    .filter(Boolean)
);

const compactText = (value: unknown, limit = 480): string => {
  if (value === null || value === undefined) return '';
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return text.trim().slice(0, limit);
};

const hasValue = (value: unknown): boolean => (
  value !== null && value !== undefined && String(value).trim().length > 0
);

const stringifyStructuredValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const flattenTraceRows = (node: NormalizedExecutionTraceNode, depth = 0): TraceTableRow[] => {
  const current = node.kind === 'root' ? [] : [{ node, depth }];
  const childDepth = node.kind === 'root' ? depth : depth + 1;
  return [
    ...current,
    ...node.children.flatMap((child) => flattenTraceRows(child, childDepth)),
  ];
};

const statusIcon = (status: string) => {
  if (status === 'completed') return <CheckCircle2 className="h-3.5 w-3.5" />;
  if (status === 'failed' || status === 'blocked') return <XCircle className="h-3.5 w-3.5" />;
  if (status === 'running') return <CircleDashed className="h-3.5 w-3.5 animate-spin" />;
  return <CircleDashed className="h-3.5 w-3.5" />;
};

const kindIcon = (kind: string) => {
  if (kind === 'root') return <Layers3 className="h-4 w-4" />;
  if (kind === 'planning') return <Workflow className="h-4 w-4" />;
  if (kind === 'tool' || kind === 'tool_call') return <Hammer className="h-4 w-4" />;
  if (kind === 'llm' || kind === 'llm_call') return <Brain className="h-4 w-4" />;
  if (kind === 'skill' || kind === 'skill_call') return <Sparkles className="h-4 w-4" />;
  if (kind === 'intent' || kind === 'intent_resolution') return <Search className="h-4 w-4" />;
  if (kind === 'response' || kind === 'rhythm') return <MessageSquare className="h-4 w-4" />;
  return <Workflow className="h-4 w-4" />;
};

const nodeTitle = (node: NormalizedExecutionTraceNode, t: TFunction<'app'>): string => {
  if (node.kind === 'llm' || node.kind === 'llm_call') {
    return t('chat.trace.node.coreModelProcessing');
  }
  return formatTraceLabel(node.label, node.kind, t);
};

const nodeSubtitle = (node: NormalizedExecutionTraceNode): string => {
  const meta = asRecord(node.metadata);
  if (node.kind === 'tool' || node.kind === 'tool_call') {
    return String(meta.tool_name || '').trim();
  }
  if (node.kind === 'llm' || node.kind === 'llm_call') {
    return String(meta.model || '').trim();
  }
  if (node.kind === 'skill' || node.kind === 'skill_call') {
    return String(meta.skill_name || '').trim();
  }
  return String(node.resultPreview || '').trim();
};

const nodeDuration = (node: NormalizedExecutionTraceNode): string => {
  const meta = asRecord(node.metadata);
  if (Number(meta.duration_ms || 0) > 0) {
    return formatMilliseconds(meta.duration_ms);
  }
  if (node.startedAt && node.endedAt) {
    return formatDuration(Math.max(0, node.endedAt - node.startedAt));
  }
  return '--';
};

const previewFromSlot = (value: unknown): string => {
  const record = asRecord(value);
  return compactText(record.preview || record.summary || record.result_preview || record.content_preview);
};

const inputPreview = (node: NormalizedExecutionTraceNode): string => {
  const meta = asRecord(node.metadata);
  return (
    previewFromSlot(meta.input)
    || compactText(meta.request_preview)
    || compactText(meta.arguments)
    || compactText(meta.tool_arguments)
  );
};

const outputPreview = (node: NormalizedExecutionTraceNode): string => {
  const meta = asRecord(node.metadata);
  return (
    previewFromSlot(meta.output)
    || compactText(meta.response_preview)
    || compactText(node.resultPreview)
    || compactText(meta.result_json)
  );
};

const DetailField = ({ label, value }: { label: string; value: string }) => (
  <div className="min-w-0 border-l border-border/60 pl-3">
    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">{label}</div>
    <div className="mt-1 truncate text-sm font-medium text-foreground">{value || '--'}</div>
  </div>
);

const PreviewBlock = ({ label, children }: { label: string; children: string }) => (
  <div className="min-w-0">
    <div className="mb-2 text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">{label}</div>
    <pre className="max-h-56 overflow-auto rounded-md border border-border/50 bg-background/80 p-3 text-xs leading-6 text-muted-foreground whitespace-pre-wrap break-words">
      {children}
    </pre>
  </div>
);

const TokenList = ({ label, items }: { label: string; items: string[] }) => {
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className="rounded-full border border-border/60 bg-background/80 px-2 py-0.5 text-xs text-foreground">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
};

const NodeDetails = ({ node }: { node: NormalizedExecutionTraceNode }) => {
  const { t, i18n } = useTranslation('app');
  const meta = asRecord(node.metadata);
  const taskHint = asRecord(meta.task_hint);
  const routerTools = asStringArray(meta.router_tools);
  const selectedTools = asStringArray(meta.selected_tools);
  const input = inputPreview(node) || t('chat.trace.previewUnavailable');
  const output = outputPreview(node) || t('chat.trace.previewUnavailable');
  const metadataDefaultOpen = node.status === 'failed' || node.status === 'running';
  const hasModelInfo = hasValue(meta.model) || hasValue(meta.provider);
  const hasTokenInfo = Boolean(meta.input_tokens || meta.output_tokens || meta.reasoning_tokens);
  const hasRouteReason = hasValue(meta.route_reason);
  const isSkillNode = node.kind === 'skill' || node.kind === 'skill_call';
  const skillAllowedTools = isSkillNode ? asStringArray(meta.allowed_tools) : [];

  return (
    <div className="border-b border-border/35 border-t border-border/40 bg-muted/20 px-5 py-5">
      <div className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <DetailField label={t('chat.trace.startedAt')} value={formatTraceTime(node.startedAt, i18n.language)} />
        <DetailField label={t('chat.trace.endedAt')} value={formatTraceTime(node.endedAt, i18n.language)} />
        <DetailField label={t('chat.trace.nodeDuration')} value={nodeDuration(node)} />
        <DetailField label={t('chat.trace.executionTime')} value={formatMilliseconds(meta.execution_time || meta.duration_ms)} />
        {hasModelInfo && <DetailField label={t('chat.trace.model')} value={String(meta.model || '--')} />}
        {hasValue(meta.provider) && <DetailField label={t('chat.trace.provider')} value={String(meta.provider || '--')} />}
        {hasTokenInfo && (
          <DetailField
            label={t('chat.trace.summaryTokens')}
            value={formatTokenCount(Number(meta.input_tokens || 0), Number(meta.output_tokens || 0), Number(meta.reasoning_tokens || 0))}
          />
        )}
        {hasTokenInfo && (
          <DetailField
            label={t('chat.trace.cacheTokens')}
            value={formatCacheTokens(Number(meta.cache_read_tokens || 0), Number(meta.cache_write_tokens || 0))}
          />
        )}
        {hasValue(meta.intent_label) && <DetailField label={t('chat.trace.intentLabel')} value={String(meta.intent_label)} />}
        {hasValue(meta.execution_mode) && <DetailField label={t('chat.trace.executionMode')} value={String(meta.execution_mode)} />}
        {hasValue(taskHint.task_intent) && <DetailField label={t('chat.trace.taskIntent')} value={String(taskHint.task_intent)} />}
        {hasValue(taskHint.domain) && <DetailField label={t('chat.trace.taskDomain')} value={String(taskHint.domain)} />}
        {isSkillNode && hasValue(meta.skill_name) && (
          <DetailField label={t('chat.trace.skillName')} value={String(meta.skill_name)} />
        )}
        {isSkillNode && meta.fork_mode !== undefined && (
          <DetailField
            label={t('chat.trace.skillForkMode')}
            value={meta.fork_mode ? t('chat.trace.skillForkOn') : t('chat.trace.skillForkOff')}
          />
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <PreviewBlock label={t('chat.trace.input')}>{input}</PreviewBlock>
        <PreviewBlock label={t('chat.trace.output')}>{output}</PreviewBlock>
      </div>

      {(hasRouteReason || routerTools.length || selectedTools.length || skillAllowedTools.length || node.error) && (
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          {hasRouteReason && <PreviewBlock label={t('chat.trace.routeReason')}>{String(meta.route_reason)}</PreviewBlock>}
          {node.error && <PreviewBlock label={t('chat.trace.error')}>{node.error}</PreviewBlock>}
          <TokenList label={t('chat.trace.routerTools')} items={routerTools} />
          <TokenList label={t('chat.trace.selectedTools')} items={selectedTools} />
          <TokenList label={t('chat.trace.skillAllowedTools')} items={skillAllowedTools} />
        </div>
      )}

      <details className="mt-4 rounded-md border border-border/50 bg-background/70" open={metadataDefaultOpen}>
        <summary className="flex cursor-pointer select-none items-center gap-2 px-4 py-3 text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
          <Clock3 className="h-3.5 w-3.5" />
          {t('chat.trace.metadata')}
        </summary>
        <div className="border-t border-border/40 p-3">
          <pre className="max-h-72 overflow-auto text-xs leading-6 text-muted-foreground whitespace-pre-wrap break-words">
            {stringifyStructuredValue(node.metadata)}
          </pre>
        </div>
      </details>
    </div>
  );
};

const ContinuationNotice = ({ children }: { children: React.ReactNode }) => (
  <div className="rounded-md border border-amber-300/40 bg-amber-50/80 px-4 py-3 text-sm text-amber-950 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-100">
    {children}
  </div>
);

const ToolchainDrawer: React.FC<ToolchainDrawerProps> = ({
  open,
  onOpenChange,
  loading,
  snapshot,
  title,
  subtitle,
}) => {
  const { t } = useTranslation('app');
  const [expandedNodeIds, setExpandedNodeIds] = React.useState<Set<string>>(() => new Set());
  const displayRoot = React.useMemo(
    () => (snapshot?.root ? flattenPlanningNodeForDisplay(snapshot.root) : null),
    [snapshot],
  );
  const rows = React.useMemo(
    () => (displayRoot ? flattenTraceRows(displayRoot) : []),
    [displayRoot],
  );

  React.useEffect(() => {
    setExpandedNodeIds(new Set());
  }, [snapshot?.turnId]);

  const toggleNode = React.useCallback((nodeId: string) => {
    setExpandedNodeIds((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="trace-theme-surface my-3 mr-2 flex h-[calc(100%-1.5rem)] w-[min(1180px,calc(100vw-72px))] max-w-[1180px] flex-col overflow-hidden rounded-3xl border border-border/60 bg-card p-0 shadow-2xl"
      >
        <SheetHeader className="border-b border-border/50 bg-muted/30 px-8 py-6">
          <SheetTitle className="text-[28px] font-semibold text-foreground">{title}</SheetTitle>
          <SheetDescription className="max-w-3xl pt-1 text-sm leading-6 text-muted-foreground">{subtitle}</SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {loading && (
            <div className="flex h-full items-center justify-center gap-3 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('chat.trace.loading')}
            </div>
          )}
          {!loading && !snapshot && (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {t('chat.trace.empty')}
            </div>
          )}
          {!loading && snapshot && (
            <>
              {(snapshot.continuedFromTurnId || snapshot.supersededByTurnId) && (
                <div className="border-b border-border/40 bg-muted/20 px-8 py-3">
                  <div className="space-y-2">
                    {snapshot.continuedFromTurnId && (
                      <ContinuationNotice>
                        <span className="font-medium">{t('chat.trace.continuedFromTurn')}</span>{' '}
                        <span>{snapshot.continuedFromTurnId}</span>
                      </ContinuationNotice>
                    )}
                    {snapshot.supersededByTurnId && snapshot.supersessionReason === 'interrupted' && (
                      <ContinuationNotice>
                        <span className="font-medium">{t('chat.trace.interruptedIntoTurn')}</span>{' '}
                        <span>{snapshot.supersededByTurnId}</span>
                      </ContinuationNotice>
                    )}
                    {snapshot.supersededByTurnId && snapshot.supersessionReason === 'merged' && (
                      <ContinuationNotice>
                        <span className="font-medium">{t('chat.trace.mergedIntoTurn')}</span>{' '}
                        <span>{snapshot.supersededByTurnId}</span>
                      </ContinuationNotice>
                    )}
                  </div>
                </div>
              )}

              <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-border/40 bg-muted/30 px-8 py-3 xl:grid-cols-4">
                <div className="rounded-xl border border-border/50 bg-card px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryStatus')}</div>
                  <div className="mt-1.5 text-base font-semibold capitalize text-foreground">
                    {formatTraceStatus(snapshot.summary.status, t)}
                  </div>
                </div>
                <div className="rounded-xl border border-border/50 bg-card px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryDuration')}</div>
                  <div className="mt-1.5 text-base font-semibold text-foreground">{formatDuration(snapshot.summary.durationSeconds)}</div>
                </div>
                <div className="rounded-xl border border-border/50 bg-card px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summarySteps')}</div>
                  <div className="mt-1.5 text-base font-semibold text-foreground">
                    {t('chat.trace.summaryStepsValue', {
                      completed: snapshot.summary.completedSteps,
                      failed: snapshot.summary.failedSteps,
                    })}
                  </div>
                </div>
                <div className="rounded-xl border border-border/50 bg-card px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryTokens')}</div>
                  <div className="mt-1.5 text-base font-semibold text-foreground">
                    {formatTokenCount(
                      snapshot.summary.totalInputTokens,
                      snapshot.summary.totalOutputTokens,
                      snapshot.summary.totalReasoningTokens,
                    )}
                  </div>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-auto bg-muted/20 px-6 py-5 xl:px-8">
                <div className="min-w-[760px] overflow-hidden rounded-xl border border-border/50 bg-card shadow-sm">
                  <div className="grid grid-cols-[minmax(0,1fr)_112px_132px_56px] border-b border-border/50 bg-muted/35 px-4 py-2 text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
                    <div>{t('chat.trace.tableNode')}</div>
                    <div>{t('chat.trace.tableDuration')}</div>
                    <div>{t('chat.trace.tableStatus')}</div>
                    <div className="text-right">{t('chat.trace.tableAction')}</div>
                  </div>
                  {rows.map(({ node, depth }) => {
                    const expanded = expandedNodeIds.has(node.id);
                    const subtitle = nodeSubtitle(node);
                    return (
                      <React.Fragment key={node.id}>
                        <div className={cn(
                          'grid grid-cols-[minmax(0,1fr)_112px_132px_56px] items-center border-b border-border/35 px-4 py-3 transition-colors',
                          expanded ? 'bg-muted/30' : 'hover:bg-muted/20',
                        )}>
                          <div className="min-w-0">
                            <div className="flex min-w-0 items-center gap-3" style={{ paddingLeft: `${depth * 22}px` }}>
                              {depth > 0 && <span className="h-8 w-px shrink-0 bg-border/70" />}
                              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border/60 bg-background text-muted-foreground">
                                {kindIcon(node.kind)}
                              </span>
                              <div className="min-w-0 flex-1">
                                <div className="flex min-w-0 items-center gap-2">
                                  <span className="truncate text-sm font-semibold text-foreground">{nodeTitle(node, t)}</span>
                                  <span className="shrink-0 rounded-full border border-border/60 bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
                                    {formatTraceKind(node.kind, t)}
                                  </span>
                                </div>
                                {subtitle && (
                                  <div className="mt-1 truncate text-xs text-muted-foreground">{subtitle}</div>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="text-sm font-medium text-foreground">{nodeDuration(node)}</div>
                          <div>
                            <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs', statusTone[node.status] || statusTone.pending)}>
                              {statusIcon(node.status)}
                              {formatTraceStatus(node.status, t)}
                            </span>
                          </div>
                          <div className="flex justify-end">
                            <button
                              type="button"
                              onClick={() => toggleNode(node.id)}
                              aria-expanded={expanded}
                              aria-label={expanded ? t('chat.trace.collapseNode') : t('chat.trace.expandNode')}
                              className="flex h-8 w-8 items-center justify-center rounded-md border border-border/60 bg-background text-muted-foreground transition-colors hover:text-foreground"
                            >
                              {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            </button>
                          </div>
                        </div>
                        {expanded && <NodeDetails node={node} />}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
};

export default ToolchainDrawer;
