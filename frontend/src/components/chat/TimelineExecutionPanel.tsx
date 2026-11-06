import { useTranslation } from 'react-i18next';
import type { ProjectedExecutionProgressPresentation } from '@/domain/chat/presentation';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import { isPendingRunState } from '@/domain/chat/run-state';
import type { TimelineExecutionBindings } from './TimelineRowShared';
import { AssistantRuntimePanel } from './AssistantRuntimePanel';
import { ExecutionProgressPanel, ExecutionRunActions } from './ExecutionProgressPanel';
import { TraceEntryButton } from './TraceEntryButton';

type TimelineExecutionPanelProps = {
  message: ChatTimelineMessage;
  executionProgress: ProjectedExecutionProgressPresentation | null;
  variant: 'card' | 'bubble';
  execution: TimelineExecutionBindings;
  shouldReduceMotion: boolean;
};

export const TimelineExecutionPanel = ({
  message, executionProgress, variant, execution, shouldReduceMotion,
}: TimelineExecutionPanelProps) => {
  const { t } = useTranslation('app');
  const turnId = executionProgress?.turnId;
  if (!executionProgress || !turnId) return null;

  const isInterim = message.messageKind === 'assistant_interim';
  const active = isPendingRunState(executionProgress.executionState)
    && (Boolean(message.streaming) || message.kind === 'status' || isInterim);
  const showProgress = active && (message.kind === 'status' || isInterim || !message.content.trim());
  const needsAttention = !['running', 'queued', 'completed'].includes(executionProgress.executionState);
  const runtimeStatuses = isInterim && message.content.trim()
    ? [{ source: 'assistant_interim', content: message.content }, ...(message.runtimeStatuses ?? [])]
    : message.runtimeStatuses;
  const hasRuntime = Boolean(runtimeStatuses?.length || message.reasoning?.length || message.toolCalls?.length);
  const hasDetails = hasRuntime || ((active || isInterim || variant === 'card') && Boolean(message.traceSummary || executionProgress.traceEntry.canOpen));
  const traceEntry = executionProgress.traceEntry.canOpen ? (
    <TraceEntryButton traceEntry={executionProgress.traceEntry} label={t('chat.trace.view')} onOpenTraceDrawer={execution.onOpenTraceDrawer} />
  ) : null;
  const actions = active ? (
    <ExecutionRunActions
      presentation={executionProgress}
      onCancel={() => void execution.onRequestRunCancel(turnId)}
      onDetach={() => void execution.onRequestRunDetach(turnId)}
    />
  ) : null;

  if (!active && !needsAttention && !hasDetails) return null;

  return (
    <div data-testid={`chat-execution-panel-${turnId}`}>
      {needsAttention && (
        <ExecutionProgressPanel
          variant="card"
          presentation={executionProgress}
          traceEntry={traceEntry}
          onCancel={() => void execution.onRequestRunCancel(turnId)}
          onDetach={() => void execution.onRequestRunDetach(turnId)}
        />
      )}
      <AssistantRuntimePanel
        runtimeStatuses={runtimeStatuses}
        reasoning={message.reasoning}
        toolCalls={message.toolCalls}
        streaming={active}
        showProgress={showProgress && !needsAttention}
        progressText={turnId === 'bootstrap-init-pending' ? message.content : undefined}
        shouldReduceMotion={shouldReduceMotion}
        actions={needsAttention ? undefined : actions}
      >
        {hasDetails && !needsAttention ? (
          <>
            <ExecutionProgressPanel variant="card" presentation={executionProgress} showActions={false} />
            {traceEntry}
          </>
        ) : null}
      </AssistantRuntimePanel>
    </div>
  );
};
