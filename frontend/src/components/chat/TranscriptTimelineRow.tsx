import { useTranslation } from 'react-i18next';
import type { ProjectedChatTimelineMessage } from '@/domain/chat/presentation';
import { formatChatClockTime } from '@/domain/chat/timestamps';
import { ChatRoleAvatar } from './ChatRoleAvatar';
import { MessageLabelBadge } from './MessageLabelBadge';
import type {
  TimelineAssistantIdentity,
  TimelineRowSharedProps,
  TranscriptTimelineInteractions,
} from './TimelineRowShared';
import { TraceEntryButton } from './TraceEntryButton';
import { TranscriptBubbleTop } from './TranscriptBubbleTop';
import { TimelineExecutionPanel } from './TimelineExecutionPanel';
import { TranscriptHeaderActions } from './TranscriptHeaderActions';
import { TranscriptTimelineMessage } from './TranscriptTimelineMessage';
import { UserTurnTraceStatus } from './UserTurnTraceStatus';

const resolveTranscriptContent = (
  message: ProjectedChatTimelineMessage['message'],
  t: (key: string, values?: Record<string, unknown>) => string,
): string => {
  const payload = message.payload && typeof message.payload === 'object'
    ? message.payload as Record<string, unknown>
    : null;
  const backgroundTaskId = String(payload?.background_task_id || '').trim();
  const backgroundTaskTitle = String(payload?.background_task_title || '').trim();
  const backgroundTaskStatus = String(payload?.background_task_status || '').trim().toLowerCase();

  if (
    message.role === 'assistant'
    && message.messageKind === 'assistant_final'
    && Boolean(String(message.turnId || '').trim())
    && backgroundTaskId
    && backgroundTaskTitle
    && !backgroundTaskStatus
  ) {
    return t('chat.backgroundTask.startedMessage', { title: backgroundTaskTitle });
  }

  return message.content;
};

const resolveAssistantIdentity = (
  assistant: TimelineAssistantIdentity,
  personaId: string | null | undefined,
): TimelineAssistantIdentity => {
  const normalizedPersonaId = String(personaId || '').trim();
  const persona = normalizedPersonaId ? assistant.personas?.[normalizedPersonaId] : undefined;
  if (!persona) {
    return assistant;
  }
  return {
    name: persona.name || assistant.name,
    avatar: persona.avatar || '',
    personas: assistant.personas,
  };
};

type TranscriptTimelineRowProps = TimelineRowSharedProps & {
  projectedMessage: Extract<ProjectedChatTimelineMessage, { surface: 'transcript' }>;
  interactions: TranscriptTimelineInteractions;
};

export const TranscriptTimelineRow = ({
  projectedMessage,
  assistant,
  shouldReduceMotion,
  execution,
  interactions,
}: TranscriptTimelineRowProps) => {
  const { t, i18n } = useTranslation('app');
  const traceEntryLabel = t('chat.trace.view');
  const message = projectedMessage.message;
  const transcript = projectedMessage.transcript;
  const content = resolveTranscriptContent(message, t);
  const messageAssistant = message.role === 'assistant'
    ? resolveAssistantIdentity(assistant, message.personaId)
    : assistant;

  return (
    <TranscriptTimelineMessage
      message={message}
      content={content}
      assistantName={messageAssistant.name}
      userNameLabel={t('chat.you')}
      timestampLabel={formatChatClockTime(message.timestamp, i18n.language)}
      shouldReduceMotion={shouldReduceMotion}
      avatar={<ChatRoleAvatar role={message.role} assistantName={messageAssistant.name} assistantAvatar={messageAssistant.avatar} />}
      headerExtras={(
        <TranscriptHeaderActions
          message={message}
          replyPreview={transcript.actions.replyPreview}
          canQuickLabel={transcript.actions.canQuickLabel}
          showHeaderTraceEntry={transcript.showHeaderTraceEntry}
          traceEntry={transcript.traceEntry}
          traceEntryLabel={traceEntryLabel}
          labelPopoverState={interactions.labelPopoverState}
          labelPopoverDraft={interactions.labelPopoverDraft}
          labelPopoverRef={interactions.labelPopoverRef}
          onSetReplyTarget={interactions.onSetReplyTarget}
          onOpenTraceDrawer={execution.onOpenTraceDrawer}
          onCloseLabelPopover={interactions.onCloseLabelPopover}
          onCloseMessageContextMenu={interactions.onCloseMessageContextMenu}
          onOpenLabelPopover={interactions.onOpenLabelPopover}
          onApplyLabelToMessage={interactions.onApplyLabelToMessage}
          onLabelDraftChange={interactions.onLabelDraftChange}
          onLabelDraftCompositionStart={interactions.onLabelDraftCompositionStart}
          onLabelDraftCompositionEnd={interactions.onLabelDraftCompositionEnd}
        />
      )}
      bubbleTop={(
        <TranscriptBubbleTop
          align={message.role}
          replyTo={transcript.bubbleTop.replyTo}
          attachments={transcript.bubbleTop.attachments}
          currentSessionId={interactions.currentSessionId}
          showReplyStrip={transcript.bubbleTop.showReplyStrip}
          showAttachments={transcript.bubbleTop.showAttachments}
          onOpenImagePreview={interactions.onOpenImagePreview}
        />
      )}
      bubbleFooter={transcript.showExecutionBubbleFooter
        ? (
          <TimelineExecutionPanel
            executionProgress={transcript.executionProgress}
            variant="bubble"
            execution={execution}
          />
        )
        : null}
      belowBubble={(
        <>
          {transcript.belowBubble.showReactionBadge && (
            <div className="mt-2 flex justify-end">
              <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full border border-border/60 bg-background px-2 text-sm shadow-sm">
                {transcript.belowBubble.reactionText}
              </span>
            </div>
          )}
          <MessageLabelBadge
            align={message.role}
            label={transcript.belowBubble.label}
            showLabel={transcript.belowBubble.showMessageLabel}
          />
          {transcript.belowBubble.showUserTraceStatus ? (
            <UserTurnTraceStatus
              message={message}
              traceEntry={(
                <TraceEntryButton
                  traceEntry={transcript.traceEntry}
                  label={traceEntryLabel}
                  onOpenTraceDrawer={execution.onOpenTraceDrawer}
                />
              )}
            />
          ) : null}
        </>
      )}
      onContextMenu={(event) => {
        event.preventDefault();
        event.stopPropagation();
        interactions.onCloseLabelPopover();
        interactions.onOpenMessageContextMenu(message, {
          x: Math.max(16, event.clientX),
          y: Math.max(16, event.clientY),
        });
      }}
    />
  );
};