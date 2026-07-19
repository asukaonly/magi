import {
  defineChatPageSuite,
  realtimeListener,
  consoleErrorSpy,
  buildConfigWithVision,
} from '@/test/chatPageHarness';
import {
  act,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import { useChatTraceStore } from '@/stores';
import {
  normalizeHistoryMessages,
  shouldShowTraceEntry,
} from '@/domain/chat/state';
import { messagesApi } from '@/api';
import { configApi } from '@/api/modules/config';

defineChatPageSuite('ChatPage runtime updates', () => {
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

  it('loads trace when opening a trace entry and refreshes it while the drawer stays open', async () => {
    const user = userEvent.setup();
    vi.mocked(messagesApi.getTrace).mockResolvedValue({
      success: true,
      user_id: 'local_user',
      session_id: 'session-1',
      turn_id: 'turn-trace-open',
      trace: {
        turn_id: 'turn-trace-open',
        user_id: 'local_user',
        session_id: 'session-1',
        status: 'running',
        mode: 'orchestration',
        summary: {
          turn_id: 'turn-trace-open',
          mode: 'orchestration',
          status: 'running',
          headline: '正在分析项目',
          active_steps: 2,
          completed_steps: 1,
          failed_steps: 0,
          duration_seconds: 1.4,
          trace_available: true,
        },
        root: {
          id: 'root-turn-trace-open',
          kind: 'task',
          label: 'Inspect repository',
          status: 'running',
          metadata: {},
          children: [],
        },
      },
    } as any);

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          message_id: 'msg-final-trace-open',
          message_kind: 'assistant_final',
          content: 'Trace refresh target',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-trace-open',
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-trace-open',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    const messageText = await screen.findByText('Trace refresh target');
    const messageRow = messageText.closest('div.items-start');
    expect(messageRow).not.toBeNull();
    if (!messageRow) {
      throw new Error('Expected the assistant trace row to exist.');
    }

    const scopedRow = messageRow as HTMLElement;
    await user.click(within(scopedRow).getByRole('button', { name: 'chat.trace.view' }));

    await waitFor(() => {
      expect(messagesApi.getTrace).toHaveBeenCalledWith('local_user', 'session-1', 'turn-trace-open');
    });
    await waitFor(() => {
      expect(useChatTraceStore.getState().activeTurnId).toBe('turn-trace-open');
      expect(useChatTraceStore.getState().drawerOpen).toBe(true);
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-trace-open',
          trace_summary: {
            turn_id: 'turn-trace-open',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.5,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(messagesApi.getTrace).toHaveBeenCalledTimes(2);
    });
  });

  it('returns the composer to send mode after an agent response when interjection is disabled', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);

    render(<ChatPage />);

    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Please continue');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(expect.objectContaining({
        message: 'Please continue',
      }));
    });

    const pendingTurnId = String(vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id || '');
    expect(pendingTurnId).not.toBe('');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });
    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          turn_id: pendingTurnId,
          message_id: 'msg-agent-response-stop-reset',
          message_kind: 'assistant_final',
          content: 'Handled',
          timestamp: Date.now() / 1000,
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
  });

  it('restores missed rhythm segments from history before unlocking the composer', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Explain it');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });
    const pendingTurnId = String(
      vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id || '',
    );
    const presentationBaseMs = Date.now();
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce({
      user_id: 'local_user',
      session_id: 'session-1',
      history_version: 2,
      messages: [
        {
          message_id: 'msg-user-rhythm',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Explain it',
          timestamp: presentationBaseMs / 1000,
          turn_id: pendingTurnId,
          run_state: { state: 'completed' },
        },
        {
          message_id: 'msg-rhythm-1',
          message_kind: 'assistant_rhythm_segment',
          role: 'assistant',
          kind: 'assistant',
          content: 'First recovered segment',
          timestamp: presentationBaseMs / 1000 + 0.5,
          turn_id: pendingTurnId,
          payload: {
            rhythm: { segment_index: 0, segment_count: 2 },
          },
          run_state: { state: 'completed' },
        },
        {
          message_id: 'msg-rhythm-2',
          message_kind: 'assistant_rhythm_segment',
          role: 'assistant',
          kind: 'assistant',
          content: 'Second recovered segment',
          timestamp: presentationBaseMs / 1000 + 1.1,
          turn_id: pendingTurnId,
          payload: {
            rhythm: { segment_index: 1, segment_count: 2 },
          },
          run_state: { state: 'completed' },
        },
      ],
    } as any);

    act(() => {
      realtimeListener?.({
        event: 'turn_execution_control',
        data: {
          session_id: 'session-1',
          turn_id: pendingTurnId,
          state: 'completed',
        },
      });
    });

    await waitFor(() => {
      expect(
        useConversationStore.getState().messagesBySession['session-1']
          ?.some((message) => message.content === 'Second recovered segment'),
      ).toBe(true);
    });
    expect(screen.queryByText('First recovered segment')).not.toBeInTheDocument();
    expect(screen.queryByText('Second recovered segment')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();

    expect(await screen.findByText(
      'First recovered segment',
      {},
      { timeout: 1_000 },
    )).toBeInTheDocument();
    expect(screen.queryByText('Second recovered segment')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();

    expect(await screen.findByText(
      'Second recovered segment',
      {},
      { timeout: 2_000 },
    )).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
  });

  it('does not merge a fallback history snapshot while the turn is still running', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Keep the local turn');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    const pendingTurnId = String(
      vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id || '',
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });
    const historyCallsBeforeCompletion = vi.mocked(
      messagesApi.getHistory,
    ).mock.calls.length;

    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce({
      user_id: 'local_user',
      session_id: 'session-1',
      history_version: 9,
      messages: [
        {
          message_id: 'msg-running-server-user',
          message_kind: 'user_text',
          role: 'user',
          kind: 'user',
          content: 'Keep the local turn',
          timestamp: Date.now() / 1000,
          turn_id: pendingTurnId,
          run_state: { state: 'running' },
        },
        {
          message_id: 'msg-running-server-only',
          message_kind: 'assistant_interim',
          role: 'assistant',
          kind: 'assistant',
          content: 'Unsafe running history snapshot',
          timestamp: Date.now() / 1000,
          turn_id: pendingTurnId,
          run_state: { state: 'running' },
        },
      ],
    } as any);

    act(() => {
      realtimeListener?.({
        event: 'turn_execution_control',
        data: {
          session_id: 'session-1',
          turn_id: pendingTurnId,
          state: 'completed',
        },
      });
    });

    await waitFor(() => {
      expect(messagesApi.getHistory).toHaveBeenCalledTimes(
        historyCallsBeforeCompletion + 1,
      );
    });
    expect(screen.queryByText('Unsafe running history snapshot')).not.toBeInTheDocument();
    expect(
      useConversationStore.getState().messagesBySession['session-1']
        ?.some((message) => message.content === 'Unsafe running history snapshot'),
    ).toBe(false);
    expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
  });

  it('does not carry a pending-turn lock into another session', async () => {
    const user = userEvent.setup();
    const config = buildConfigWithVision(true) as any;
    config.data.preferences = {
      ...(config.data.preferences || {}),
      allow_interjection: false,
    };
    vi.mocked(configApi.get).mockResolvedValue(config);
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'Session 1',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
      {
        session_id: 'session-2',
        title: 'Session 2',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');

    render(<ChatPage />);
    await waitFor(() => expect(configApi.get).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText('chat.inputPlaceholder'), 'Keep working');
    await user.click(screen.getByRole('button', { name: 'chat.send' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.stop' })).toBeInTheDocument();
    });
    const pendingTurnId = String(
      vi.mocked(messagesApi.sendMessage).mock.calls[0]?.[0]?.client_turn_id || '',
    );

    act(() => {
      useConversationStore.getState().setCurrentSessionId('session-2');
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          turn_id: pendingTurnId,
          message_id: 'msg-background-session-final',
          message_kind: 'assistant_final',
          content: 'Finished in the background',
          timestamp: Date.now() / 1000,
        },
      });
      useConversationStore.getState().setCurrentSessionId('session-1');
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'chat.send' })).toBeInTheDocument();
    });
  });

  it('preserves millisecond timestamps from realtime agent responses', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          message_id: 'msg-final-ms',
          message_kind: 'assistant_final',
          content: '毫秒时间戳',
          timestamp: 1710000000000,
          turn_id: 'turn-ms',
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('毫秒时间戳')).toBeInTheDocument();
    });

    expect(
      useConversationStore.getState().messagesBySession['session-1']?.find((message) => message.turnId === 'turn-ms')?.timestamp
    ).toBe(1710000000000);
  });

  it('shows assistant image attachments immediately from realtime agent responses', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          message_id: 'msg-final-image-live',
          message_kind: 'assistant_final',
          content: '图片已生成。',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-image-live',
          attachments: [
            {
              attachment_id: 'att-image-live',
              kind: 'image',
              original_name: 'live.png',
              size_bytes: 2048,
            },
          ],
        },
      });
    });

    expect(await screen.findByRole('img', { name: 'live.png' })).toHaveAttribute(
      'src',
      'http://127.0.0.1:8000/api/messages/session/session-1/attachments/att-image-live/content?user_id=local_user',
    );
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

  it('renders a subtle trace entry for direct replies when ux plan requests collapsible trace display', async () => {
    const view = render(<ChatPage />);
    const scoped = within(view.container);

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '你好，我在。',
          timestamp: Date.now() / 1000,
          turn_id: 'turn-direct-visible',
          ux_plan: {
            assistant_surface_mode: 'final_only',
            trace_display_mode: 'collapsible',
          },
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-direct-visible',
            mode: 'direct_llm',
            status: 'completed',
            headline: '直答已完成',
            active_steps: 0,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(scoped.getByText('你好，我在。')).toBeInTheDocument();
    });

    expect(view.container.querySelector('[data-trace-variant="default"]')).toBeInTheDocument();
  });

  it('keeps the default trace entry style when ux plan requests prominent trace display', async () => {
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

    expect(view.container.querySelector('[data-trace-variant="default"]')).toBeInTheDocument();
    expect(view.container.querySelector('[data-trace-variant="prominent"]')).not.toBeInTheDocument();
  });

  it('renders an interim assistant message when turn ux plan requests interim-then-final', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-2',
          message_id: 'msg-interim-1',
          message_kind: 'assistant_interim',
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
    expect(
      useConversationStore.getState().messagesBySession['session-1']?.find((message) => message.turnId === 'turn-2' && message.kind === 'assistant')?.id
    ).toBe('msg-interim-1');

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
    expect(screen.getByText('稍等我查一下')).toBeInTheDocument();
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
      expect(screen.getAllByText('👌').length).toBeGreaterThan(0);
    });

    act(() => {
      realtimeListener?.({
        event: 'agent_response',
        data: {
          session_id: 'session-1',
          content: '👌',
          timestamp: Date.now() / 1000,
          message_id: 'msg-reaction-only',
          message_kind: 'assistant_reaction',
          turn_id: 'turn-3',
          ux_plan: {
            assistant_surface_mode: 'reaction_only',
            reaction_style: 'acknowledge',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.queryByText('msg-reaction-only')).not.toBeInTheDocument();
    });
  });

  it('rehydrates a persisted reaction-only turn without creating an assistant bubble', async () => {
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-user-reaction',
          message_kind: 'user_text',
          role: 'user',
          content: '嗯',
          timestamp: 1000,
          turn_id: 'turn-reaction-history',
          kind: 'user',
          label: {
            kind: 'emoji',
            text: '👌',
            applied_by: 'assistant',
            source: 'reaction_only',
            created_at_ms: 1001,
          },
        },
      ])
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getAllByText('嗯').length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText('👌').length).toBeGreaterThan(0);
    expect(screen.queryByText('msg-reaction-only')).not.toBeInTheDocument();
    expect(
      useConversationStore.getState().messagesBySession['session-1']?.filter((message) => message.turnId === 'turn-reaction-history')
    ).toHaveLength(1);
  });

  it('hides trace entry after reload when persisted history says trace display is none', async () => {
    useConversationStore.getState().receiveHistory(
      'session-1',
      normalizeHistoryMessages([
        {
          message_id: 'msg-final-hidden',
          message_kind: 'assistant_final',
          role: 'assistant',
          content: '整理好了',
          timestamp: 1000,
          turn_id: 'turn-hidden-history',
          kind: 'assistant',
          trace_available: true,
          trace_summary: {
            turn_id: 'turn-hidden-history',
            mode: 'function_calling',
            status: 'completed',
            headline: '工具链已完成',
            active_steps: 0,
            completed_steps: 2,
            failed_steps: 0,
            duration_seconds: 1.2,
            trace_available: true,
          },
          trace_display_mode: 'none',
          allow_trace_collapse: false,
        },
      ])
    );

    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getAllByText('整理好了').length).toBeGreaterThan(0);
    });

    const hiddenMessage = useConversationStore.getState().messagesBySession['session-1']
      ?.find((message) => message.turnId === 'turn-hidden-history');
    expect(hiddenMessage?.traceDisplayMode).toBe('none');
    expect(
      shouldShowTraceEntry(hiddenMessage ?? { turnId: '', traceDisplayMode: null, traceAvailable: false, traceSummary: null })
    ).toBe(false);
  });

  it('renders an interim assistant bubble when ux plan requests visible thinking feedback', async () => {
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

  it('renders tool-call runtime details inside the assistant bubble', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'msg-tool-runtime',
      role: 'assistant',
      kind: 'assistant',
      content: '',
      timestamp: 1000,
      turnId: 'turn-tool-runtime',
      streaming: true,
      toolCalls: [
        {
          toolCallId: 'call-1',
          toolName: 'web-search',
          status: 'running',
          toolArgsText: '{"query":"magi memory architecture"}',
        },
      ],
    });

    render(<ChatPage />);

    const panels = await screen.findAllByTestId('chat-assistant-runtime-panel');
    const panel = panels.find((candidate) => within(candidate).queryByText('web-search'));
    expect(panel).toBeDefined();
    if (!panel) {
      throw new Error('Expected a runtime panel containing the tool-call details.');
    }
    expect(within(panel).getByText('chat.runtime.label')).toBeInTheDocument();
    expect(within(panel).getByText('chat.toolCalls.label')).toBeInTheDocument();
    expect(within(panel).getByText('web-search')).toBeInTheDocument();
    expect(within(panel).getByText('chat.toolCalls.running')).toBeInTheDocument();
    expect(within(panel).getByText('{"query":"magi memory architecture"}')).toBeInTheDocument();
  });

  it('renders tool-call assistant narration inside runtime activity', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'msg-status-runtime',
      role: 'assistant',
      kind: 'assistant',
      content: '',
      timestamp: 1000,
      turnId: 'turn-status-runtime',
      streaming: true,
      runtimeStatuses: [
        {
          source: 'assistant_tool_call',
          stepLabel: 'tool_call_narration',
          content: '工作区是空的，附件解析也失败了。我先试试提取它们。',
        },
      ],
    });

    render(<ChatPage />);

    const panels = await screen.findAllByTestId('chat-assistant-runtime-panel');
    const panel = panels.find((candidate) => within(candidate).queryByText('工作区是空的，附件解析也失败了。我先试试提取它们。'));
    expect(panel).toBeDefined();
    if (!panel) {
      throw new Error('Expected a runtime panel containing assistant narration.');
    }
    expect(within(panel).getByText('chat.runtime.status')).toBeInTheDocument();
    expect(within(panel).getByText('工作区是空的，附件解析也失败了。我先试试提取它们。')).toBeInTheDocument();
  });

  it('renders streamed reasoning details inside the assistant bubble', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-1',
        title: 'New Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'session-1');
    useConversationStore.getState().upsertMessage('session-1', {
      id: 'msg-reasoning-runtime',
      role: 'assistant',
      kind: 'assistant',
      content: '先看一下代码路径。',
      timestamp: 1001,
      turnId: 'turn-reasoning-runtime',
      streaming: true,
      reasoning: [
        {
          source: 'planner',
          stepLabel: 'Plan',
          content: 'Inspecting the execution path',
        },
      ],
    });

    render(<ChatPage />);

    const panels = await screen.findAllByTestId('chat-assistant-runtime-panel');
    const panel = panels.find((candidate) => within(candidate).queryByText('Inspecting the execution path'));
    expect(panel).toBeDefined();
    if (!panel) {
      throw new Error('Expected a runtime panel containing the reasoning details.');
    }
    expect(within(panel).getByText('chat.runtime.label')).toBeInTheDocument();
    expect(within(panel).getByText('chat.thinking.label')).toBeInTheDocument();
    expect(within(panel).getByText('Inspecting the execution path')).toBeInTheDocument();
    expect(screen.getByText('先看一下代码路径。')).toBeInTheDocument();
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

    expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', 'session-1');
  });

  it('shows a trace status row on the user turn when a turn is interrupted without assistant output', async () => {
    render(<ChatPage />);

    act(() => {
      useConversationStore.getState().appendPendingTurn({
        sessionId: 'session-1',
        input: '先帮我看登录流程',
        turnId: 'turn-interrupted',
        timestamp: Date.now(),
        pendingLabel: 'thinking',
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interrupted',
          trace_summary: {
            turn_id: 'turn-interrupted',
            mode: 'function_calling',
            status: 'interrupted',
            headline: 'Interrupted by a newer turn',
            active_steps: 0,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Interrupted by a newer turn')).toBeInTheDocument();
    });

    expect(screen.getAllByRole('button', { name: 'chat.trace.view' }).length).toBeGreaterThan(0);
  });

  it('requests run cancellation from the running interim execution bubble', async () => {
    vi.mocked(messagesApi.cancelRun).mockResolvedValue({
      success: true,
      message: 'cancelled',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        run_id: 'run-1',
        status: 'cancelling',
      },
    });

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          trace_summary: {
            turn_id: 'turn-running',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('正在分析项目')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
    await userEvent.click(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' }));

    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledWith('local_user', 'session-1', {
        reason: 'user_cancel',
        turnId: 'turn-running',
      });
    });
  });

  it('requests background handoff from the running interim execution bubble', async () => {
    vi.mocked(messagesApi.detachRun).mockResolvedValue({
      success: true,
      message: 'detaching',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        run_id: 'run-1',
        status: 'detaching',
      },
    });

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          trace_summary: {
            turn_id: 'turn-running',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('正在分析项目')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
    await userEvent.click(within(runningPanel).getByRole('button', { name: 'chat.trace.detachRun' }));

    await waitFor(() => {
      expect(messagesApi.detachRun).toHaveBeenCalledWith('local_user', 'session-1', {
        reason: 'user_detach',
        turnId: 'turn-running',
      });
    });
  });

  it('shows execution actions on assistant interim messages and can cancel the run', async () => {
    vi.mocked(messagesApi.cancelRun).mockResolvedValue({
      success: true,
      message: 'cancelled',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        run_id: 'run-1',
        status: 'cancelling',
      },
    });

    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-actions',
          message_id: 'msg-interim-actions',
          message_kind: 'assistant_interim',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
            interim_text: '让我仔细想想再回复你。',
            trace_display_mode: 'prominent',
            allow_trace_collapse: true,
          },
        },
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-actions',
          trace_summary: {
            turn_id: 'turn-interim-actions',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('让我仔细想想再回复你。')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-interim-actions');
    await userEvent.click(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' }));

    await waitFor(() => {
      expect(messagesApi.cancelRun).toHaveBeenCalledWith('local_user', 'session-1', {
        reason: 'user_cancel',
        turnId: 'turn-interim-actions',
      });
    });
  });

  it('keeps interim execution actions visible after a todo state card appears', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'turn_ux_plan',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-todo',
          message_id: 'msg-interim-todo',
          message_kind: 'assistant_interim',
          ux_plan: {
            assistant_surface_mode: 'interim_then_final',
            interim_text: '让我仔细想想再回复你。',
            trace_display_mode: 'prominent',
            allow_trace_collapse: true,
          },
        },
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-interim-todo',
          trace_summary: {
            turn_id: 'turn-interim-todo',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 1,
            completed_steps: 0,
            failed_steps: 0,
            duration_seconds: 0.8,
            trace_available: true,
          },
        },
      });
    });

    act(() => {
      realtimeListener?.({
        event: 'chat_message_upserted',
        data: {
          session_id: 'session-1',
          message: {
            message_id: 'todo:turn-interim-todo',
            message_kind: 'todo_state',
            role: 'assistant',
            kind: 'status',
            content: 'Search official sources',
            timestamp: Date.now() / 1000,
            turn_id: 'turn-interim-todo',
            payload: {
              items: [
                { id: 'todo-1', content: 'Search official sources', status: 'in_progress' },
              ],
            },
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Search official sources')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-interim-todo');
    expect(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeInTheDocument();
    expect(within(runningPanel).getByRole('button', { name: 'chat.trace.detachRun' })).toBeInTheDocument();
  });

  it('updates the running interim execution bubble from execution control websocket events', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          trace_summary: {
            turn_id: 'turn-running',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
          },
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
      expect(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeEnabled();
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_execution_control',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          state: 'cancelling',
          can_cancel: false,
          label: 'Cancelling run',
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
      expect(within(runningPanel).getByText('chat.trace.execution.cancellingTitle')).toBeInTheDocument();
      expect(within(runningPanel).getByText('chat.trace.execution.cancellingBody')).toBeInTheDocument();
      expect(within(runningPanel).getByRole('button', { name: 'chat.trace.cancelRun' })).toBeDisabled();
    });

    act(() => {
      realtimeListener?.({
        event: 'turn_execution_control',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-running',
          state: 'cancelled',
          can_cancel: false,
          label: 'Run cancelled',
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-running');
      expect(within(runningPanel).getByText('chat.trace.execution.cancelledTitle')).toBeInTheDocument();
      expect(within(runningPanel).getByText('chat.trace.execution.cancelledBody')).toBeInTheDocument();
      expect(within(runningPanel).getByText('chat.trace.execution.footerCancelled')).toBeInTheDocument();
      expect(within(runningPanel).queryByRole('button', { name: 'chat.trace.cancelRun' })).not.toBeInTheDocument();
      expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', 'session-1');
    });
  });

  it('renders a richer orchestration plan preview on the running interim execution bubble', async () => {
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        event: 'execution_trace_update',
        data: {
          session_id: 'session-1',
          turn_id: 'turn-plan-preview',
          trace_summary: {
            turn_id: 'turn-plan-preview',
            mode: 'orchestration',
            status: 'running',
            headline: '正在分析项目',
            active_steps: 2,
            completed_steps: 1,
            failed_steps: 0,
            duration_seconds: 1.4,
            trace_available: true,
            plan_summary: {
              planner: 'task_agent',
              parallel_mode: 'parallel',
              total_steps: 4,
              remaining_steps: 1,
              steps: [
                {
                  subtask_id: 'subtask_1',
                  label: '梳理现有文档和范围',
                  status: 'completed',
                },
                {
                  subtask_id: 'subtask_2',
                  label: '盘点代码结构与运行方式',
                  status: 'running',
                },
                {
                  subtask_id: 'subtask_3',
                  label: '整理 MVP 验收清单',
                  status: 'pending',
                },
              ],
            },
          },
        },
      });
    });

    await waitFor(() => {
      const runningPanel = screen.getByTestId('chat-execution-panel-turn-plan-preview');
      expect(within(runningPanel).getByText('梳理现有文档和范围')).toBeInTheDocument();
    });

    const runningPanel = screen.getByTestId('chat-execution-panel-turn-plan-preview');
    expect(within(runningPanel).getByText('盘点代码结构与运行方式')).toBeInTheDocument();
    expect(within(runningPanel).getByText('整理 MVP 验收清单')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stage.runningParallel')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.parallel')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stepStatus.completed')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stepStatus.running')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.stepStatus.pending')).toBeInTheDocument();
    expect(within(runningPanel).getByText('chat.trace.plan.moreSteps')).toBeInTheDocument();
  });

  it('does not ask the backend for a current session after subscribe event', () => {
    useConversationStore.getState().setCurrentSessionId(null);
    vi.mocked(messagesApi.sendMessage).mockClear();
    render(<ChatPage />);

    act(() => {
      realtimeListener?.({
        type: 'subscribed',
      });
    });

    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
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
