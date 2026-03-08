import React from 'react';
import { Loader2 } from 'lucide-react';
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

const ToolchainDrawer: React.FC<ToolchainDrawerProps> = ({
  open,
  onOpenChange,
  loading,
  snapshot,
  title,
  subtitle,
}) => {
  const { t } = useTranslation('app');
  const [selectedNode, setSelectedNode] = React.useState<NormalizedExecutionTraceNode | null>(null);

  React.useEffect(() => {
    console.debug('[toolchain] drawer props changed', {
      open,
      loading,
      turnId: snapshot?.turnId || null,
      hasSnapshot: Boolean(snapshot),
      rootNodeId: snapshot?.root?.id || null,
    });
  }, [loading, open, snapshot]);

  React.useEffect(() => {
    if (snapshot?.root) {
      setSelectedNode(snapshot.root.children[0] || snapshot.root);
    }
  }, [snapshot]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[min(92vw,1100px)] rounded-l-[28px] border-l border-border/60 bg-[linear-gradient(180deg,rgba(250,250,250,0.98),rgba(244,246,248,0.96))] p-0"
        onOpenAutoFocus={() => {
          console.debug('[toolchain] sheet onOpenAutoFocus');
        }}
        onCloseAutoFocus={() => {
          console.debug('[toolchain] sheet onCloseAutoFocus');
        }}
        onPointerDownOutside={(event) => {
          console.debug('[toolchain] sheet onPointerDownOutside', {
            target: event.target instanceof HTMLElement ? event.target.outerHTML.slice(0, 200) : String(event.target),
          });
        }}
        onInteractOutside={(event) => {
          console.debug('[toolchain] sheet onInteractOutside', {
            target: event.target instanceof HTMLElement ? event.target.outerHTML.slice(0, 200) : String(event.target),
          });
        }}
        onEscapeKeyDown={() => {
          console.debug('[toolchain] sheet onEscapeKeyDown');
        }}
      >
        <SheetHeader className="border-b border-border/50 pb-4">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{subtitle}</SheetDescription>
        </SheetHeader>
        <div className="flex h-[calc(100%-84px)] min-h-0 flex-col">
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
              <div className="grid shrink-0 grid-cols-2 gap-3 border-b border-border/40 px-6 py-4 md:grid-cols-4">
                <div className="rounded-2xl border border-border/50 bg-white/75 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryStatus')}</div>
                  <div className="mt-1 text-sm font-medium text-foreground">{snapshot.summary.headline}</div>
                </div>
                <div className="rounded-2xl border border-border/50 bg-white/75 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryDuration')}</div>
                  <div className="mt-1 text-sm font-medium text-foreground">{formatDuration(snapshot.summary.durationSeconds)}</div>
                </div>
                <div className="rounded-2xl border border-border/50 bg-white/75 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summarySteps')}</div>
                  <div className="mt-1 text-sm font-medium text-foreground">
                    {t('chat.trace.summaryStepsValue', {
                      completed: snapshot.summary.completedSteps,
                      failed: snapshot.summary.failedSteps,
                    })}
                  </div>
                </div>
                <div className="rounded-2xl border border-border/50 bg-white/75 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.summaryMode')}</div>
                  <div className="mt-1 text-sm font-medium text-foreground">{snapshot.mode}</div>
                </div>
              </div>
              <div className="grid min-h-0 flex-1 gap-0 md:grid-cols-[minmax(0,1fr)_300px]">
                <div className="min-h-0 overflow-y-auto px-6 py-5">
                  <TraceTree node={snapshot.root} selectedNodeId={selectedNode?.id || null} onSelectNode={setSelectedNode} />
                </div>
                <div className="min-h-0 border-l border-border/40 bg-white/60 px-5 py-5">
                  {selectedNode ? (
                    <div className="space-y-4">
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.selected')}</div>
                        <div className="mt-2 text-base font-semibold text-foreground">{selectedNode.label}</div>
                        <div className="mt-1 text-xs text-muted-foreground">{selectedNode.kind} · {selectedNode.status}</div>
                      </div>
                      {selectedNode.resultPreview && (
                        <div>
                          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.result')}</div>
                          <div className="mt-2 rounded-2xl border border-border/50 bg-background/80 px-3 py-3 text-sm leading-6 text-foreground">
                            {selectedNode.resultPreview}
                          </div>
                        </div>
                      )}
                      {selectedNode.error && (
                        <div>
                          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.error')}</div>
                          <div className="mt-2 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-3 text-sm leading-6 text-rose-700">
                            {selectedNode.error}
                          </div>
                        </div>
                      )}
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">{t('chat.trace.metadata')}</div>
                        <pre className="mt-2 overflow-x-auto rounded-2xl border border-border/50 bg-background/80 p-3 text-xs leading-6 text-muted-foreground">
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
