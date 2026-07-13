import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TranscriptTimelineRow } from '@/components/chat/TranscriptTimelineRow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('@/runtime/desktop', () => ({
  openExternalUrl: vi.fn(),
}));

const noop = vi.fn();

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

describe('TranscriptTimelineRow', () => {
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
});
