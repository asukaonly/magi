import React from 'react';
import { CheckCircle2, ChevronRight, CircleDashed, GitBranch, Hammer, Layers3, Workflow, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { NormalizedExecutionTraceNode } from '@/pages/chat-state';

interface TraceTreeProps {
  node: NormalizedExecutionTraceNode;
  selectedNodeId: string | null;
  onSelectNode: (node: NormalizedExecutionTraceNode) => void;
  depth?: number;
}

const statusTone: Record<string, string> = {
  completed: 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20',
  running: 'text-amber-700 bg-amber-500/10 border-amber-500/20',
  pending: 'text-slate-500 bg-slate-500/10 border-slate-500/20',
  failed: 'text-rose-600 bg-rose-500/10 border-rose-500/20',
};

const statusIcon = (status: string) => {
  if (status === 'completed') return <CheckCircle2 className="h-4 w-4" />;
  if (status === 'failed') return <XCircle className="h-4 w-4" />;
  if (status === 'running') return <CircleDashed className="h-4 w-4 animate-spin" />;
  return <CircleDashed className="h-4 w-4" />;
};

const kindIcon = (kind: string) => {
  if (kind === 'root') return <Layers3 className="h-4 w-4" />;
  if (kind === 'planning') return <Workflow className="h-4 w-4" />;
  if (kind === 'parallel_group') return <GitBranch className="h-4 w-4" />;
  if (kind === 'worker') return <Layers3 className="h-4 w-4" />;
  if (kind === 'tool') return <Hammer className="h-4 w-4" />;
  return <Workflow className="h-4 w-4" />;
};

const TraceTreeNode: React.FC<TraceTreeProps> = ({ node, selectedNodeId, onSelectNode, depth = 0 }) => {
  const [open, setOpen] = React.useState(depth < 2 || node.status === 'running');
  const hasChildren = node.children.length > 0;
  const isToolNode = node.kind === 'tool';
  const compact = isToolNode || depth >= 2;

  return (
    <div className={cn('space-y-2', compact && 'space-y-1.5')}>
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
          compact ? 'rounded-[20px] border px-3 py-2.5' : 'rounded-[22px] border px-3 py-3',
          selectedNodeId === node.id
            ? 'border-primary/35 bg-[linear-gradient(180deg,rgba(235,250,247,0.96),rgba(228,246,242,0.88))] shadow-[0_18px_40px_-28px_rgba(45,151,140,0.45)]'
            : 'border-border/50 bg-white/88 hover:bg-muted/35'
        )}
        style={{ marginLeft: `${depth * 8}px` }}
      >
        <div className={cn('flex items-start gap-3', compact && 'gap-2.5')}>
          <div className={cn('mt-0.5 flex shrink-0 items-center gap-2 text-muted-foreground', compact && 'gap-1.5')}>
            {hasChildren && (
              <ChevronRight className={cn('h-4 w-4 transition-transform', open && 'rotate-90')} />
            )}
            {!hasChildren && <span className="mt-1 inline-block h-2 w-2 rounded-full bg-border/80" />}
            <span className={cn(
              'flex items-center justify-center rounded-2xl border border-border/50 bg-background/90',
              compact ? 'h-7 w-7' : 'h-8 w-8'
            )}>
              {kindIcon(node.kind)}
            </span>
          </div>
          <div className="min-w-0 flex-1">
            <div className={cn('flex items-start gap-2', compact && 'items-center')}>
              <span className={cn(
                'min-w-0 flex-1 font-medium text-foreground',
                compact ? 'truncate text-[15px] leading-6' : 'text-sm leading-6'
              )}>
                {node.label}
              </span>
              <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]', statusTone[node.status] || statusTone.pending)}>
                {statusIcon(node.status)}
                {node.status}
              </span>
            </div>
            {node.resultPreview && (
              <div className={cn(
                'mt-1 text-muted-foreground',
                compact ? 'line-clamp-1 text-[12px] leading-5' : 'line-clamp-2 text-xs leading-5'
              )}>
                {node.resultPreview}
              </div>
            )}
            {node.error && (
              <div className="mt-1 text-xs text-rose-600">{node.error}</div>
            )}
          </div>
        </div>
      </button>
      {hasChildren && open && (
        <div
          className={cn(
            'space-y-2 border-l border-border/50 pl-3',
            compact && 'space-y-1.5 pl-2.5'
          )}
          style={{ marginLeft: `${depth * 8 + 18}px` }}
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
      <div className="space-y-2.5">
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
