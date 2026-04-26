import { useEffect } from 'react';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RealtimeProvider, useRealtime, type RealtimeMessage } from '@/realtime/provider';
import { useChatTraceStore } from '@/stores';
import { useConversationStore } from '@/stores/conversation-store';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

let bridgeListener: ((message: Record<string, unknown>) => void) | null = null;

vi.mock('@/realtime/tauri-bridge', () => ({
  TauriBridgeClient: class {
    subscribe(listener: (message: Record<string, unknown>) => void) {
      bridgeListener = listener;
      return () => {
        if (bridgeListener === listener) {
          bridgeListener = null;
        }
      };
    }

    connect() {}

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

  it('keeps the legacy content-delta fallback for streaming text chunks', async () => {
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
          content_delta: 'Hello',
          is_final: false,
        },
      });
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-legacy-stream',
          content_delta: '',
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