import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isInteractionExpired, remainingInteractionSeconds } from '@/components/control/interaction-expiry';
import type { ProjectedChatTimelineMessage } from '@/domain/chat/presentation';
import { formatChatClockTime } from '@/domain/chat/timestamps';
import { useConversationStore } from '@/stores/conversation-store';
import { useDelegationsStore, type DelegationCardState } from '@/stores/delegations-store';
import { ChatRoleAvatar, type ChatAvatarState } from './ChatRoleAvatar';
import { RecalledMemoriesRow } from './RecalledMemoriesRow';
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

const numberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

const useInteractionNow = (expiresAtMs: number | null): number => {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!expiresAtMs) {
      return () => undefined;
    }
    setNowMs(Date.now());
    const handle = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(handle);
    };
  }, [expiresAtMs]);

  return nowMs;
};

const AskTranscriptBadge = ({
  message,
}: {
  message: ProjectedChatTimelineMessage['message'];
}) => {
  const { t } = useTranslation('control');
  const isAskRequest = message.messageKind === 'ask_request';
  const payload = isAskRequest && message.payload && typeof message.payload === 'object'
    ? message.payload as Record<string, unknown>
    : {};
  const status = String(payload.status || 'pending').trim().toLowerCase();
  const isAnswered = status === 'answered';
  const expiresAtMs = isAnswered ? null : numberOrNull(payload.expires_at_ms);
  const nowMs = useInteractionNow(expiresAtMs);
  const expired = isInteractionExpired(expiresAtMs, nowMs);
  const remainingSeconds = remainingInteractionSeconds(expiresAtMs, nowMs);
  const badgeLabel = isAnswered
    ? t('ask.answered')
    : remainingSeconds !== null
      ? (expired ? t('ask.expired') : t('ask.expires_in', { seconds: remainingSeconds }))
      : t('ask.title');

  if (!isAskRequest) {
    return null;
  }

  return (
    <span className="inline-flex h-5 items-center rounded-full border border-border/60 bg-muted/35 px-2 text-[11px] font-medium text-muted-foreground">
      {badgeLabel}
    </span>
  );
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

  const messageContent = resolveTranscriptContent(message, matchingDelegation);
  const messageAssistant = message.role === 'assistant'
    ? resolveAssistantIdentity(assistant, message.personaId)
    : assistant;
  // Only the latest assistant turn signals lifecycle through its avatar so
  // historical bubbles stay visually quiet. The mapping deliberately treats
  // unknown run states as "idle" rather than "static" — a finished but
  // current turn should still feel alive instead of frozen.
  const avatarState: ChatAvatarState = message.role !== 'assistant' || !isLastAssistant
    ? 'static'
    : message.streaming || message.runState?.state === 'running'
      ? 'streaming'
      : message.runState?.state === 'failed' || message.runState?.state === 'cancelled'
        ? 'failed'
        : 'idle';

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
          avatar={<ChatRoleAvatar role={message.role} assistantName={messageAssistant.name} assistantAvatar={messageAssistant.avatar} avatarState={avatarState} />}
          headerExtras={(
            <>
              <AskTranscriptBadge message={message} />
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
            </>
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
          bubbleFooter={(
            <>
              {transcript.showExecutionBubbleFooter ? (
                <TimelineExecutionPanel
                  executionProgress={transcript.executionProgress}
                  variant="bubble"
                  execution={execution}
                />
              ) : null}
            </>
          )}
          belowBubble={(
            <>
              {transcript.showRecalledMemories ? (
                <RecalledMemoriesRow
                  memories={message.recalledMemories ?? []}
                  summary={message.recalledMemorySummary}
                />
              ) : null}
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
            if (message.messageKind === 'ask_request') {
              return;
            }
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
