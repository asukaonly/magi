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
import type { NormalizedExecutionTraceNode, NormalizedExecutionTraceSnapshot } from '@/pages/chat-state';

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

  React.useEffect(() => {
    if (snapshot?.root) {
      setSelectedNode(snapshot.root.children[0] || snapshot.root);
    }
  }, [snapshot]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="!max-w-none w-[min(92vw,1680px)] rounded-l-[32px] border-l border-border/60 bg-[radial-gradient(circle_at_top,rgba(219,244,239,0.5),transparent_34%),linear-gradient(180deg,rgba(252,253,252,0.98),rgba(244,247,246,0.96))] p-0"
      >
        <SheetHeader className="border-b border-border/50 bg-white/70 pb-5">
          <SheetTitle className="text-[30px] font-semibold tracking-[-0.04em] text-foreground">{title}</SheetTitle>
          <SheetDescription className="max-w-2xl text-sm leading-6 text-muted-foreground">{subtitle}</SheetDescription>
        </SheetHeader>
        <div className="flex h-[calc(100%-96px)] min-h-0 flex-col">
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
              <div className="grid shrink-0 grid-cols-2 gap-3 border-b border-border/40 px-6 py-5 xl:grid-cols-4">
                <div className="rounded-[24px] border border-border/50 bg-white/88 px-4 py-3 shadow-sm">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryStatus')}</div>
                  <div className="mt-2 text-lg font-semibold text-foreground">{snapshot.summary.headline}</div>
                </div>
                <div className="rounded-[24px] border border-border/50 bg-white/88 px-4 py-3 shadow-sm">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryDuration')}</div>
                  <div className="mt-2 text-lg font-semibold text-foreground">{formatDuration(snapshot.summary.durationSeconds)}</div>
                </div>
                <div className="rounded-[24px] border border-border/50 bg-white/88 px-4 py-3 shadow-sm">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summarySteps')}</div>
                  <div className="mt-2 text-lg font-semibold text-foreground">
                    {t('chat.trace.summaryStepsValue', {
                      completed: snapshot.summary.completedSteps,
                      failed: snapshot.summary.failedSteps,
                    })}
                  </div>
                </div>
                <div className="rounded-[24px] border border-border/50 bg-white/88 px-4 py-3 shadow-sm">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryMode')}</div>
                  <div className="mt-2 text-lg font-semibold capitalize text-foreground">{snapshot.mode}</div>
                </div>
              </div>
              <div className="grid min-h-0 flex-1 gap-0 xl:grid-cols-[minmax(420px,0.72fr)_minmax(780px,1.28fr)]">
                <div className="min-h-0 overflow-y-auto border-r border-border/40 bg-[linear-gradient(180deg,rgba(255,255,255,0.52),rgba(247,251,249,0.72))] px-6 py-5">
                  <div className="mb-4 rounded-[24px] border border-border/50 bg-white/80 px-4 py-4 shadow-sm">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">Execution Timeline</div>
                    <div className="mt-2 text-sm leading-6 text-foreground/90">按顺序展开本轮编排、并行分支和工具调用。</div>
                  </div>
                  <TraceTree node={snapshot.root} selectedNodeId={selectedNode?.id || null} onSelectNode={setSelectedNode} />
                </div>
                <div className="min-h-0 overflow-y-auto bg-white/72 px-6 py-5">
                  {selectedNode ? (
                    <div className="space-y-5">
                      <div className="rounded-[28px] border border-border/50 bg-white/92 px-5 py-5 shadow-sm">
                        <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.selected')}</div>
                        <div className="mt-3 text-[30px] font-semibold tracking-[-0.04em] text-foreground">{selectedNode.label}</div>
                        <div className="mt-2 text-sm text-muted-foreground">{selectedNode.kind} · {selectedNode.status}</div>
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
                        <div className="rounded-[28px] border border-border/50 bg-white/92 px-5 py-5 shadow-sm">
                          <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">
                            <Hourglass className="h-3.5 w-3.5" />
                            {t('chat.trace.result')}
                          </div>
                          <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4 text-sm leading-7 text-foreground">
                            {selectedNode.resultPreview}
                          </div>
                        </div>
                      )}

                      {selectedNode.error && (
                        <div className="rounded-[28px] border border-rose-200 bg-rose-50/90 px-5 py-5 shadow-sm">
                          <div className="mb-3 text-[11px] uppercase tracking-[0.18em] text-rose-600/80">{t('chat.trace.error')}</div>
                          <div className="rounded-2xl border border-rose-200 bg-white/70 px-4 py-4 text-sm leading-7 text-rose-700">
                            {selectedNode.error}
                          </div>
                        </div>
                      )}
                      <div className="rounded-[28px] border border-border/50 bg-white/92 px-5 py-5 shadow-sm">
                        <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">
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
