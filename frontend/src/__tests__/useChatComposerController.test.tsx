import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PendingAskSendContext } from '@/hooks/useChatSendMessage';
import { useChatComposerController } from '@/hooks/useChatComposerController';

const {
  clearDraftAttachmentsMock,
  useChatSendMessageMock,
} = vi.hoisted(() => ({
  clearDraftAttachmentsMock: vi.fn(),
  useChatSendMessageMock: vi.fn(),
}));

vi.mock('@/hooks/useChatDraftAttachments', () => ({
  useChatDraftAttachments: () => ({
    attachmentMenuOpen: false,
    draftAttachments: [],
    clearDraftAttachments: clearDraftAttachmentsMock,
    removeDraftAttachment: vi.fn(),
    addMcpResourceDraft: vi.fn(),
    handleAttachmentInputChange: vi.fn(),
    handleComposerPaste: vi.fn(),
    setAttachmentMenuOpen: vi.fn(),
  }),
}));

vi.mock('@/hooks/useChatSendMessage', async () => {
  const actual = await vi.importActual<
    typeof import('@/hooks/useChatSendMessage')
  >('@/hooks/useChatSendMessage');
  return {
    ...actual,
    useChatSendMessage: useChatSendMessageMock,
  };
});

const ask = (
  sessionId: string,
  requestId: string,
): PendingAskSendContext => ({
  sessionId,
  requestId,
  messageId: `ask:${requestId}`,
  question: 'Continue?',
  options: ['Yes', 'No'],
  allowFreeText: false,
  expiresAtMs: Date.now() + 60_000,
});

const renderController = (
  currentSessionId: string,
  pendingAsk: PendingAskSendContext | null,
) => renderHook(
  ({ session, currentAsk }) => useChatComposerController({
    currentSessionId: session,
    currentWorkspacePath: null,
    allowInterjection: false,
    coreModelSupportsVision: true,
    pendingAsk: currentAsk,
    appendPendingTurn: vi.fn(),
    removePendingMessage: vi.fn(),
    setCurrentSessionId: vi.fn(),
    onAskAnswered: vi.fn(),
    requestRunCancel: vi.fn(async () => 'ignored' as const),
    markAdmissionPendingTurn: vi.fn(),
    clearAdmissionPendingTurn: vi.fn(),
    reconcileExternalTurnBeforeSend: vi.fn(async () => ({
      kind: 'ready' as const,
    })),
    runWithTurnAdmission: vi.fn(async (_sessionId, _kind, operation) => ({
      entered: true as const,
      value: await operation(),
    })),
    translate: (key) => key,
  }), {
    initialProps: {
      session: currentSessionId,
      currentAsk: pendingAsk,
    },
  },
);

describe('useChatComposerController pending ask drafts', () => {
  beforeEach(() => {
    clearDraftAttachmentsMock.mockReset();
    useChatSendMessageMock.mockReset().mockReturnValue({
      clearAllRetryableSends: vi.fn(),
      clearRetryableSendForTurn: vi.fn(),
      clearRetryableSendsForSession: vi.fn(),
      sendingMessage: false,
      handleSendMessage: vi.fn(),
      reconcilePendingSendBeforeExternalTurn: vi.fn(async () => true),
    });
  });

  it('does not carry an ask answer across sessions or back to the original ask', () => {
    const firstAsk = ask('session-a', 'ask-a');
    const hook = renderController('session-a', firstAsk);

    act(() => {
      hook.result.current.setInputValue('Yes');
    });
    expect(hook.result.current.inputValue).toBe('Yes');

    hook.rerender({
      session: 'session-b',
      currentAsk: null,
    });
    expect(hook.result.current.inputValue).toBe('');

    hook.rerender({
      session: 'session-a',
      currentAsk: firstAsk,
    });
    expect(hook.result.current.inputValue).toBe('');
  });

  it('restores the ordinary draft after an ask is answered or expires', () => {
    const hook = renderController('session-a', null);
    act(() => {
      hook.result.current.setInputValue('Keep this ordinary draft');
    });

    hook.rerender({
      session: 'session-a',
      currentAsk: ask('session-a', 'ask-a'),
    });
    expect(hook.result.current.inputValue).toBe('');

    act(() => {
      hook.result.current.setInputValue('Yes');
    });
    expect(hook.result.current.inputValue).toBe('Yes');

    hook.rerender({
      session: 'session-a',
      currentAsk: null,
    });
    expect(hook.result.current.inputValue).toBe('Keep this ordinary draft');
  });

  it('clears only the ask-bound draft when chat history is cleared', () => {
    const hook = renderController(
      'session-a',
      ask('session-a', 'ask-a'),
    );
    act(() => {
      hook.result.current.setInputValue('Yes');
    });
    expect(hook.result.current.inputValue).toBe('Yes');

    act(() => {
      hook.result.current.clearHistoryBoundDraftState();
    });
    expect(hook.result.current.inputValue).toBe('');
  });
});
