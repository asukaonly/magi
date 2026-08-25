import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PendingAskSendContext,
  UseChatSendMessageOptions,
} from '@/hooks/useChatSendMessage';
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
  firstContextQuestion: UseChatSendMessageOptions['firstContextQuestion'] = null,
) => renderHook(
  ({ session, currentAsk, currentFirstContextQuestion }) => useChatComposerController({
    currentSessionId: session,
    currentWorkspacePath: null,
    allowInterjection: false,
    coreModelSupportsVision: true,
    pendingAsk: currentAsk,
    firstContextQuestion: currentFirstContextQuestion,
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
      currentFirstContextQuestion: firstContextQuestion,
    },
  },
);

const latestSendOptions = (): UseChatSendMessageOptions => {
  const calls = useChatSendMessageMock.mock.calls;
  return calls[calls.length - 1]?.[0] as UseChatSendMessageOptions;
};

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
      currentFirstContextQuestion: null,
    });
    expect(hook.result.current.inputValue).toBe('');

    hook.rerender({
      session: 'session-a',
      currentAsk: firstAsk,
      currentFirstContextQuestion: null,
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
      currentFirstContextQuestion: null,
    });
    expect(hook.result.current.inputValue).toBe('');

    act(() => {
      hook.result.current.setInputValue('Yes');
    });
    expect(hook.result.current.inputValue).toBe('Yes');

    hook.rerender({
      session: 'session-a',
      currentAsk: null,
      currentFirstContextQuestion: null,
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

  it('clears the ordinary draft and attachments for destructive deletion', () => {
    const hook = renderController('session-a', null);
    act(() => {
      hook.result.current.setInputValue('private unsent draft');
    });

    act(() => {
      hook.result.current.clearDeletedSessionDraftState();
    });

    expect(hook.result.current.inputValue).toBe('');
    expect(clearDraftAttachmentsMock).toHaveBeenCalledTimes(1);
  });

  it('clears a one-turn reasoning override after the submitted draft is accepted', () => {
    const hook = renderController('session-a', null);

    act(() => {
      hook.result.current.setInputValue('Answer briefly');
      hook.result.current.setReasoningPreference('fast');
    });
    const submittedOptions = latestSendOptions();

    expect(hook.result.current.reasoningPreference).toBe('fast');
    expect(submittedOptions.reasoningPreference).toBe('fast');

    act(() => {
      submittedOptions.clearComposerDraftIfUnchanged(
        submittedOptions.composerDraftIdentity,
        'normal',
      );
    });

    expect(hook.result.current.reasoningPreference).toBe('auto');
  });

  it('clears an accepted first-context answer after the prompt advances', () => {
    const firstContextQuestion = {
      questionId: 'repeating_content' as const,
      questionText: 'What have you been listening to repeatedly?',
    };
    const hook = renderController(
      'session-a',
      null,
      firstContextQuestion,
    );

    act(() => {
      hook.result.current.setInputValue('DIIV');
    });
    const submittedOptions = latestSendOptions();
    const submittedIdentity = submittedOptions.composerDraftIdentity;
    const submittedSignature = submittedOptions.composerDraftSignature;

    hook.rerender({
      session: 'session-a',
      currentAsk: null,
      currentFirstContextQuestion: null,
    });
    const acceptedOptions = latestSendOptions();

    expect(acceptedOptions.composerDraftSignature).not.toBe(
      submittedSignature,
    );
    expect(acceptedOptions.composerDraftIdentity).toBe(submittedIdentity);

    act(() => {
      acceptedOptions.clearComposerDraftIfUnchanged(
        submittedIdentity,
        'first_context',
      );
    });

    expect(hook.result.current.inputValue).toBe('');
  });

  it('preserves new text typed after a first-context answer was submitted', () => {
    const firstContextQuestion = {
      questionId: 'repeating_content' as const,
      questionText: 'What have you been listening to repeatedly?',
    };
    const hook = renderController(
      'session-a',
      null,
      firstContextQuestion,
    );

    act(() => {
      hook.result.current.setInputValue('DIIV');
    });
    const submittedOptions = latestSendOptions();

    hook.rerender({
      session: 'session-a',
      currentAsk: null,
      currentFirstContextQuestion: null,
    });
    act(() => {
      hook.result.current.setInputValue('A new message');
    });
    const acceptedOptions = latestSendOptions();

    act(() => {
      acceptedOptions.clearComposerDraftIfUnchanged(
        submittedOptions.composerDraftIdentity,
        'first_context',
      );
    });

    expect(hook.result.current.inputValue).toBe('A new message');
  });
});
