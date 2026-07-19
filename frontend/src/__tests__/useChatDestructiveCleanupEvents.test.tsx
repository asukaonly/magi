import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { APP_EVENTS, dispatchAppEvent } from '@/constants/events';
import { useChatDestructiveCleanupEvents } from '@/hooks/useChatDestructiveCleanupEvents';

const renderCleanupHook = (currentSessionId = 'session-a') => {
  const callbacks = {
    clearAllAdmissionPendingTurns: vi.fn(),
    clearAllInlineSkillRetries: vi.fn(),
    clearAllPendingResponseTurns: vi.fn(),
    clearAllRetryableSends: vi.fn(),
    clearConversationBoundDraftState: vi.fn(),
    clearDeletedSessionDraftState: vi.fn(),
    clearInlineSkillRetriesForSession: vi.fn(),
    clearPendingResponseTurn: vi.fn(),
    clearAdmissionPendingTurn: vi.fn(),
    clearRetryableSendsForSession: vi.fn(),
    clearSessionLifecycleState: vi.fn(),
    clearSessionHistory: vi.fn(),
    getCurrentSessionId: vi.fn(() => currentSessionId),
    resetTraceDrawer: vi.fn(),
    resetConversation: vi.fn(),
    setCurrentSessionId: vi.fn(),
  };
  const hook = renderHook(() => useChatDestructiveCleanupEvents(callbacks));
  return { ...hook, callbacks };
};

describe('useChatDestructiveCleanupEvents', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('clears only the deleted session and resets the active composer', () => {
    const hook = renderCleanupHook('session-a');

    act(() => {
      dispatchAppEvent.chatSessionDeleted('session-a');
    });

    expect(hook.callbacks.clearRetryableSendsForSession).toHaveBeenCalledWith(
      'session-a',
    );
    expect(hook.callbacks.clearInlineSkillRetriesForSession).toHaveBeenCalledWith(
      'session-a',
    );
    expect(hook.callbacks.clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-a',
    });
    expect(hook.callbacks.clearAdmissionPendingTurn).toHaveBeenCalledWith(
      'session-a',
    );
    expect(hook.callbacks.clearSessionHistory).toHaveBeenCalledWith('session-a');
    expect(hook.callbacks.clearSessionLifecycleState).toHaveBeenCalledWith('session-a');
    expect(hook.callbacks.clearDeletedSessionDraftState).toHaveBeenCalledTimes(1);
    expect(hook.callbacks.clearConversationBoundDraftState).not.toHaveBeenCalled();
    expect(hook.callbacks.setCurrentSessionId).toHaveBeenCalledWith(null);
    expect(hook.callbacks.resetTraceDrawer).toHaveBeenCalledTimes(1);
  });

  it('does not reset the active composer when another session is deleted', () => {
    const hook = renderCleanupHook('session-b');

    act(() => {
      dispatchAppEvent.chatSessionDeleted('session-a');
    });

    expect(hook.callbacks.clearRetryableSendsForSession).toHaveBeenCalledWith(
      'session-a',
    );
    expect(hook.callbacks.clearDeletedSessionDraftState).not.toHaveBeenCalled();
    expect(hook.callbacks.setCurrentSessionId).not.toHaveBeenCalled();
    expect(hook.callbacks.resetTraceDrawer).not.toHaveBeenCalled();
  });

  it('clears every in-memory chat state on a full memory clear', () => {
    const hook = renderCleanupHook();

    act(() => {
      window.dispatchEvent(new Event(APP_EVENTS.MEMORY_CLEARED));
    });

    expect(hook.callbacks.clearAllRetryableSends).toHaveBeenCalledTimes(1);
    expect(hook.callbacks.clearAllInlineSkillRetries).toHaveBeenCalledTimes(1);
    expect(hook.callbacks.clearAllPendingResponseTurns).toHaveBeenCalledTimes(1);
    expect(hook.callbacks.clearAllAdmissionPendingTurns).toHaveBeenCalledTimes(1);
    expect(hook.callbacks.clearConversationBoundDraftState).toHaveBeenCalledTimes(1);
    expect(hook.callbacks.clearSessionLifecycleState).toHaveBeenCalledWith();
    expect(hook.callbacks.setCurrentSessionId).toHaveBeenCalledWith(null);
    expect(hook.callbacks.resetTraceDrawer).toHaveBeenCalledTimes(1);
    expect(hook.callbacks.resetConversation).toHaveBeenCalledTimes(1);
  });
});
