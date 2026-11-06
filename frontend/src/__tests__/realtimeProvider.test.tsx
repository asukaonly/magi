import { useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RealtimeProvider, useRealtime, type RealtimeMessage } from '@/realtime/provider';
import { useChatTraceStore } from '@/stores';
import { useConversationStore } from '@/stores/conversation-store';
import { APP_EVENTS } from '@/constants/events';
import type { EventConnectionStatus } from '@/realtime/sse-client';
import { requestRuntimeReconnect } from '@/runtime/config';

vi.mock('@/runtime/config', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/runtime/config')>(),
  getRuntimeConfig: () => ({ apiBaseUrl: 'https://center.example/api', serverId: 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0' }),
  requestRuntimeReconnect: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const { connectMock } = vi.hoisted(() => ({ connectMock: vi.fn<() => Promise<void>>() }));

let bridgeListener: ((message: Record<string, unknown>) => void) | null = null;
let statusListener: ((status: EventConnectionStatus) => void) | null = null;

vi.mock('@/realtime/sse-client', () => ({
  SseClient: class {
    subscribe(listener: (message: Record<string, unknown>) => void) {
      bridgeListener = listener;
      return () => {
        if (bridgeListener === listener) {
          bridgeListener = null;
        }
      };
    }

    connect() { return connectMock(); }

    subscribeStatus(listener: (status: EventConnectionStatus) => void) {
      statusListener = listener;
      return () => { statusListener = null; };
    }

    disconnect() {
      bridgeListener = null;
    }
  },
}));

function RealtimeProbe({ onMessage }: { onMessage: (message: RealtimeMessage) => void }) {
  const { subscribe } = useRealtime();

  useEffect(() => subscribe(onMessage), [onMessage, subscribe]);

  return null;
}

describe('RealtimeProvider', () => {
  beforeEach(() => {
    connectMock.mockReset().mockResolvedValue();
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'sid-1',
        title: 'Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'sid-1');
  });

  afterEach(() => {
    cleanup();
    bridgeListener = null;
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
    vi.clearAllMocks();
  });

  it('leaves the draft mounted without a global warning while the client retries', async () => {
    connectMock.mockRejectedValueOnce(new Error('Bridge failed'));
    render(<RealtimeProvider><input aria-label="draft" defaultValue="Current draft" /></RealtimeProvider>);
    await act(async () => {});
    act(() => statusListener?.({ connected: false, reconnectAttempts: 1, lastError: 'Offline', accessDenied: false }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    const sync = vi.fn();
    window.addEventListener(APP_EVENTS.SESSION_SYNC, sync);
    act(() => statusListener?.({ connected: true, reconnectAttempts: 0, lastError: null, accessDenied: false }));
    expect(sync).toHaveBeenCalledOnce();
    expect(screen.getByRole('textbox', { name: 'draft' })).toHaveValue('Current draft');
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(connectMock).toHaveBeenCalledOnce();
    window.removeEventListener(APP_EVENTS.SESSION_SYNC, sync);
  });

  it('keeps a repair entry for rejected authorization and clears it on recovery', async () => {
    render(<RealtimeProvider><div>Current page</div></RealtimeProvider>);
    act(() => statusListener?.({ connected: false, reconnectAttempts: 1, lastError: 'Denied', accessDenied: true }));
    expect(screen.getByRole('alert')).toHaveTextContent('shell.connectionAccessDenied');
    fireEvent.click(screen.getByRole('button', { name: 'shell.reconnect' }));
    expect(requestRuntimeReconnect).toHaveBeenCalledOnce();
    act(() => statusListener?.({ connected: true, reconnectAttempts: 0, lastError: null, accessDenied: false }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Current page')).toBeInTheDocument();
  });

  it('projects execution trace updates into both the conversation and trace stores', async () => {
    render(
      <RealtimeProvider>
        <div />
      </RealtimeProvider>,
    );

    act(() => {
      bridgeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-trace',
          trace_summary: {
            turn_id: 'turn-trace',
            mode: 'function_calling',
            status: 'running',
            headline: 'Tracing execution',
            active_steps: 1,
            completed_steps: 0,
            failed_steps: 0,
            duration_seconds: 0.2,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      const projectedMessage = useConversationStore.getState().messagesBySession['sid-1']
        ?.find((message) => message.turnId === 'turn-trace');
      expect(projectedMessage?.traceSummary?.headline).toBe('Tracing execution');
      expect(useChatTraceStore.getState().summaries['turn-trace']?.headline).toBe('Tracing execution');
    });
  });

  it('projects no-bubble agent responses through the shared store path', async () => {
    useConversationStore.getState().upsertMessage('sid-1', {
      id: 'msg-user-only',
      role: 'user',
      kind: 'user',
      messageKind: 'user_text',
      content: 'Inspect the runtime path',
      timestamp: 1000,
      turnId: 'turn-no-bubble',
    });

    render(
      <RealtimeProvider>
        <div />
      </RealtimeProvider>,
    );

    act(() => {
      bridgeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-no-bubble',
          content: '',
          ux_plan: {
            assistant_surface_mode: 'none',
            trace_display_mode: 'none',
          },
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-no-bubble',
            mode: 'function_calling',
            status: 'completed',
            headline: 'Execution finished',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      const turnMessages = (useConversationStore.getState().messagesBySession['sid-1'] || [])
        .filter((message) => message.turnId === 'turn-no-bubble');
      expect(turnMessages).toHaveLength(1);
      expect(turnMessages[0]).toMatchObject({
        role: 'user',
        traceDisplayMode: 'none',
      });
      expect(useChatTraceStore.getState().summaries['turn-no-bubble']?.headline).toBe('Execution finished');
    });
  });

  it('projects turn ux plan updates through the shared store path', async () => {
    render(
      <RealtimeProvider>
        <div />
      </RealtimeProvider>,
    );

    act(() => {
      bridgeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-interim',
          message_id: 'msg-interim',
          message_kind: 'assistant_interim',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
            interim_text: 'Looking into it',
          },
        },
      });
    });

    await waitFor(() => {
      const projectedMessage = useConversationStore.getState().messagesBySession['sid-1']
        ?.find((message) => message.turnId === 'turn-interim' && message.messageKind === 'assistant_interim');
      expect(projectedMessage).toMatchObject({
        id: 'msg-interim',
        content: 'Looking into it',
      });
    });
  });

  it('normalizes tool-call chunk events for realtime subscribers', async () => {
    const onMessage = vi.fn();

    render(
      <RealtimeProvider>
        <RealtimeProbe onMessage={onMessage} />
      </RealtimeProvider>,
    );

    act(() => {
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-tool-call',
          event: {
            kind: 'tool_call_start',
            tool_call_id: 'call-1',
            tool_name: 'web-search',
          },
        },
      });
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-tool-call',
          event: {
            kind: 'tool_call_args',
            tool_call_id: 'call-1',
            tool_name: 'web-search',
            tool_args_delta: '{"query":"magi"}',
          },
        },
      });
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-tool-call',
          event: {
            kind: 'tool_call_end',
            tool_call_id: 'call-1',
            tool_name: 'web-search',
            tool_arguments: {
              query: 'magi',
            },
          },
        },
      });
    });

    await waitFor(() => {
      expect(onMessage).toHaveBeenCalledTimes(3);
    });

    expect(onMessage.mock.calls[0][0].streamEvent).toMatchObject({
      kind: 'tool_call_start',
      toolCallId: 'call-1',
      toolName: 'web-search',
    });
    expect(onMessage.mock.calls[1][0].streamEvent).toMatchObject({
      kind: 'tool_call_args',
      toolCallId: 'call-1',
      toolName: 'web-search',
      toolArgsDelta: '{"query":"magi"}',
    });
    expect(onMessage.mock.calls[2][0].streamEvent).toMatchObject({
      kind: 'tool_call_end',
      toolCallId: 'call-1',
      toolName: 'web-search',
      toolArguments: {
        query: 'magi',
      },
    });
  });

  it('routes reasoning deltas from normalized stream events into the conversation store', async () => {
    render(
      <RealtimeProvider>
        <div />
      </RealtimeProvider>,
    );

    act(() => {
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-reasoning',
          event: {
            kind: 'reasoning_delta',
            text: 'Inspecting the workspace',
            source: 'planner',
            step_label: 'Plan',
          },
        },
      });
    });

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      const reasoningMessage = messages.find((message) => message.turnId === 'turn-reasoning');
      expect(reasoningMessage).toBeDefined();
      expect(reasoningMessage?.reasoning?.[0]).toMatchObject({
        source: 'planner',
        stepLabel: 'Plan',
        content: 'Inspecting the workspace',
      });
    });
  });

  it('routes tool-call chunk events into the conversation store', async () => {
    render(
      <RealtimeProvider>
        <div />
      </RealtimeProvider>,
    );

    act(() => {
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-tool-store',
          event: {
            kind: 'tool_call_start',
            tool_call_id: 'call-1',
            tool_name: 'web-search',
          },
        },
      });
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-tool-store',
          event: {
            kind: 'tool_call_args',
            tool_call_id: 'call-1',
            tool_name: 'web-search',
            tool_args_delta: '{"query":"magi"}',
          },
        },
      });
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-tool-store',
          event: {
            kind: 'tool_call_end',
            tool_call_id: 'call-1',
            tool_name: 'web-search',
            tool_arguments: {
              query: 'magi',
            },
          },
        },
      });
    });

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => (
        message.turnId === 'turn-tool-store'
        && message.toolCalls?.some((toolCall) => (
          toolCall.toolCallId === 'call-1'
          && toolCall.toolName === 'web-search'
          && toolCall.status === 'completed'
        ))
      ))).toBe(true);
    });
  });

  it('projects structured text chunks and flushes on the final boundary', async () => {
    render(
      <RealtimeProvider>
        <div />
      </RealtimeProvider>,
    );

    act(() => {
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-legacy-stream',
          event: { kind: 'text_delta', text: 'Hello' },
          is_final: false,
        },
      });
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-legacy-stream',
          event: { kind: 'done' },
          is_final: true,
        },
      });
    });

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => (
        message.turnId === 'turn-legacy-stream'
        && message.content === 'Hello'
        && message.streaming === false
      ))).toBe(true);
    });
  });
});
