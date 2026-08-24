import React from 'react';
import { Brain, CheckCircle2, ChevronRight, CircleDashed, GitBranch, Hammer, Layers3, MessageSquare, RefreshCw, Search, ShieldCheck, Sparkles, Workflow, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { NormalizedExecutionTraceNode } from '@/domain/chat/state';
import { formatTraceKind, formatTraceLabel, formatTraceStatus } from './traceDisplay';

interface TraceTreeProps {
  node: NormalizedExecutionTraceNode;
  selectedNodeId: string | null;
  onSelectNode: (node: NormalizedExecutionTraceNode) => void;
  depth?: number;
}

const statusTone: Record<string, string> = {
  completed: 'text-[hsl(var(--trace-status-completed-fg))] bg-[hsl(var(--trace-status-completed-bg))] border-[hsl(var(--trace-status-completed-border))]',
  running: 'text-[hsl(var(--trace-status-running-fg))] bg-[hsl(var(--trace-status-running-bg))] border-[hsl(var(--trace-status-running-border))]',
  pending: 'text-[hsl(var(--trace-status-pending-fg))] bg-[hsl(var(--trace-status-pending-bg))] border-[hsl(var(--trace-status-pending-border))]',
  failed: 'text-[hsl(var(--trace-status-failed-fg))] bg-[hsl(var(--trace-status-failed-bg))] border-[hsl(var(--trace-status-failed-border))]',
  blocked: 'text-[hsl(var(--trace-status-failed-fg))] bg-[hsl(var(--trace-status-failed-bg))] border-[hsl(var(--trace-status-failed-border))]',
  suspended: 'text-[hsl(var(--trace-status-pending-fg))] bg-[hsl(var(--trace-status-pending-bg))] border-[hsl(var(--trace-status-pending-border))]',
  cancelled: 'text-[hsl(var(--trace-status-pending-fg))] bg-[hsl(var(--trace-status-pending-bg))] border-[hsl(var(--trace-status-pending-border))]',
};

const statusIcon = (status: string) => {
  if (status === 'completed') return <CheckCircle2 className="h-4 w-4" />;
  if (status === 'failed' || status === 'blocked') return <XCircle className="h-4 w-4" />;
  if (status === 'running') return <CircleDashed className="h-4 w-4 animate-spin" />;
  return <CircleDashed className="h-4 w-4" />;
};

const kindIcon = (kind: string) => {
  if (kind === 'root') return <Layers3 className="h-4 w-4" />;
  if (kind === 'planning') return <Workflow className="h-4 w-4" />;
  if (kind === 'parallel_group') return <GitBranch className="h-4 w-4" />;
  if (kind === 'worker') return <Layers3 className="h-4 w-4" />;
  if (kind === 'tool' || kind === 'tool_call') return <Hammer className="h-4 w-4" />;
  if (kind === 'llm' || kind === 'llm_call') return <Brain className="h-4 w-4" />;
  if (kind === 'validation') return <ShieldCheck className="h-4 w-4" />;
  if (kind === 'repair') return <RefreshCw className="h-4 w-4" />;
  if (kind === 'reasoning') return <Brain className="h-4 w-4" />;
  if (kind === 'skill' || kind === 'skill_call') return <Sparkles className="h-4 w-4" />;
  if (kind === 'intent' || kind === 'intent_resolution') return <Search className="h-4 w-4" />;
  if (kind === 'response') return <MessageSquare className="h-4 w-4" />;
  return <Workflow className="h-4 w-4" />;
};

const nodeSubtitle = (node: NormalizedExecutionTraceNode): string => {
  const meta = node.metadata as Record<string, unknown> | undefined;
  if (!meta) return '';
  if (node.kind === 'tool' || node.kind === 'tool_call') {
    return String(meta.tool_name || '');
  }
  if (node.kind === 'llm' || node.kind === 'llm_call') {
    return String(meta.model || '');
  }
  if (node.kind === 'skill' || node.kind === 'skill_call') {
    return String(meta.skill_name || '');
  }
  return '';
};

const TraceTreeNode: React.FC<TraceTreeProps> = ({ node, selectedNodeId, onSelectNode, depth = 0 }) => {
  const { t } = useTranslation('app');
  const [open, setOpen] = React.useState(depth < 2 || node.status === 'running');
  const hasChildren = node.children.length > 0;
  const isToolNode = node.kind === 'tool' || node.kind === 'tool_call';
  const compact = depth >= 1;
  const selected = selectedNodeId === node.id;
  const subtitle = nodeSubtitle(node);
  const preview = isToolNode
    ? ''
    : (node.resultPreview || '').replace(/\s+/g, ' ').trim();

  return (
    <div className={cn('space-y-1.5', compact && 'space-y-1')}>
      <button
        type="button"
        onClick={() => {
          onSelectNode(node);
          if (hasChildren) {
            setOpen((prev) => !prev);
          }
        }}
        className={cn(
          'w-full text-left transition-colors',
          compact ? 'rounded-xl px-2.5 py-1.5' : 'rounded-xl px-3 py-2',
          selected
            ? 'bg-[hsl(var(--trace-selected))] ring-1 ring-[hsl(var(--trace-selected-border))]'
            : 'hover:bg-[hsl(var(--trace-surface-muted)/0.72)]',
          compact
            ? selected
              ? 'shadow-none'
              : 'border-transparent bg-transparent'
            : selected
              ? 'shadow-md'
              : 'bg-[hsl(var(--trace-card))]'
        )}
        style={{ marginLeft: `${depth * 4}px` }}
      >
        <div className={cn('flex items-start gap-3', compact && 'gap-2')}>
          <div className={cn('mt-0.5 flex shrink-0 items-center gap-2 text-muted-foreground', compact && 'gap-1.5')}>
            {hasChildren && (
              <ChevronRight className={cn('transition-transform', compact ? 'h-3.5 w-3.5' : 'h-4 w-4', open && 'rotate-90')} />
            )}
            {!hasChildren && <span className={cn('inline-block rounded-full bg-primary/30', compact ? 'h-1.5 w-1.5' : 'mt-1 h-2 w-2')} />}
            <span className={cn(
              'flex items-center justify-center rounded-xl border border-[hsl(var(--trace-icon-border))] bg-[hsl(var(--trace-icon-bg))] text-muted-foreground',
              compact ? 'h-7 w-7' : 'h-8 w-8'
            )}>
              {kindIcon(node.kind)}
            </span>
          </div>
          <div className="min-w-0 flex-1">
            <div className={cn('flex items-start gap-2', compact && 'items-center')}>
              <span className={cn(
                'min-w-0 flex-1 font-medium text-foreground',
                compact ? 'truncate text-[15px] leading-5.5' : 'text-[15px] leading-6'
              )}>
                {formatTraceLabel(node.label, node.kind, t)}
              </span>
              <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]', statusTone[node.status] || statusTone.pending, compact && 'px-1.5 py-0 text-[10px]')}>
                {statusIcon(node.status)}
                {formatTraceStatus(node.status, t)}
              </span>
            </div>
            <div className={cn('mt-0.5 text-muted-foreground', compact ? 'text-[12px] leading-4.5' : 'text-[12px] leading-5')}>
              {formatTraceKind(node.kind, t)}
              {subtitle && <span className="ml-1.5 text-muted-foreground/60">· {subtitle}</span>}
            </div>
            {preview && (
              <div className={cn(
                'mt-0.5 overflow-hidden text-ellipsis whitespace-nowrap text-muted-foreground',
                compact ? 'text-[12px] leading-5' : 'text-[13px] leading-5'
              )}>
                {preview}
              </div>
            )}
            {node.error && (
              <div className="mt-0.5 overflow-hidden text-ellipsis whitespace-nowrap text-xs text-[hsl(var(--trace-error-foreground))]">{node.error}</div>
            )}
          </div>
        </div>
      </button>
      {hasChildren && open && (
        <div
          className={cn(
            'space-y-0.5 border-l border-border/60 pl-3',
            'border-l-[hsl(var(--trace-border))]',
            compact && 'space-y-0.5 pl-3'
          )}
          style={{ marginLeft: `${depth * 4 + 18}px` }}
        >
          {node.children.map((child) => (
            <TraceTreeNode
              key={child.id}
              node={child}
              selectedNodeId={selectedNodeId}
              onSelectNode={onSelectNode}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
};

const TraceTree: React.FC<TraceTreeProps> = ({ node, selectedNodeId, onSelectNode }) => {
  if (node.kind === 'root') {
    return (
      <div className="space-y-2">
        {node.children.map((child) => (
          <TraceTreeNode
            key={child.id}
            node={child}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
            depth={0}
          />
        ))}
      </div>
    );
  }

  return <TraceTreeNode node={node} selectedNodeId={selectedNodeId} onSelectNode={onSelectNode} />;
};

export default TraceTree;
