import type { MouseEvent } from 'react';
import type { ProjectedTraceEntryPresentation } from '@/domain/chat/presentation';

type TraceEntryButtonProps = {
  traceEntry: ProjectedTraceEntryPresentation;
  label: string;
  onOpenTraceDrawer: (turnId: string) => void;
};

export const TraceEntryButton = ({
  traceEntry,
  label,
  onOpenTraceDrawer,
}: TraceEntryButtonProps) => {
  const turnId = traceEntry.turnId;

  if (!turnId || !traceEntry.canOpen) {
    return null;
  }

  const isProminent = traceEntry.variant === 'prominent';

  return (
    <button
      type="button"
      data-trace-variant={isProminent ? 'prominent' : 'default'}
      onClick={(event: MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        onOpenTraceDrawer(turnId);
      }}
      className="inline-flex items-center gap-1 rounded-full border border-border/50 bg-background/75 px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
    >
      {label}
    </button>
  );
};