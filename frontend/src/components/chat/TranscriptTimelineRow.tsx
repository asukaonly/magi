import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProjectedChatTimelineMessage } from '@/domain/chat/presentation';
import { formatChatClockTime } from '@/domain/chat/timestamps';
import { useConversationStore } from '@/stores/conversation-store';
import { useDelegationsStore, type DelegationCardState } from '@/stores/delegations-store';
import { ChatRoleAvatar } from './ChatRoleAvatar';
import { DelegationCard } from './DelegationCard';
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
  delegationCard: DelegationCardState | null,
): string => {
  const payload = message.payload && typeof message.payload === 'object'
    ? message.payload as Record<string, unknown>
    : null;
  const backgroundTaskId = String(payload?.background_task_id || '').trim();

  // Check if this message has an associated delegation
  const hasDelegation = backgroundTaskId && delegationCard;

  // Check if delegation has finished
  const isDelegationTerminal = delegationCard?.lifecycle === 'finished'
    || delegationCard?.lifecycle === 'failed'
    || delegationCard?.lifecycle === 'cancelled'
    || delegationCard?.lifecycle === 'applied'
    || delegationCard?.lifecycle === 'discarded';

  // When delegation is finished, show the summary as the message content
  if (hasDelegation && isDelegationTerminal) {
    const summary = delegationCard?.result?.summary;
    if (summary) {
      return summary;
    }
  }

  // Default: show original content
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
  isLastAssistant?: boolean;
};

export const TranscriptTimelineRow = ({
  projectedMessage,
  assistant,
  shouldReduceMotion,
  execution,
  interactions,
  isLastAssistant = false,
}: TranscriptTimelineRowProps) => {
  const { t, i18n } = useTranslation('app');
  const traceEntryLabel = t('chat.trace.view');
  const message = projectedMessage.message;
  const transcript = projectedMessage.transcript;

  const sessionId = interactions.currentSessionId;
  const delegationCards = useDelegationsStore((state) =>
    sessionId ? state.delegationsBySession[sessionId] ?? null : null,
  );

  // Find matching delegation card for this message (by background_task_id -> delegation_id)
  const backgroundTaskId = message.payload && typeof message.payload === 'object'
    ? String((message.payload as Record<string, unknown>).background_task_id || '').trim()
    : '';
  const matchingDelegation = backgroundTaskId && delegationCards?.[backgroundTaskId]
    ? delegationCards[backgroundTaskId]
    : null;

  // Debug: log when message has background_task_id but no matching delegation
  if (backgroundTaskId && !matchingDelegation) {
    console.log('[TranscriptTimelineRow] Message has background_task_id but no matching delegation', {
      backgroundTaskId,
      delegationCardsKeys: delegationCards ? Object.keys(delegationCards) : [],
      messageId: message.id,
    });
  }
  // Debug: log when message has background_task_id and matching delegation
  if (backgroundTaskId && matchingDelegation) {
    console.log('[TranscriptTimelineRow] Message has background_task_id with matching delegation', {
      backgroundTaskId,
      lifecycle: matchingDelegation.lifecycle,
      messageId: message.id,
    });
  }

  const messageContent = resolveTranscriptContent(message, matchingDelegation);
  const messageAssistant = message.role === 'assistant'
    ? resolveAssistantIdentity(assistant, message.personaId)
    : assistant;

  // Check if this message has an associated delegation (running or finished)
  const hasAssociatedDelegation = Boolean(matchingDelegation);

  const workspacePath = useConversationStore((state) =>
    sessionId ? state.sessionsById[sessionId]?.workspace_path ?? null : null,
  );
  const delegationIds = useMemo(() => {
    if (!delegationCards) return [];

    // If this message has an associated delegation, show only that card
    if (hasAssociatedDelegation && matchingDelegation) {
      return [matchingDelegation.delegation_id];
    }

    // Otherwise, if we're the last assistant message, show all relevant cards
    const showDelegationCards = isLastAssistant && message.role === 'assistant' && Boolean(sessionId);
    if (!showDelegationCards) return [];

    const allIds = Object.keys(delegationCards);
    // Filter out discarded cards initially
    const activeIds = allIds.filter((did) => {
      const card = delegationCards[did];
      return card?.lifecycle !== 'discarded';
    });
    // For finished cards, only show the most recent one
    const finishedIds = activeIds.filter((did) => {
      const card = delegationCards[did];
      return card?.lifecycle === 'finished' || card?.lifecycle === 'applied';
    });
    // Running cards: show ALL of them (not just the most recent) during execution
    const runningIds = activeIds.filter((did) => {
      const card = delegationCards[did];
      return card?.lifecycle === 'started' || card?.lifecycle === 'running' || card?.lifecycle === 'cancelled' || card?.lifecycle === 'failed';
    });

    const allIds = Object.keys(delegationCards);
    // Filter out discarded cards initially
    const activeIds = allIds.filter((did) => {
      const card = delegationCards[did];
      return card?.lifecycle !== 'discarded';
    });
    // For finished cards, only show the most recent one
    const finishedIds = activeIds.filter((did) => {
      const card = delegationCards[did];
      return card?.lifecycle === 'finished' || card?.lifecycle === 'applied';
    });
    const runningIds = activeIds.filter((did) => {
      const card = delegationCards[did];
      return card?.lifecycle === 'started' || card?.lifecycle === 'running' || card?.lifecycle === 'cancelled' || card?.lifecycle === 'failed';
    });
    // Keep only the most recent finished card
    if (finishedIds.length > 1) {
      finishedIds.splice(0, finishedIds.length - 1);
    }
    // Include discarded cards only when there are no active ones (for visual feedback)
    const discardedIds = allIds.filter((did) => {
      const card = delegationCards[did];
      return card?.lifecycle === 'discarded';
    });
    const visibleDiscarded = (runningIds.length > 0 || finishedIds.length > 0) ? [] : discardedIds.slice(-1);
    return [...runningIds, ...finishedIds, ...visibleDiscarded];
  }, [delegationCards, hasAssociatedDelegation, matchingDelegation, isLastAssistant, message.role, sessionId]);

  // Check if the associated delegation is running
  const isAssociatedDelegationRunning = matchingDelegation?.lifecycle === 'started'
    || matchingDelegation?.lifecycle === 'running';

  // Check if we have any delegation cards at all
  const hasAnyDelegationCards = delegationIds.length > 0;

  // Render delegation cards
  const renderDelegationCards = (aboveMessage = false) => {
    if (!sessionId) return null;
    return (
      <div className={`${aboveMessage ? 'mb-2' : 'mt-2'} space-y-2`}>
        {delegationIds.map((did) => (
          <DelegationCard
            key={did}
            sessionId={sessionId}
            delegationId={did}
            workspace={workspacePath}
          />
        ))}
      </div>
    );
  };

  return (
    <>
      {/* Show delegation cards above message when there are any delegation cards */}
      {hasAnyDelegationCards && sessionId && renderDelegationCards(true)}

      {/* Show message bubble when delegation is finished, or when there's no associated delegation */}
      {(!isAssociatedDelegationRunning || !hasAssociatedDelegation) && (
        <TranscriptTimelineMessage
          message={message}
          content={messageContent}
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
          belowBubble={(
            <>
              {transcript.showExecutionBubbleFooter && (
                <TimelineExecutionPanel
                  executionProgress={transcript.executionProgress}
                  variant="bubble"
                  execution={execution}
                />
              )}
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
      )}
    </>
  );
};