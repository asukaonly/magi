import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { SkillCommandDescriptor } from '@/api';
import {
  INLINE_SKILL_RETRY_STORAGE_KEY,
  loadRetryableInlineSkillOperations,
} from '@/hooks/chatRetryableSendStorage';
import type { RunWithChatTurnAdmission } from '@/hooks/chatTurnAdmission';
import {
  useChatInlineSkillSend,
  type SkillExpansionOutcome,
} from '@/hooks/useChatInlineSkillSend';
import { useConversationStore } from '@/stores/conversation-store';

const {
  expandSkillMock,
  getHistoryMock,
  runSkillAsBackgroundMock,
  sendMessageMock,
  toastWarningMock,
} = vi.hoisted(() => ({
  expandSkillMock: vi.fn(),
  getHistoryMock: vi.fn(),
  runSkillAsBackgroundMock: vi.fn(),
  sendMessageMock: vi.fn(),
  toastWarningMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  commandsApi: {
    expandSkill: expandSkillMock,
    runSkillAsBackground: runSkillAsBackgroundMock,
  },
  messagesApi: {
    getHistory: getHistoryMock,
    sendMessage: sendMessageMock,
  },
}));

vi.mock('@/api/modules/control', () => ({
  getAskState: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: toastWarningMock,
  },
}));

const SESSION_ID = 'session-inline';
const DESCRIPTOR: SkillCommandDescriptor = {
  name: 'summarize',
  description: 'Summarize the conversation',
  argument_hint: null,
  tags: [],
  context_mode: 'inline',
};

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
};

const renderInlineSkillHook = ({
  hasPendingAsk = false,
  runWithTurnAdmission = async (_sessionId, _kind, operation) => ({
    entered: true as const,
    value: await operation(),
  }),
}: {
  hasPendingAsk?: boolean;
  runWithTurnAdmission?: RunWithChatTurnAdmission;
} = {}) => renderHook(() => useChatInlineSkillSend({
  currentSessionId: SESSION_ID,
  workspacePath: null,
  allowInterjection: true,
  hasPendingAsk,
  appendPendingTurn: vi.fn(),
  removeMessage: vi.fn(),
  trackPendingResponseTurn: vi.fn(),
  clearPendingResponseTurn: vi.fn(),
  reconcilePendingSendBeforeExternalTurn: async () => true,
  runWithTurnAdmission,
  translate: (key) => key,
}));

describe('useChatInlineSkillSend', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    useConversationStore.getState().reset();
    useConversationStore.getState().setCurrentSessionId(SESSION_ID);
    expandSkillMock.mockReset().mockResolvedValue({
      name: DESCRIPTOR.name,
      description: DESCRIPTOR.description,
      invocation_text: '/summarize',
      rendered_prompt: 'Expanded prompt',
      context_mode: 'inline',
    });
    getHistoryMock.mockReset().mockResolvedValue({
      user_id: 'local_user',
      session_id: SESSION_ID,
      messages: [],
      count: 0,
    });
    sendMessageMock.mockReset();
    runSkillAsBackgroundMock.mockReset().mockResolvedValue({
      task_id: 'task-background',
      title: 'Background summary',
    });
    toastWarningMock.mockReset();
  });

  it('reports an unconfirmed inline send instead of treating it as success', async () => {
    sendMessageMock.mockRejectedValue(new Error('offline'));
    const hook = renderInlineSkillHook();
    let outcome: SkillExpansionOutcome | undefined;

    await act(async () => {
      outcome = await hook.result.current.runSkillExpansion(DESCRIPTOR, '');
    });

    expect(outcome).toEqual({
      kind: 'not_sent',
      message: 'chat.skills.sendUnconfirmed',
    });
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).not.toBeNull();
  });

  it('blocks inline skills during a pending ask but still allows background skills', async () => {
    const hook = renderInlineSkillHook({ hasPendingAsk: true });

    await expect(
      hook.result.current.runSkillExpansion(DESCRIPTOR, ''),
    ).resolves.toEqual({
      kind: 'not_sent',
      message: 'chat.skills.pendingAskBlocked',
    });
    expect(expandSkillMock).not.toHaveBeenCalled();
    expect(sendMessageMock).not.toHaveBeenCalled();

    await expect(hook.result.current.runSkillExpansion({
      ...DESCRIPTOR,
      context_mode: 'fork',
    }, '')).resolves.toEqual({ kind: 'accepted' });
    expect(runSkillAsBackgroundMock).toHaveBeenCalledTimes(1);
  });

  it('does not start a background skill while history is being cleared', async () => {
    const hook = renderInlineSkillHook({
      runWithTurnAdmission: async () => ({
        entered: false,
        reason: 'exclusive_action',
      }),
    });

    await expect(hook.result.current.runSkillExpansion({
      ...DESCRIPTOR,
      context_mode: 'fork',
    }, '')).resolves.toEqual({
      kind: 'not_sent',
      message: 'chat.clearHistoryDialog.inProgress',
    });
    expect(runSkillAsBackgroundMock).not.toHaveBeenCalled();
  });

  it.each([
    {
      name: 'an exact message deletion',
      clear: (
        hook: ReturnType<typeof renderInlineSkillHook>,
        turnId: string,
      ) => hook.result.current.clearRetryForTurn(SESSION_ID, turnId),
    },
    {
      name: 'a session or history deletion',
      clear: (hook: ReturnType<typeof renderInlineSkillHook>) => (
        hook.result.current.clearRetriesForSession(SESSION_ID)
      ),
    },
    {
      name: 'a full memory clear',
      clear: (hook: ReturnType<typeof renderInlineSkillHook>) => (
        hook.result.current.clearAllRetries()
      ),
    },
  ])('does not restore an inline retry after $name while its request is still in flight', async ({ clear }) => {
    const firstAttempt = createDeferred<never>();
    sendMessageMock
      .mockImplementationOnce(() => firstAttempt.promise)
      .mockRejectedValue(new Error('offline'));
    const hook = renderInlineSkillHook();
    let sendPromise!: Promise<SkillExpansionOutcome>;

    act(() => {
      sendPromise = hook.result.current.runSkillExpansion(DESCRIPTOR, '');
    });

    await waitFor(() => {
      expect(window.sessionStorage.getItem(
        INLINE_SKILL_RETRY_STORAGE_KEY,
      )).not.toBeNull();
    });
    const operation = [...loadRetryableInlineSkillOperations().values()][0];
    expect(operation).toBeDefined();

    act(() => {
      clear(hook, operation.confirmation.turnId);
    });
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();

    await act(async () => {
      firstAttempt.reject(new Error('late network failure'));
      await sendPromise;
    });

    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();
    expect(toastWarningMock).not.toHaveBeenCalledWith(
      'chat.skills.sendUnconfirmed',
    );
  });
});
