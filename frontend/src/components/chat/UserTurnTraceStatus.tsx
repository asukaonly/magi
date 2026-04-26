import type { ReactNode } from 'react';
import type { ChatTimelineMessage } from '@/domain/chat/state';

type UserTurnTraceStatusProps = {
  message: ChatTimelineMessage;
  traceEntry?: ReactNode;
};

export const UserTurnTraceStatus = ({ message, traceEntry }: UserTurnTraceStatusProps) => {
  if (!message.traceSummary) {
    return null;
  }

  return (
    <div className="mt-2 flex justify-end">
      <div className="flex max-w-[75%] items-center gap-3 rounded-xl border border-border/35 bg-background px-3 py-2">
        <span className="text-xs text-muted-foreground">{message.traceSummary.headline}</span>
        {traceEntry}
      </div>
    </div>
  );
};