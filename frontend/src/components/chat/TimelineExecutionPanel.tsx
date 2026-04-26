import { useTranslation } from 'react-i18next';
import type { ProjectedExecutionProgressPresentation } from '@/domain/chat/presentation';
import type { TimelineExecutionBindings } from './TimelineRowShared';
import { ExecutionProgressPanel } from './ExecutionProgressPanel';
import { TraceEntryButton } from './TraceEntryButton';

type TimelineExecutionPanelProps = {
  executionProgress: ProjectedExecutionProgressPresentation | null;
  variant: 'card' | 'bubble';
  execution: TimelineExecutionBindings;
};

export const TimelineExecutionPanel = ({
  executionProgress,
  variant,
  execution,
}: TimelineExecutionPanelProps) => {
  const { t } = useTranslation('app');
  const traceEntryLabel = t('chat.trace.view');
  const turnId = executionProgress?.turnId ?? null;

  if (!executionProgress || !turnId) {
    return null;
  }

  return (
    <ExecutionProgressPanel
      variant={variant}
      presentation={executionProgress}
      traceEntry={(
        <TraceEntryButton
          traceEntry={executionProgress.traceEntry}
          label={traceEntryLabel}
          onOpenTraceDrawer={execution.onOpenTraceDrawer}
        />
      )}
      onCancel={() => void execution.onRequestRunCancel(turnId)}
      onDetach={() => void execution.onRequestRunDetach(turnId)}
    />
  );
};