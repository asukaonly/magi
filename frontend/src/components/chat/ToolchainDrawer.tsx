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

const toMilliseconds = (value?: number | null): number | null => {
  if (!value) return null;
  return value < 1_000_000_000_000 ? value * 1000 : value;
};

const formatTraceTime = (value?: number | null, locale?: string): string => {
  const normalized = toMilliseconds(value);
  if (!normalized) return '--';
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(normalized));
};

const formatExecutionTime = (value: unknown): string => {
  const normalized = Number(value || 0);
  if (!normalized) return '--';
  return `${normalized.toFixed(normalized >= 10 ? 1 : 2)}s`;
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

  React.useEffect(() => {
    if (displayRoot) {
      setSelectedNode(displayRoot.children[0] || displayRoot);
    }
  }, [displayRoot]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="!max-w-none w-[min(calc(100vw-24px),1820px)] rounded-l-[28px] border-l border-border/60 bg-[radial-gradient(circle_at_top,rgba(219,244,239,0.48),transparent_32%),linear-gradient(180deg,rgba(252,253,252,0.985),rgba(244,247,246,0.965))] p-0"
      >
        <SheetHeader className="border-b border-border/50 bg-white/82 px-8 py-6">
          <SheetTitle className="text-[28px] font-semibold tracking-[-0.04em] text-foreground">{title}</SheetTitle>
          <SheetDescription className="max-w-3xl pt-1 text-sm leading-6 text-muted-foreground">{subtitle}</SheetDescription>
        </SheetHeader>
        <div className="flex h-[calc(100%-116px)] min-h-0 flex-col">
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
              <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-border/40 bg-white/40 px-8 py-3 xl:grid-cols-4">
                <div className="rounded-[20px] border border-border/50 bg-white/92 px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryStatus')}</div>
                  <div className="mt-1.5 text-base font-semibold text-foreground">{snapshot.summary.headline}</div>
                </div>
                <div className="rounded-[20px] border border-border/50 bg-white/92 px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryDuration')}</div>
                  <div className="mt-1.5 text-base font-semibold text-foreground">{formatDuration(snapshot.summary.durationSeconds)}</div>
                </div>
                <div className="rounded-[20px] border border-border/50 bg-white/92 px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summarySteps')}</div>
                  <div className="mt-1.5 text-base font-semibold text-foreground">
                    {t('chat.trace.summaryStepsValue', {
                      completed: snapshot.summary.completedSteps,
                      failed: snapshot.summary.failedSteps,
                    })}
                  </div>
                </div>
                <div className="rounded-[20px] border border-border/50 bg-white/92 px-5 py-2.5 shadow-sm">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryMode')}</div>
                  <div className="mt-1.5 text-base font-semibold capitalize text-foreground">{snapshot.mode}</div>
                </div>
              </div>
              <div className="grid min-h-0 flex-1 gap-0 xl:grid-cols-[minmax(520px,0.92fr)_minmax(720px,1.08fr)]">
                <div className="min-h-0 overflow-y-auto border-r border-border/40 bg-[linear-gradient(180deg,rgba(255,255,255,0.56),rgba(247,251,249,0.76))] px-8 py-6">
                  <div className="mb-3 flex items-center justify-between rounded-2xl border border-border/40 bg-white/72 px-4 py-2.5">
                    <div>
                      <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">Execution Timeline</div>
                      <div className="mt-1 text-[13px] text-foreground/90">按执行顺序查看编排、分支和工具调用。</div>
                    </div>
                    <div className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs text-emerald-700">
                      {snapshot.summary.completedSteps + snapshot.summary.failedSteps} steps
                    </div>
                  </div>
                  {displayRoot && (
                    <TraceTree node={displayRoot} selectedNodeId={selectedNode?.id || null} onSelectNode={setSelectedNode} />
                  )}
                </div>
                <div className="min-h-0 overflow-y-auto bg-white/76 px-8 py-6">
                  {selectedNode ? (
                    <div className="space-y-4">
                      <div className="rounded-[24px] border border-border/50 bg-white/94 px-6 py-5 shadow-sm">
                        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.selected')}</div>
                        <div className="mt-2 flex flex-wrap items-center gap-3">
                          <div className="text-[24px] font-semibold tracking-[-0.04em] text-foreground">{selectedNode.label}</div>
                          <div className="rounded-full border border-border/60 bg-muted/35 px-3 py-1 text-xs capitalize text-muted-foreground">
                            {selectedNode.kind} · {selectedNode.status}
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
                          value={formatDuration(
                            selectedNode.startedAt && selectedNode.endedAt
                              ? Math.max(0, (selectedNode.endedAt - selectedNode.startedAt))
                              : 0
                          )}
                        />
                        <DetailBlock
                          label={t('chat.trace.executionTime')}
                          value={formatExecutionTime(selectedNode.metadata.execution_time)}
                        />
                      </div>

                      {selectedNode.resultPreview && (
                        <div className="rounded-[24px] border border-border/50 bg-white/94 px-5 py-5 shadow-sm">
                          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
                            <Hourglass className="h-3.5 w-3.5" />
                            {t('chat.trace.result')}
                          </div>
                          <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4 text-sm leading-7 text-foreground">
                            {selectedNode.resultPreview}
                          </div>
                        </div>
                      )}

                      {selectedNode.error && (
                        <div className="rounded-[24px] border border-rose-200 bg-rose-50/90 px-5 py-5 shadow-sm">
                          <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-rose-600/80">{t('chat.trace.error')}</div>
                          <div className="rounded-2xl border border-rose-200 bg-white/70 px-4 py-4 text-sm leading-7 text-rose-700">
                            {selectedNode.error}
                          </div>
                        </div>
                      )}
                      <div className="rounded-[24px] border border-border/50 bg-white/94 px-5 py-5 shadow-sm">
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
