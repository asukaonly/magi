import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { useChatTraceStore } from '@/stores';

const sendMock = vi.fn();
let realtimeListener: ((message: Record<string, unknown>) => void) | null = null;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('@/realtime/provider', () => ({
  useRealtime: () => ({
    send: sendMock,
    subscribe: (listener: (message: Record<string, unknown>) => void) => {
      realtimeListener = listener;
      return () => {
        realtimeListener = null;
      };
    },
  }),
}));

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({
    apiBaseUrl: 'http://127.0.0.1:8000/api',
  }),
}));

vi.mock('@/api', () => ({
  messagesApi: {
    getTrace: vi.fn(),
  },
}));

vi.mock('@/components/chat/ToolchainDrawer', () => ({
  default: () => null,
}));

describe('ChatPage', () => {
  beforeEach(() => {
    sendMock.mockReset();
    realtimeListener = null;
    Element.prototype.scrollIntoView = vi.fn();
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    useConversationStore.getState().setCurrentSessionId('session-1');
  });

  it('renders trace entry when an agent response arrives through chat subscription', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '整理好了',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-1',
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-1',
            mode: 'function_calling',
            status: 'completed',
            headline: '工具链已完成',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 1.2,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('整理好了')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'chat.trace.view' })).toBeInTheDocument();
  });

  it('requests fresh history when a turn completes without an agent response event', () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-2',
          trace_summary: {
            turn_id: 'turn-2',
            mode: 'function_calling',
            status: 'completed',
            headline: '工具链已完成',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 1.2,
            trace_available: true,
          },
        },
      });
    });

    expect(sendMock).toHaveBeenCalledWith({
      type: 'get_history',
      session_id: 'session-1',
    });
  });

  it('does not ask the backend for a current session after websocket subscribe', () => {
    useConversationStore.getState().setCurrentSessionId(null);
    sendMock.mockClear();
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        type: 'subscribed',
      });
    });

    expect(sendMock).not.toHaveBeenCalledWith({ type: 'get_current_session' });
  });
});
