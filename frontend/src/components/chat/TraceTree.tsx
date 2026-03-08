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
  if (kind === 'planning') return <Workflow className="h-4 w-4" />;
  if (kind === 'parallel_group') return <GitBranch className="h-4 w-4" />;
  if (kind === 'worker') return <Layers3 className="h-4 w-4" />;
  if (kind === 'tool') return <Hammer className="h-4 w-4" />;
  return <ChevronRight className="h-4 w-4" />;
};

const TraceTreeNode: React.FC<TraceTreeProps> = ({ node, selectedNodeId, onSelectNode, depth = 0 }) => {
  const [open, setOpen] = React.useState(depth < 2 || node.status === 'running');
  const hasChildren = node.children.length > 0;

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => {
          onSelectNode(node);
          if (hasChildren) {
            setOpen((prev) => !prev);
          }
        }}
        className={cn(
          'w-full rounded-2xl border px-3 py-3 text-left transition-colors',
          selectedNodeId === node.id ? 'border-primary/35 bg-primary/10' : 'border-border/50 bg-card/70 hover:bg-muted/40'
        )}
        style={{ marginLeft: `${depth * 14}px` }}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex shrink-0 items-center gap-1 text-muted-foreground">
            {hasChildren && (
              <ChevronRight className={cn('h-4 w-4 transition-transform', open && 'rotate-90')} />
            )}
            {!hasChildren && <span className="inline-block w-4" />}
            {kindIcon(node.kind)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium text-foreground">{node.label}</span>
              <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]', statusTone[node.status] || statusTone.pending)}>
                {statusIcon(node.status)}
                {node.status}
              </span>
            </div>
            {node.resultPreview && (
              <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{node.resultPreview}</div>
            )}
            {node.error && (
              <div className="mt-1 text-xs text-rose-600">{node.error}</div>
            )}
          </div>
        </div>
      </button>
      {hasChildren && open && (
        <div className="space-y-2">
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

const TraceTree: React.FC<TraceTreeProps> = (props) => <TraceTreeNode {...props} />;

export default TraceTree;
