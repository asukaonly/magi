import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { dispatchAppEvent, APP_EVENTS } from '@/constants/events';
import { useChatWorkspaceActions } from '@/hooks/useChatWorkspaceActions';

const {
  getRecentWorkspacesMock,
  pickDirectoryMock,
  rememberWorkspaceMock,
  updateSessionWorkspaceMock,
  toastErrorMock,
} = vi.hoisted(() => ({
  getRecentWorkspacesMock: vi.fn(),
  pickDirectoryMock: vi.fn(),
  rememberWorkspaceMock: vi.fn(),
  updateSessionWorkspaceMock: vi.fn(),
  toastErrorMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  messagesApi: {
    getRecentWorkspaces: getRecentWorkspacesMock,
    rememberWorkspace: rememberWorkspaceMock,
    updateSessionWorkspace: updateSessionWorkspaceMock,
  },
}));

vi.mock('@/runtime/desktop', () => ({
  pickDirectory: pickDirectoryMock,
}));

vi.mock('sonner', () => ({
  toast: {
    error: toastErrorMock,
  },
}));

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
};

describe('useChatWorkspaceActions full-clear invalidation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getRecentWorkspacesMock.mockResolvedValue({ paths: [] });
    rememberWorkspaceMock.mockResolvedValue({ paths: [] });
    pickDirectoryMock.mockResolvedValue(null);
  });

  it('does not commit an old workspace response after a full clear starts', async () => {
    const update = createDeferred<{
      success: boolean;
      user_id: string;
      session: {
        session_id: string;
        title: string;
        last_message_preview: string;
        last_timestamp: number;
        message_count: number;
        workspace_path: string;
      };
    }>();
    updateSessionWorkspaceMock.mockReturnValueOnce(update.promise);
    const upsertSession = vi.fn();
    const sessionSync = vi.fn();
    window.addEventListener(APP_EVENTS.SESSION_SYNC, sessionSync);
    const hook = renderHook(() => useChatWorkspaceActions({
      currentSessionId: 'session-before-clear',
      currentWorkspacePath: null,
      upsertSession,
      translate: (key) => key,
    }));
    let pending!: Promise<void>;
    act(() => {
      pending = hook.result.current.persistSessionWorkspace('/private/old');
    });
    await waitFor(() => {
      expect(updateSessionWorkspaceMock).toHaveBeenCalledWith(
        'local_user',
        'session-before-clear',
        '/private/old',
      );
    });

    act(() => {
      dispatchAppEvent.memoryClearStarted();
    });
    await act(async () => {
      update.resolve({
        success: true,
        user_id: 'local_user',
        session: {
          session_id: 'session-before-clear',
          title: 'Old private session',
          last_message_preview: '',
          last_timestamp: 1,
          message_count: 0,
          workspace_path: '/private/old',
        },
      });
      await pending;
    });

    expect(rememberWorkspaceMock).not.toHaveBeenCalled();
    expect(upsertSession).not.toHaveBeenCalled();
    expect(sessionSync).not.toHaveBeenCalled();
    expect(toastErrorMock).not.toHaveBeenCalled();
    expect(hook.result.current.updatingWorkspace).toBe(false);
    window.removeEventListener(APP_EVENTS.SESSION_SYNC, sessionSync);
  });

  it('does not surface an old workspace failure or leave the interface busy after a full clear starts', async () => {
    const update = createDeferred<never>();
    updateSessionWorkspaceMock.mockReturnValueOnce(update.promise);
    const upsertSession = vi.fn();
    const hook = renderHook(() => useChatWorkspaceActions({
      currentSessionId: 'session-before-clear',
      currentWorkspacePath: null,
      upsertSession,
      translate: (key) => key,
    }));
    let pending!: Promise<void>;
    act(() => {
      pending = hook.result.current.persistSessionWorkspace('/private/old');
    });
    await waitFor(() => {
      expect(hook.result.current.updatingWorkspace).toBe(true);
    });

    act(() => {
      dispatchAppEvent.memoryClearStarted();
    });
    await act(async () => {
      update.reject(new Error('late old failure'));
      await pending;
    });

    expect(hook.result.current.updatingWorkspace).toBe(false);
    expect(upsertSession).not.toHaveBeenCalled();
    expect(rememberWorkspaceMock).not.toHaveBeenCalled();
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('does not apply a folder picker result returned after a full clear starts', async () => {
    const picker = createDeferred<string | null>();
    pickDirectoryMock.mockReturnValueOnce(picker.promise);
    const hook = renderHook(() => useChatWorkspaceActions({
      currentSessionId: 'session-before-clear',
      currentWorkspacePath: null,
      upsertSession: vi.fn(),
      translate: (key) => key,
    }));
    let pending!: Promise<void>;
    act(() => {
      pending = hook.result.current.handlePickWorkspace();
    });
    await waitFor(() => {
      expect(pickDirectoryMock).toHaveBeenCalledTimes(1);
    });

    act(() => {
      dispatchAppEvent.memoryClearStarted();
    });
    await act(async () => {
      picker.resolve('/private/old');
      await pending;
    });

    expect(updateSessionWorkspaceMock).not.toHaveBeenCalled();
  });
});
