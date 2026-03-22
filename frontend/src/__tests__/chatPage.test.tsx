import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { useChatTraceStore } from '@/stores';
import { shouldShowTraceEntry } from '@/pages/chat-state';

const sendMock = vi.fn();
let realtimeListener: ((message: Record<string, unknown>) => void) | null = null;
const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

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
  afterAll(() => {
    consoleErrorSpy.mockRestore();
  });

  afterEach(() => {
    realtimeListener = null;
    sendMock.mockReset();
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    cleanup();
    document.body.innerHTML = '';
  });

  beforeEach(() => {
    sendMock.mockReset();
    realtimeListener = null;
    consoleErrorSpy.mockClear();
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
          message_id: 'msg-final-1',
          message_kind: 'assistant_final',
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
    expect(
      useConversationStore.getState().messagesBySession['session-1']?.find((message) => message.turnId === 'turn-1')?.id
    ).toBe('msg-final-1');
    expect(screen.getByRole('button', { name: 'chat.trace.view' })).toBeInTheDocument();
  });

  it('hides the trace entry when ux plan disables trace display', async () => {
    const view = render(<ChatPage />);
    const scoped = within(view.container);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '整理好了',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-hidden',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            trace_display_mode: 'none',
          },
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-hidden',
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
      expect(scoped.getAllByText('整理好了').length).toBeGreaterThan(0);
    });
    const hiddenMessage = useConversationStore.getState().messagesBySession['session-1']
      ?.find((message) => message.turnId === 'turn-hidden');
    expect(hiddenMessage?.traceDisplayMode).toBe('none');
    expect(
      shouldShowTraceEntry(hiddenMessage ?? { turnId: '', traceDisplayMode: null, traceAvailable: false, traceSummary: null })
    ).toBe(false);
  });

  it('renders a more prominent trace entry when ux plan requests prominent trace display', async () => {
    const view = render(<ChatPage />);
    const scoped = within(view.container);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '需要你看下执行细节',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-prominent',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            trace_display_mode: 'prominent',
            allow_trace_collapse: true,
          },
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-prominent',
            mode: 'orchestration',
            status: 'completed',
            headline: '任务链路已生成',
            active_steps: 0,
            completed_steps: 3,
            failed_steps: 0,
            duration_seconds: 2.1,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(scoped.getByText('需要你看下执行细节')).toBeInTheDocument();
    });

    expect(view.container.querySelector('[data-trace-variant="prominent"]')).toBeInTheDocument();
  });

  it('renders an interim assistant message when turn ux plan requests interim-then-final', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-2',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
            interim_text: '稍等我查一下',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('稍等我查一下')).toBeInTheDocument();
    });

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '已经查好了',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-2',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('已经查好了')).toBeInTheDocument();
    });
    expect(screen.queryByText('稍等我查一下')).not.toBeInTheDocument();
  });

  it('renders a reaction-only acknowledgement without an assistant bubble', async () => {
    render(<ChatPage />);

    act(() => {
      useConversationStore.getState().appendPendingTurn({
        sessionId: 'session-1',
        input: '嗯',
        turnId: 'turn-3',
        timestamp: Date.now(),
        pendingLabel: 'thinking',
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-3',
          ux_plan: {
            assistant_surface_mode: 'reaction_only',
            reaction_style: 'acknowledge',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('👌')).toBeInTheDocument();
    });

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '收到啦',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-3',
          ux_plan: {
            assistant_surface_mode: 'reaction_only',
            reaction_style: 'acknowledge',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.queryByText('收到啦')).not.toBeInTheDocument();
    });
  });

  it('renders a thinking status card when ux plan requests visible thinking feedback', async () => {
    render(<ChatPage />);

    act(() => {
      useConversationStore.getState().appendPendingTurn({
        sessionId: 'session-1',
        input: '帮我查一下',
        turnId: 'turn-4',
        timestamp: Date.now(),
        pendingLabel: 'thinking',
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-4',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            thinking_indicator: 'visible',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('chat.trace.pending')).toBeInTheDocument();
    });
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

  it('does not emit act warnings while handling chat updates', async () => {
    const content = 'warning-check-reply';
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content,
          timestamp: Date.now() / 1000,
          turn_id: 'turn-warning',
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText(content)).toBeInTheDocument();
    });

    const actWarnings = consoleErrorSpy.mock.calls.filter(([firstArg]) =>
      String(firstArg).includes('not wrapped in act')
    );
    expect(actWarnings).toHaveLength(0);
  });
});
