import React from 'react';
import { Clock3, Hourglass, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import TraceTree from './TraceTree';
import { flattenPlanningNodeForDisplay, type NormalizedExecutionTraceNode, type NormalizedExecutionTraceSnapshot } from '@/pages/chat-state';
import { formatTraceKind, formatTraceLabel, formatTraceMode, formatTraceStatus } from './traceDisplay';

interface ToolchainDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  loading: boolean;
  snapshot: NormalizedExecutionTraceSnapshot | null;
  title: string;
  subtitle: string;
}

const formatDuration = (seconds: number): string => {
  if (!seconds) return '0.0s';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${(seconds % 60).toFixed(0)}s`;
};

const asRecord = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
);

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

const formatExecutionTime = (value: unknown): string => {
  const normalized = Number(value || 0);
  if (!normalized) return '--';
  return `${normalized.toFixed(normalized >= 10 ? 1 : 2)}s`;
};

const formatCount = (value: unknown): string => {
  const normalized = Number(value || 0);
  if (!normalized) return '0';
  return String(Math.round(normalized));
};

const formatBoolean = (value: unknown, truthyLabel: string, falsyLabel: string): string => (
  value ? truthyLabel : falsyLabel
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

const DetailBlock = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-2xl border border-border/50 bg-background/80 px-3 py-3">
    <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{label}</div>
    <div className="mt-2 text-sm font-medium text-foreground">{value}</div>
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
  const { t, i18n } = useTranslation('app');
  const [selectedNode, setSelectedNode] = React.useState<NormalizedExecutionTraceNode | null>(null);
  const displayRoot = React.useMemo(
    () => (snapshot?.root ? flattenPlanningNodeForDisplay(snapshot.root) : null),
    [snapshot],
  );
  const selectedMetadata = React.useMemo(
    () => asRecord(selectedNode?.metadata),
    [selectedNode],
  );
  const selectedInput = React.useMemo(
    () => {
      const input = asRecord(selectedMetadata.input);
      if (Object.keys(input).length > 0) {
        return input;
      }
      return asRecord(selectedMetadata.arguments);
    },
    [selectedMetadata],
  );
  const selectedOutput = React.useMemo(
    () => asRecord(selectedMetadata.output),
    [selectedMetadata],
  );
  const selectedMetrics = React.useMemo(
    () => {
      const metrics = asRecord(selectedMetadata.metrics);
      const canonicalMetrics = {
        provider: selectedMetadata.provider,
        model: selectedMetadata.model,
        input_tokens: selectedMetadata.input_tokens,
        output_tokens: selectedMetadata.output_tokens,
        reasoning_tokens: selectedMetadata.reasoning_tokens,
        cache_read_tokens: selectedMetadata.cache_read_tokens,
        cache_write_tokens: selectedMetadata.cache_write_tokens,
        thinking_enabled: selectedMetadata.thinking_enabled,
      };
      return Object.fromEntries(
        Object.entries({
          ...metrics,
          ...canonicalMetrics,
        }).filter(([, value]) => value !== undefined && value !== null && value !== '')
      );
    },
    [selectedMetadata],
  );
  const selectedTags = React.useMemo(
    () => asRecord(selectedMetadata.tags),
    [selectedMetadata],
  );
  const nodeDurationValue = React.useMemo(() => (
    Number(selectedMetadata.duration_ms || 0) > 0
      ? formatMilliseconds(selectedMetadata.duration_ms)
      : formatDuration(
        selectedNode?.startedAt && selectedNode.endedAt
          ? Math.max(0, selectedNode.endedAt - selectedNode.startedAt)
          : 0,
      )
  ), [selectedMetadata.duration_ms, selectedNode?.endedAt, selectedNode?.startedAt]);
  const executionTimeValue = React.useMemo(() => (
    Number(selectedMetadata.duration_ms || 0) > 0
      ? formatMilliseconds(selectedMetadata.duration_ms)
      : formatExecutionTime(selectedMetadata.execution_time)
  ), [selectedMetadata.duration_ms, selectedMetadata.execution_time]);

  React.useEffect(() => {
    if (displayRoot) {
      setSelectedNode(displayRoot.children[0] || displayRoot);
    }
  }, [displayRoot]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="trace-theme-surface flex h-full w-[min(1180px,calc(100vw-72px))] max-w-[1180px] flex-col overflow-hidden rounded-l-3xl border-l border-border/60 bg-card p-0 shadow-2xl"
      >
        <SheetHeader className="border-b border-border/50 bg-muted/30 px-8 py-6">
          <SheetTitle className="text-[28px] font-semibold tracking-[-0.04em] text-foreground">{title}</SheetTitle>
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
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryMode')}</div>
                  <div className="mt-1.5 text-base font-semibold text-foreground">
                    {formatTraceMode(snapshot.mode, t)}
                  </div>
                </div>
              </div>
              <div className="grid min-h-0 flex-1 gap-0 overflow-hidden xl:grid-cols-[minmax(320px,0.74fr)_minmax(0,1.26fr)]">
                <div className="min-h-0 min-w-0 overflow-y-auto border-r border-border/40 bg-muted/20 px-6 py-6 xl:px-7">
                  {displayRoot && (
                    <TraceTree node={displayRoot} selectedNodeId={selectedNode?.id || null} onSelectNode={setSelectedNode} />
                  )}
                </div>
                <div className="min-h-0 min-w-0 overflow-y-auto bg-muted/30 px-6 py-6 xl:px-7">
                  {selectedNode ? (
                    <div className="space-y-4">
                      <div className="rounded-3xl border border-border/50 bg-card px-6 py-5 shadow-sm">
                        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.selected')}</div>
                        <div className="mt-2 flex flex-wrap items-center gap-3">
                          <div className="text-[24px] font-semibold tracking-[-0.04em] text-foreground">
                            {formatTraceLabel(selectedNode.label, selectedNode.kind, t)}
                          </div>
                          <div className="rounded-full border border-border/60 bg-muted/35 px-3 py-1 text-xs capitalize text-muted-foreground">
                            {formatTraceKind(selectedNode.kind, t)} · {formatTraceStatus(selectedNode.status, t)}
                          </div>
                        </div>
                      </div>

                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        <DetailBlock
                          label={t('chat.trace.startedAt')}
                          value={formatTraceTime(selectedNode.startedAt, i18n.language)}
                        />
                        <DetailBlock
                          label={t('chat.trace.endedAt')}
                          value={formatTraceTime(selectedNode.endedAt, i18n.language)}
                        />
                        <DetailBlock
                          label={t('chat.trace.nodeDuration')}
                          value={nodeDurationValue}
                        />
                        <DetailBlock
                          label={t('chat.trace.executionTime')}
                          value={executionTimeValue}
                        />
                      </div>

                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        <DetailBlock
                          label={t('chat.trace.model')}
                          value={String(selectedMetrics.model || selectedMetadata.model || '--')}
                        />
                        <DetailBlock
                          label={t('chat.trace.provider')}
                          value={String(selectedMetrics.provider || selectedMetadata.provider || '--')}
                        />
                        <DetailBlock
                          label={t('chat.trace.attempt')}
                          value={String(selectedMetadata.attempt_index || '1')}
                        />
                        <DetailBlock
                          label={t('chat.trace.retryCount')}
                          value={String(selectedMetadata.retry_count || '0')}
                        />
                      </div>

                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        <DetailBlock
                          label={t('chat.trace.inputTokens')}
                          value={formatCount(selectedMetrics.input_tokens)}
                        />
                        <DetailBlock
                          label={t('chat.trace.outputTokens')}
                          value={formatCount(selectedMetrics.output_tokens)}
                        />
                        <DetailBlock
                          label={t('chat.trace.reasoningTokens')}
                          value={formatCount(selectedMetrics.reasoning_tokens)}
                        />
                        <DetailBlock
                          label={t('chat.trace.thinking')}
                          value={formatBoolean(selectedMetrics.thinking_enabled, t('chat.trace.enabled'), t('chat.trace.disabled'))}
                        />
                      </div>

                      {selectedNode.resultPreview && (
                        <div className="rounded-3xl border border-border/50 bg-card px-5 py-5 shadow-sm">
                          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
                            <Hourglass className="h-3.5 w-3.5" />
                            {t('chat.trace.result')}
                          </div>
                          <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4 text-sm leading-7 text-foreground">
                            {selectedNode.resultPreview}
                          </div>
                        </div>
                      )}

                      {!!Object.keys(selectedInput).length && (
                        <div className="rounded-3xl border border-border/50 bg-card px-5 py-5 shadow-sm">
                          <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.input')}</div>
                          <pre className="overflow-x-auto rounded-2xl border border-border/50 bg-background/80 p-4 text-xs leading-6 text-muted-foreground">
                            {stringifyStructuredValue(selectedInput)}
                          </pre>
                        </div>
                      )}

                      {!!Object.keys(selectedOutput).length && (
                        <div className="rounded-3xl border border-border/50 bg-card px-5 py-5 shadow-sm">
                          <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.output')}</div>
                          <pre className="overflow-x-auto rounded-2xl border border-border/50 bg-background/80 p-4 text-xs leading-6 text-muted-foreground">
                            {stringifyStructuredValue(selectedOutput)}
                          </pre>
                        </div>
                      )}

                      {!!Object.keys(selectedMetrics).length && (
                        <div className="rounded-3xl border border-border/50 bg-card px-5 py-5 shadow-sm">
                          <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.metrics')}</div>
                          <pre className="overflow-x-auto rounded-2xl border border-border/50 bg-background/80 p-4 text-xs leading-6 text-muted-foreground">
                            {stringifyStructuredValue(selectedMetrics)}
                          </pre>
                        </div>
                      )}

                      {!!Object.keys(selectedTags).length && (
                        <div className="rounded-3xl border border-border/50 bg-card px-5 py-5 shadow-sm">
                          <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.tags')}</div>
                          <pre className="overflow-x-auto rounded-2xl border border-border/50 bg-background/80 p-4 text-xs leading-6 text-muted-foreground">
                            {stringifyStructuredValue(selectedTags)}
                          </pre>
                        </div>
                      )}

                      {selectedNode.error && (
                        <div className="rounded-3xl border border-[hsl(var(--trace-error-border))] bg-[hsl(var(--trace-error-bg)/0.92)] px-5 py-5 shadow-sm">
                          <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-[hsl(var(--trace-error-foreground)/0.82)]">{t('chat.trace.error')}</div>
                          <div className="rounded-2xl border border-[hsl(var(--trace-error-border))] bg-card px-4 py-4 text-sm leading-7 text-[hsl(var(--trace-error-foreground))]">
                            {selectedNode.error}
                          </div>
                        </div>
                      )}
                      <div className="rounded-3xl border border-border/50 bg-card px-5 py-5 shadow-sm">
                        <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
                          <Clock3 className="h-3.5 w-3.5" />
                          {t('chat.trace.metadata')}
                        </div>
                        <pre className="overflow-x-auto rounded-2xl border border-border/50 bg-background/80 p-4 text-xs leading-6 text-muted-foreground">
                          {JSON.stringify(selectedNode.metadata, null, 2)}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">{t('chat.trace.noSelection')}</div>
                  )}
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
