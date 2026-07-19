import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { codeAgentApi } from '@/api/modules/codeAgent';
import { TranscriptTimelineRow } from '@/components/chat/TranscriptTimelineRow';
import { resetRealtimeChatProjectionRetirementForTests } from '@/realtime/chat-projection-retirement';
import { useConversationStore } from '@/stores/conversation-store';
import { useDelegationsStore } from '@/stores/delegations-store';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('@/runtime/desktop', () => ({
  openExternalUrl: vi.fn(),
}));

vi.mock('@/api/modules/codeAgent', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/codeAgent')>(
    '@/api/modules/codeAgent',
  );
  return {
    ...actual,
    codeAgentApi: {
      ...actual.codeAgentApi,
      getDelegation: vi.fn(),
    },
  };
});

const noop = vi.fn();
const SESSION_ID = 'session-1';
const TURN_ID = 'turn-delegation';
const DELEGATION_ID = 'a'.repeat(32);
const SECOND_DELEGATION_ID = 'b'.repeat(32);
const WORKSPACE = '/tmp/current-workspace';
const FIRST_TASK_WORKSPACE = '/tmp/historical-first-workspace';
const SECOND_TASK_WORKSPACE = '/tmp/historical-second-workspace';

const baseTranscript = {
  actions: {
    replyPreview: null,
    canQuickLabel: false,
  },
  showHeaderTraceEntry: false,
  traceEntry: null,
  bubbleTop: {
    replyTo: null,
    attachments: [],
    showReplyStrip: false,
    showAttachments: false,
  },
  showExecutionBubbleFooter: false,
  executionProgress: null,
  belowBubble: {
    showReactionBadge: false,
    reactionText: '',
    label: null,
    showMessageLabel: false,
    showUserTraceStatus: false,
  },
};

const createTranscriptRow = (
  message: Record<string, unknown>,
  isLastAssistant = false,
) => (
  <TranscriptTimelineRow
    projectedMessage={{
      surface: 'transcript',
      message,
      transcript: baseTranscript,
    } as any}
    assistant={{ name: 'Magi', avatar: '' }}
    shouldReduceMotion
    execution={{
      summaries: {},
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: [],
      onOpenTraceDrawer: noop,
      onRequestRunCancel: noop,
      onRequestRunDetach: noop,
    }}
    interactions={{
      currentSessionId: SESSION_ID,
      labelPopoverState: null,
      labelPopoverDraft: '',
      labelPopoverRef: { current: null },
      onSetReplyTarget: noop,
      onOpenImagePreview: noop,
      onCloseLabelPopover: noop,
      onCloseMessageContextMenu: noop,
      onOpenLabelPopover: noop,
      onOpenMessageContextMenu: noop,
      onApplyLabelToMessage: noop,
      onLabelDraftChange: noop,
      onLabelDraftCompositionStart: noop,
      onLabelDraftCompositionEnd: noop,
    }}
    isLastAssistant={isLastAssistant}
  />
);

describe('TranscriptTimelineRow', () => {
  beforeEach(() => {
    vi.mocked(codeAgentApi.getDelegation).mockReset();
    useConversationStore.getState().reset();
    useDelegationsStore.getState().reset();
    resetRealtimeChatProjectionRetirementForTests();
  });

  afterEach(() => {
    useConversationStore.getState().reset();
    useDelegationsStore.getState().reset();
    resetRealtimeChatProjectionRetirementForTests();
  });

  it('does not reuse the active persona avatar when a historical persona has no avatar', () => {
    render(
      <TranscriptTimelineRow
        projectedMessage={{
          surface: 'transcript',
          message: {
            id: 'msg-asuka',
            role: 'assistant',
            kind: 'assistant',
            content: 'Stored persona answer',
            timestamp: 1777729177195,
            messageId: 'msg-asuka',
            messageKind: 'assistant_final',
            personaId: 'persona-asuka',
            turnId: 'turn-asuka',
          },
          transcript: baseTranscript,
        } as any}
        assistant={{
          name: 'Echo-01',
          avatar: 'https://example.test/echo.png',
          personas: {
            'persona-asuka': {
              name: '惣流·明日香·兰格雷',
              avatar: '',
            },
          },
        }}
        shouldReduceMotion
        execution={{
          summaries: {},
          executionControlByTurnId: {},
          cancellingTurnIds: [],
          detachingTurnIds: [],
          onOpenTraceDrawer: noop,
          onRequestRunCancel: noop,
          onRequestRunDetach: noop,
        }}
        interactions={{
          currentSessionId: 'session-1',
          labelPopoverState: null,
          labelPopoverDraft: '',
          labelPopoverRef: { current: null },
          onSetReplyTarget: noop,
          onOpenImagePreview: noop,
          onCloseLabelPopover: noop,
          onCloseMessageContextMenu: noop,
          onOpenLabelPopover: noop,
          onOpenMessageContextMenu: noop,
          onApplyLabelToMessage: noop,
          onLabelDraftChange: noop,
          onLabelDraftCompositionStart: noop,
          onLabelDraftCompositionEnd: noop,
        }}
      />,
    );

    expect(screen.getByText('惣流·明日香·兰格雷')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: '惣流·明日香·兰格雷' })).not.toBeInTheDocument();
    expect(screen.getByText('惣')).toBeInTheDocument();
  });

  it('renders recalled memories below the assistant bubble', () => {
    render(
      <TranscriptTimelineRow
        projectedMessage={{
          surface: 'transcript',
          message: {
            id: 'msg-memory',
            role: 'assistant',
            kind: 'assistant',
            content: 'Answer with memory',
            timestamp: 1777729177195,
            messageId: 'msg-memory',
            messageKind: 'assistant_final',
            turnId: 'turn-memory',
            recalledMemories: [{
              kind: 'event',
              sourceLayer: 'L1',
              statement: 'Visited example.com',
              topic: 'example.com',
            }],
          },
          transcript: {
            ...baseTranscript,
            showRecalledMemories: true,
          },
        } as any}
        assistant={{ name: 'Magi', avatar: '' }}
        shouldReduceMotion
        execution={{
          summaries: {},
          executionControlByTurnId: {},
          cancellingTurnIds: [],
          detachingTurnIds: [],
          onOpenTraceDrawer: noop,
          onRequestRunCancel: noop,
          onRequestRunDetach: noop,
        }}
        interactions={{
          currentSessionId: 'session-1',
          labelPopoverState: null,
          labelPopoverDraft: '',
          labelPopoverRef: { current: null },
          onSetReplyTarget: noop,
          onOpenImagePreview: noop,
          onCloseLabelPopover: noop,
          onCloseMessageContextMenu: noop,
          onOpenLabelPopover: noop,
          onOpenMessageContextMenu: noop,
          onApplyLabelToMessage: noop,
          onLabelDraftChange: noop,
          onLabelDraftCompositionStart: noop,
          onLabelDraftCompositionEnd: noop,
        }}
      />,
    );

    const bubble = screen.getByText('Answer with memory').closest('div.rounded-xl');
    const memoryDisclosure = screen.getByRole('button', { name: 'chat.recalledMemories.summary' });

    expect(bubble).not.toBeNull();
    expect(bubble).not.toContainElement(memoryDisclosure);
    expect(bubble?.parentElement).toContainElement(memoryDisclosure);
  });

  it('hydrates a persisted delegation after reopening a session with an empty runtime store', async () => {
    useConversationStore.getState().hydrateSessions([{
      session_id: SESSION_ID,
      title: 'Historical task',
      last_message_preview: '',
      last_user_message_preview: '',
      title_overridden: false,
      last_timestamp: 1,
      message_count: 1,
      workspace_path: WORKSPACE,
    }], SESSION_ID);
    vi.mocked(codeAgentApi.getDelegation).mockImplementation(async (
      _sessionId,
      delegationId,
    ) => ({
      result: {
        delegation_id: delegationId,
        success: true,
        exit_code: 0,
        duration_ms: 100,
        adapter: 'codex',
        diff_path: null,
        diff_stats: { files_changed: 0, additions: 0, deletions: 0 },
        files_changed: [],
        summary: delegationId === DELEGATION_ID
          ? 'Restored first task'
          : 'Restored second task',
        logs_path: '/tmp/logs',
        events_path: '/tmp/events',
        error: null,
        cost: null,
      },
      events_tail: [],
      diff_text: '',
    }));

    render(
      <TranscriptTimelineRow
        projectedMessage={{
          surface: 'transcript',
          message: {
            id: 'msg-delegation',
            role: 'assistant',
            kind: 'assistant',
            content: 'Task started',
            timestamp: 1777729177195,
            messageId: 'msg-delegation',
            messageKind: 'assistant_final',
            turnId: TURN_ID,
            payload: {
              code_agent_delegations: [
                {
                  delegation_id: DELEGATION_ID,
                  turn_id: 'turn-first',
                  workspace_path: FIRST_TASK_WORKSPACE,
                },
                {
                  delegation_id: SECOND_DELEGATION_ID,
                  turn_id: 'turn-second',
                  workspace_path: SECOND_TASK_WORKSPACE,
                },
              ],
            },
          },
          transcript: baseTranscript,
        } as any}
        assistant={{ name: 'Magi', avatar: '' }}
        shouldReduceMotion
        execution={{
          summaries: {},
          executionControlByTurnId: {},
          cancellingTurnIds: [],
          detachingTurnIds: [],
          onOpenTraceDrawer: noop,
          onRequestRunCancel: noop,
          onRequestRunDetach: noop,
        }}
        interactions={{
          currentSessionId: SESSION_ID,
          labelPopoverState: null,
          labelPopoverDraft: '',
          labelPopoverRef: { current: null },
          onSetReplyTarget: noop,
          onOpenImagePreview: noop,
          onCloseLabelPopover: noop,
          onCloseMessageContextMenu: noop,
          onOpenLabelPopover: noop,
          onOpenMessageContextMenu: noop,
          onApplyLabelToMessage: noop,
          onLabelDraftChange: noop,
          onLabelDraftCompositionStart: noop,
          onLabelDraftCompositionEnd: noop,
        }}
      />,
    );

    await waitFor(() => {
      expect(codeAgentApi.getDelegation).toHaveBeenCalledWith(
        SESSION_ID,
        DELEGATION_ID,
        FIRST_TASK_WORKSPACE,
      );
      expect(codeAgentApi.getDelegation).toHaveBeenCalledWith(
        SESSION_ID,
        SECOND_DELEGATION_ID,
        SECOND_TASK_WORKSPACE,
      );
    });
    await waitFor(() => {
      expect(screen.getByText('Restored first task')).toBeInTheDocument();
      expect(screen.getByText('Restored second task')).toBeInTheDocument();
    });
    expect(
      useDelegationsStore.getState()
        .delegationsBySession[SESSION_ID]?.[DELEGATION_ID]?.hydrated,
    ).toBe(true);
    expect(
      useDelegationsStore.getState()
        .delegationsBySession[SESSION_ID]?.[SECOND_DELEGATION_ID]?.hydrated,
    ).toBe(true);
    expect(
      useDelegationsStore.getState()
        .delegationsBySession[SESSION_ID]?.[DELEGATION_ID]?.turn_id,
    ).toBe('turn-first');
    expect(
      useDelegationsStore.getState()
        .delegationsBySession[SESSION_ID]?.[SECOND_DELEGATION_ID]?.turn_id,
    ).toBe('turn-second');
  });

  it('does not treat a normal background task id as a code delegation', () => {
    useConversationStore.getState().hydrateSessions([{
      session_id: SESSION_ID,
      title: 'Background task',
      last_message_preview: '',
      last_user_message_preview: '',
      title_overridden: false,
      last_timestamp: 1,
      message_count: 1,
      workspace_path: WORKSPACE,
    }], SESSION_ID);

    render(
      <TranscriptTimelineRow
        projectedMessage={{
          surface: 'transcript',
          message: {
            id: 'msg-background',
            role: 'assistant',
            kind: 'assistant',
            content: 'Background task started',
            timestamp: 1777729177195,
            messageId: 'msg-background',
            messageKind: 'assistant_final',
            turnId: TURN_ID,
            payload: {
              background_task_id: 'ordinary-background-task',
            },
          },
          transcript: baseTranscript,
        } as any}
        assistant={{ name: 'Magi', avatar: '' }}
        shouldReduceMotion
        execution={{
          summaries: {},
          executionControlByTurnId: {},
          cancellingTurnIds: [],
          detachingTurnIds: [],
          onOpenTraceDrawer: noop,
          onRequestRunCancel: noop,
          onRequestRunDetach: noop,
        }}
        interactions={{
          currentSessionId: SESSION_ID,
          labelPopoverState: null,
          labelPopoverDraft: '',
          labelPopoverRef: { current: null },
          onSetReplyTarget: noop,
          onOpenImagePreview: noop,
          onCloseLabelPopover: noop,
          onCloseMessageContextMenu: noop,
          onOpenLabelPopover: noop,
          onOpenMessageContextMenu: noop,
          onApplyLabelToMessage: noop,
          onLabelDraftChange: noop,
          onLabelDraftCompositionStart: noop,
          onLabelDraftCompositionEnd: noop,
        }}
      />,
    );

    expect(screen.getByText('Background task started')).toBeInTheDocument();
    expect(codeAgentApi.getDelegation).not.toHaveBeenCalled();
  });

  it('does not attach a previous turn delegation to the latest assistant message', () => {
    useConversationStore.getState().hydrateSessions([{
      session_id: SESSION_ID,
      title: 'Live task',
      last_message_preview: '',
      last_user_message_preview: '',
      title_overridden: false,
      last_timestamp: 1,
      message_count: 1,
      workspace_path: WORKSPACE,
    }], SESSION_ID);
    const createResult = (delegationId: string, summary: string) => ({
      delegation_id: delegationId,
      success: true,
      exit_code: 0,
      duration_ms: 100,
      adapter: 'codex' as const,
      diff_path: null,
      diff_stats: { files_changed: 0, additions: 0, deletions: 0 },
      files_changed: [],
      summary,
      logs_path: '/tmp/logs',
      events_path: '/tmp/events',
      error: null,
      cost: null,
    });
    useDelegationsStore.getState().upsertState(
      SESSION_ID,
      DELEGATION_ID,
      'turn-current',
      'finished',
      createResult(DELEGATION_ID, 'Current turn task') as unknown as Record<string, unknown>,
    );
    useDelegationsStore.getState().markHydrated(SESSION_ID, DELEGATION_ID);
    useDelegationsStore.getState().upsertState(
      SESSION_ID,
      SECOND_DELEGATION_ID,
      'turn-previous',
      'finished',
      createResult(SECOND_DELEGATION_ID, 'Previous turn task') as unknown as Record<string, unknown>,
    );
    useDelegationsStore.getState().markHydrated(
      SESSION_ID,
      SECOND_DELEGATION_ID,
    );

    render(
      <TranscriptTimelineRow
        projectedMessage={{
          surface: 'transcript',
          message: {
            id: 'msg-current-turn',
            role: 'assistant',
            kind: 'assistant',
            content: 'Current answer',
            timestamp: 1777729177195,
            messageId: 'msg-current-turn',
            messageKind: 'assistant_final',
            turnId: 'turn-current',
          },
          transcript: baseTranscript,
        } as any}
        assistant={{ name: 'Magi', avatar: '' }}
        shouldReduceMotion
        execution={{
          summaries: {},
          executionControlByTurnId: {},
          cancellingTurnIds: [],
          detachingTurnIds: [],
          onOpenTraceDrawer: noop,
          onRequestRunCancel: noop,
          onRequestRunDetach: noop,
        }}
        interactions={{
          currentSessionId: SESSION_ID,
          labelPopoverState: null,
          labelPopoverDraft: '',
          labelPopoverRef: { current: null },
          onSetReplyTarget: noop,
          onOpenImagePreview: noop,
          onCloseLabelPopover: noop,
          onCloseMessageContextMenu: noop,
          onOpenLabelPopover: noop,
          onOpenMessageContextMenu: noop,
          onApplyLabelToMessage: noop,
          onLabelDraftChange: noop,
          onLabelDraftCompositionStart: noop,
          onLabelDraftCompositionEnd: noop,
        }}
        isLastAssistant
      />,
    );

    expect(screen.getByText('Current turn task')).toBeInTheDocument();
    expect(screen.queryByText('Previous turn task')).not.toBeInTheDocument();
    expect(codeAgentApi.getDelegation).not.toHaveBeenCalled();
  });

  it('keeps the original answer visible when historical delegation hydration fails', async () => {
    useConversationStore.getState().hydrateSessions([{
      session_id: SESSION_ID,
      title: 'Unavailable task',
      last_message_preview: '',
      last_user_message_preview: '',
      title_overridden: false,
      last_timestamp: 1,
      message_count: 1,
      workspace_path: WORKSPACE,
    }], SESSION_ID);
    vi.mocked(codeAgentApi.getDelegation).mockRejectedValue(
      Object.assign(new Error('delegation not found'), {
        response: { status: 404 },
      }),
    );
    const unavailableRow = (
      <TranscriptTimelineRow
        projectedMessage={{
          surface: 'transcript',
          message: {
            id: 'msg-unavailable-delegation',
            role: 'assistant',
            kind: 'assistant',
            content: 'Original task answer',
            timestamp: 1777729177195,
            messageId: 'msg-unavailable-delegation',
            messageKind: 'assistant_final',
            turnId: TURN_ID,
            payload: {
              code_agent_delegations: [{
                delegation_id: DELEGATION_ID,
                turn_id: 'turn-historical',
                workspace_path: FIRST_TASK_WORKSPACE,
              }],
            },
          },
          transcript: baseTranscript,
        } as any}
        assistant={{ name: 'Magi', avatar: '' }}
        shouldReduceMotion
        execution={{
          summaries: {},
          executionControlByTurnId: {},
          cancellingTurnIds: [],
          detachingTurnIds: [],
          onOpenTraceDrawer: noop,
          onRequestRunCancel: noop,
          onRequestRunDetach: noop,
        }}
        interactions={{
          currentSessionId: SESSION_ID,
          labelPopoverState: null,
          labelPopoverDraft: '',
          labelPopoverRef: { current: null },
          onSetReplyTarget: noop,
          onOpenImagePreview: noop,
          onCloseLabelPopover: noop,
          onCloseMessageContextMenu: noop,
          onOpenLabelPopover: noop,
          onOpenMessageContextMenu: noop,
          onApplyLabelToMessage: noop,
          onLabelDraftChange: noop,
          onLabelDraftCompositionStart: noop,
          onLabelDraftCompositionEnd: noop,
        }}
      />
    );

    const rendered = render(unavailableRow);

    await waitFor(() => {
      expect(screen.getByText('Original task answer')).toBeInTheDocument();
      expect(
        screen.getByText('chat.delegation.lifecycle.failed'),
      ).toBeInTheDocument();
    });
    rendered.rerender(unavailableRow);

    expect(codeAgentApi.getDelegation).toHaveBeenCalledTimes(1);
  });

  it('renders a duplicated rhythm reference only on the final segment', async () => {
    useConversationStore.getState().hydrateSessions([{
      session_id: SESSION_ID,
      title: 'Segmented answer',
      last_message_preview: '',
      last_user_message_preview: '',
      title_overridden: false,
      last_timestamp: 1,
      message_count: 2,
      workspace_path: WORKSPACE,
    }], SESSION_ID);
    vi.mocked(codeAgentApi.getDelegation).mockResolvedValue({
      result: {
        delegation_id: DELEGATION_ID,
        success: true,
        exit_code: 0,
        duration_ms: 100,
        adapter: 'codex',
        diff_path: null,
        diff_stats: { files_changed: 0, additions: 0, deletions: 0 },
        files_changed: [],
        summary: 'Segmented task result',
        logs_path: '/tmp/logs',
        events_path: '/tmp/events',
        error: null,
        cost: null,
      },
      events_tail: [],
      diff_text: '',
    });
    const codeAgentDelegations = [{
      delegation_id: DELEGATION_ID,
      turn_id: TURN_ID,
      workspace_path: FIRST_TASK_WORKSPACE,
    }];

    render(
      <>
        {createTranscriptRow({
          id: 'rhythm-segment-0',
          role: 'assistant',
          kind: 'assistant',
          content: 'First segment',
          timestamp: 1777729177195,
          messageId: 'rhythm-segment-0',
          messageKind: 'assistant_rhythm_segment',
          turnId: TURN_ID,
          payload: {
            rhythm: { segment_index: 0, segment_count: 2 },
            code_agent_delegations: codeAgentDelegations,
          },
        })}
        {createTranscriptRow({
          id: 'rhythm-segment-1',
          role: 'assistant',
          kind: 'assistant',
          content: 'Final segment',
          timestamp: 1777729177196,
          messageId: 'rhythm-segment-1',
          messageKind: 'assistant_rhythm_segment',
          turnId: TURN_ID,
          payload: {
            rhythm: { segment_index: 1, segment_count: 2 },
            code_agent_delegations: codeAgentDelegations,
          },
        }, true)}
      </>,
    );

    await waitFor(() => {
      expect(
        screen.getAllByText('chat.delegation.lifecycle.finished'),
      ).toHaveLength(1);
    });
    expect(codeAgentApi.getDelegation).toHaveBeenCalledTimes(1);
  });
});
