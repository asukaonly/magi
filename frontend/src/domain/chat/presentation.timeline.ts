import type { ChatTimelineMessage, ChatTimelineReplyPreview } from './state';
import type { ProjectedChatTimelineMessage } from './presentation.types';
import { getChatPresentationSurface } from './presentation.control';
import {
  projectExecutionProgressPresentation,
  projectTraceEntryPresentation,
  type ChatTimelineExecutionProjectionInput,
} from './presentation.execution';

const shouldShowUserTraceStatus = (message: ChatTimelineMessage): boolean => {
  if (message.role !== 'user' || !message.traceSummary) {
    return false;
  }

  const traceStatus = String(message.traceSummary.status || '').trim();
  return traceStatus === 'interrupted' || traceStatus === 'merged';
};

export const buildReplyPreviewFromMessage = (
  message: ChatTimelineMessage,
): ChatTimelineReplyPreview | null => {
  const messageId = String(message.messageId || '').trim();
  if (!messageId) {
    return null;
  }
  const excerpt = String(message.content || '').trim();
  return {
    messageId,
    role: message.role,
    messageKind: message.messageKind || null,
    contentExcerpt: excerpt.length > 140 ? `${excerpt.slice(0, 137)}...` : excerpt,
  };
};

export const projectChatTimelineMessage = (
  message: ChatTimelineMessage,
): ProjectedChatTimelineMessage => {
  const surface = getChatPresentationSurface(message);
  if (surface === 'control_status') {
    return {
      message,
      surface,
    };
  }
  if (surface === 'runtime_status') {
    return {
      message,
      surface,
      executionProgress: null,
    };
  }

  const isAssistantInterim = message.role === 'assistant' && message.messageKind === 'assistant_interim';
  const isAskRequest = message.messageKind === 'ask_request';
  const rhythmPayload = message.payload?.rhythm;
  const rhythmSegmentIndex = rhythmPayload && typeof rhythmPayload === 'object'
    ? Number((rhythmPayload as Record<string, unknown>).segment_index ?? 0)
    : 0;
  const rhythmSegmentCount = rhythmPayload && typeof rhythmPayload === 'object'
    ? Number((rhythmPayload as Record<string, unknown>).segment_count ?? 0)
    : 0;
  const isSecondaryRhythmSegment = message.role === 'assistant'
    && message.messageKind === 'assistant_rhythm_segment'
    && rhythmSegmentIndex > 0;
  const isNonTerminalRhythmSegment = message.role === 'assistant'
    && message.messageKind === 'assistant_rhythm_segment'
    && Number.isInteger(rhythmSegmentIndex)
    && Number.isInteger(rhythmSegmentCount)
    && rhythmSegmentCount > 0
    && rhythmSegmentIndex < rhythmSegmentCount - 1;
  const hasRecalledMemories = message.role === 'assistant'
    && (
      (Array.isArray(message.recalledMemories) && message.recalledMemories.length > 0)
      || message.recalledMemorySummary?.canClaimTotal === true
    );
  const replyPreview = isAskRequest ? null : buildReplyPreviewFromMessage(message);
  const canQuickLabel = !isAskRequest && message.role === 'assistant' && Boolean(String(message.messageId || '').trim());
  const showReactionBadge = message.role === 'user'
    && Boolean(message.reaction)
    && message.label?.text !== message.reaction;
  const showReplyStrip = Boolean(message.replyTo);
  const showAttachments = Array.isArray(message.attachments) && message.attachments.length > 0;
  const showMessageLabel = Boolean(message.label);
  const showUserTraceStatus = shouldShowUserTraceStatus(message);
  const traceEntry = projectTraceEntryPresentation(message);

  return {
    message,
    surface: 'transcript',
    transcript: {
      showHeaderTraceEntry: message.role === 'assistant' && !isAskRequest && !isAssistantInterim && !isSecondaryRhythmSegment,
      showExecutionBubbleFooter: isAssistantInterim,
      showRecalledMemories: hasRecalledMemories && !isNonTerminalRhythmSegment,
      bubbleTop: {
        replyTo: message.replyTo ?? null,
        attachments: message.attachments,
        showReplyStrip,
        showAttachments,
      },
      belowBubble: {
        reactionText: message.reaction ?? null,
        showReactionBadge,
        label: message.label ?? null,
        showMessageLabel,
        showUserTraceStatus,
      },
      actions: {
        replyPreview,
        canQuickLabel,
      },
      traceEntry,
      executionProgress: null,
    },
  };
};

export const projectChatTimelineRow = (
  message: ChatTimelineMessage,
  execution: ChatTimelineExecutionProjectionInput,
): ProjectedChatTimelineMessage => {
  const projected = projectChatTimelineMessage(message);
  const turnId = String(message.turnId || '').trim();
  const summary = turnId ? execution.summaries[turnId] : undefined;

  if (projected.surface === 'runtime_status') {
    return {
      ...projected,
      executionProgress: projectExecutionProgressPresentation(message, {
        executionControlByTurnId: execution.executionControlByTurnId,
        cancellingTurnIds: execution.cancellingTurnIds,
        detachingTurnIds: execution.detachingTurnIds,
        summary,
        variant: 'card',
      }),
    };
  }

  if (projected.surface === 'transcript' && projected.transcript.showExecutionBubbleFooter) {
    const isInterimFinalized = Boolean(
      turnId && execution.finalizedTurnIds && execution.finalizedTurnIds.has(turnId),
    );
    if (isInterimFinalized) {
      return projected;
    }
    return {
      ...projected,
      transcript: {
        ...projected.transcript,
        traceEntry: projectTraceEntryPresentation(message, summary),
        executionProgress: projectExecutionProgressPresentation(message, {
          executionControlByTurnId: execution.executionControlByTurnId,
          cancellingTurnIds: execution.cancellingTurnIds,
          detachingTurnIds: execution.detachingTurnIds,
          summary,
          variant: 'bubble',
        }),
      },
    };
  }

  if (projected.surface === 'transcript') {
    return {
      ...projected,
      transcript: {
        ...projected.transcript,
        traceEntry: projectTraceEntryPresentation(message, summary),
      },
    };
  }

  return projected;
};
