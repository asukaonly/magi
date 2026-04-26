import type { ProjectedChatTimelineMessage } from '@/domain/chat/presentation';
import { ChatRoleAvatar } from './ChatRoleAvatar';
import { ControlStatusCard } from './ControlStatusCard';
import { RuntimeStatusCard } from './RuntimeStatusCard';
import type { TimelineRowSharedProps } from './TimelineRowShared';
import { TimelineExecutionPanel } from './TimelineExecutionPanel';

type StatusTimelineRowProps = TimelineRowSharedProps & {
  projectedMessage: Exclude<ProjectedChatTimelineMessage, { surface: 'transcript' }>;
};

export const StatusTimelineRow = ({
  projectedMessage,
  assistant,
  shouldReduceMotion,
  execution,
}: StatusTimelineRowProps) => {
  const message = projectedMessage.message;

  if (projectedMessage.surface === 'control_status') {
    return <ControlStatusCard message={message} shouldReduceMotion={shouldReduceMotion} />;
  }

  return (
    <RuntimeStatusCard
      message={message}
      shouldReduceMotion={shouldReduceMotion}
      avatar={<ChatRoleAvatar role="assistant" assistantName={assistant.name} assistantAvatar={assistant.avatar} />}
      executionPanel={(
        <TimelineExecutionPanel
          executionProgress={projectedMessage.executionProgress}
          variant="card"
          execution={execution}
        />
      )}
    />
  );
};