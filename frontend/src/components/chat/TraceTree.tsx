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
  const compact = depth >= 1;
  const selected = selectedNodeId === node.id;
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
          compact ? 'rounded-2xl px-2.5 py-1.5' : 'rounded-[20px] px-3 py-2',
          selected
            ? 'bg-emerald-50/90 ring-1 ring-emerald-200'
            : 'hover:bg-white/72',
          compact
            ? selected
              ? 'shadow-none'
              : 'border-transparent bg-transparent'
            : selected
              ? 'shadow-[0_18px_40px_-30px_rgba(45,151,140,0.35)]'
              : 'bg-white/78'
        )}
        style={{ marginLeft: `${depth * 4}px` }}
      >
        <div className={cn('flex items-start gap-3', compact && 'gap-2')}>
          <div className={cn('mt-0.5 flex shrink-0 items-center gap-2 text-muted-foreground', compact && 'gap-1.5')}>
            {hasChildren && (
              <ChevronRight className={cn('transition-transform', compact ? 'h-3.5 w-3.5' : 'h-4 w-4', open && 'rotate-90')} />
            )}
            {!hasChildren && <span className={cn('inline-block rounded-full bg-emerald-200', compact ? 'h-1.5 w-1.5' : 'mt-1 h-2 w-2')} />}
            <span className={cn(
              'flex items-center justify-center rounded-2xl border border-border/40 bg-white/92 text-muted-foreground',
              compact ? 'h-7 w-7 rounded-xl' : 'h-8 w-8'
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
                {node.label}
              </span>
              <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]', statusTone[node.status] || statusTone.pending, compact && 'px-1.5 py-0 text-[10px]')}>
                {statusIcon(node.status)}
                {node.status}
              </span>
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
              <div className="mt-0.5 overflow-hidden text-ellipsis whitespace-nowrap text-xs text-rose-600">{node.error}</div>
            )}
          </div>
        </div>
      </button>
      {hasChildren && open && (
        <div
          className={cn(
            'space-y-0.5 border-l border-emerald-200/90 pl-3',
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
