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

  return (
    <button
      type="button"
      data-trace-variant="default"
      aria-label={label}
      title={label}
      onClick={(event: MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        onOpenTraceDrawer(turnId);
      }}
      className="inline-flex items-center text-[11px] font-medium text-muted-foreground/55 transition-colors hover:text-muted-foreground"
    >
      {label}
    </button>
  );
};