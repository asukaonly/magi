import { describe, expect, it } from 'vitest';
import {
  applyAgentResponse,
  applyTurnUxPlan,
  createPendingTurn,
  flattenPlanningNodeForDisplay,
  normalizeHistoryMessages,
  normalizeTraceSnapshot,
  normalizeTraceSummary,
  shouldShowTraceEntry,
  upsertTraceSummary,
} from '@/pages/chat-state';

describe('chat trace state helpers', () => {
  it('creates a compact pending turn with only the user message by default', () => {
    const messages = createPendingTurn('Analyze this repo', 'turn_1', 1000, 'Thinking');

    expect(messages).toHaveLength(1);
    expect(messages[0].kind).toBe('user');
  });

  it('adds a status card when trace activity begins', () => {
    const initial = createPendingTurn('Analyze this repo', 'turn_1', 1000, 'Thinking');
    const summary = normalizeTraceSummary({
      turn_id: 'turn_1',
      mode: 'orchestration',
      status: 'running',
      headline: '正在执行工具链',
      active_steps: 2,
      completed_steps: 1,
      failed_steps: 0,
      duration_seconds: 1.8,
      trace_available: true,
      orchestration_id: 'orch_1',
    });

    const next = upsertTraceSummary(initial, 'turn_1', summary);

    expect(next).toHaveLength(2);
    expect(next[1].kind).toBe('status');
    expect(next[1].content).toBe('正在执行工具链');
    expect(next[1].traceAvailable).toBe(true);
  });

  it('does not add a trace status card when ux plan hides trace display', () => {
    const initial = applyTurnUxPlan(
      createPendingTurn('Analyze this repo', 'turn_hidden', 1000, 'Thinking'),
      'turn_hidden',
      {
        assistantSurfaceMode: 'final_only',
        traceDisplayMode: 'none',
      }
    );
    const summary = normalizeTraceSummary({
      turn_id: 'turn_hidden',
      mode: 'function_calling',
      status: 'running',
      headline: '正在执行工具链',
      active_steps: 1,
      completed_steps: 0,
      failed_steps: 0,
      duration_seconds: 0.4,
      trace_available: true,
    });

    const next = upsertTraceSummary(initial, 'turn_hidden', summary);

    expect(next).toHaveLength(1);
    expect(next[0].kind).toBe('user');
  });

  it('hides trace entry helper output when trace display mode is none', () => {
    const hiddenMessage = applyAgentResponse(
      applyTurnUxPlan(
        createPendingTurn('Analyze this repo', 'turn-hidden', 1000, 'Thinking'),
        'turn-hidden',
        {
          assistantSurfaceMode: 'final_only',
          traceDisplayMode: 'none',
        }
      ),
      {
        content: '整理好了',
        timestamp: 2000,
        turnId: 'turn-hidden',
        uxPlan: {
          assistantSurfaceMode: 'final_only',
          traceDisplayMode: 'none',
        },
        traceSummary: normalizeTraceSummary({
          turn_id: 'turn-hidden',
          mode: 'function_calling',
          status: 'completed',
          headline: '工具链已完成',
          active_steps: 0,
          completed_steps: 2,
          failed_steps: 0,
          duration_seconds: 1.2,
          trace_available: true,
        }),
        traceAvailable: true,
      }
    )[0];

    expect(shouldShowTraceEntry(hiddenMessage)).toBe(false);
  });

  it('keeps trace entry helper enabled for prominent trace display', () => {
    const prominentMessage = applyAgentResponse(
      applyTurnUxPlan(
        createPendingTurn('Analyze this repo', 'turn-prominent', 1000, 'Thinking'),
        'turn-prominent',
        {
          assistantSurfaceMode: 'final_only',
          traceDisplayMode: 'prominent',
          allowTraceCollapse: true,
        }
      ),
      {
        content: '整理好了',
        timestamp: 2000,
        turnId: 'turn-prominent',
        uxPlan: {
          assistantSurfaceMode: 'final_only',
          traceDisplayMode: 'prominent',
          allowTraceCollapse: true,
        },
        traceSummary: normalizeTraceSummary({
          turn_id: 'turn-prominent',
          mode: 'function_calling',
          status: 'completed',
          headline: '工具链已完成',
          active_steps: 0,
          completed_steps: 2,
          failed_steps: 0,
          duration_seconds: 1.2,
          trace_available: true,
        }),
        traceAvailable: true,
      }
    ).find((message) => message.kind === 'assistant')!;

    expect(prominentMessage.traceDisplayMode).toBe('prominent');
    expect(shouldShowTraceEntry(prominentMessage)).toBe(true);
  });

  it('preserves trace continuation metadata when normalizing a snapshot', () => {
    const snapshot = normalizeTraceSnapshot({
      turn_id: 'turn-2',
      user_id: 'user-1',
      session_id: 'session-1',
      status: 'interrupted',
      mode: 'function_calling',
      started_at: 1000,
      ended_at: 2000,
      continued_from_turn_id: 'turn-1',
      continued_from_trace_id: 'trace:turn-1',
      superseded_by_turn_id: 'turn-3',
      supersession_reason: 'interrupted',
      summary: {
        turn_id: 'turn-2',
        mode: 'function_calling',
        status: 'interrupted',
        headline: 'Interrupted by a newer turn',
        active_steps: 0,
        completed_steps: 1,
        failed_steps: 0,
        duration_seconds: 1,
        trace_available: true,
        continued_from_turn_id: 'turn-1',
        superseded_by_turn_id: 'turn-3',
      },
      root: {
        id: 'turn-2:root',
        kind: 'root',
        label: 'Tool chain',
        status: 'interrupted',
        metadata: {},
        children: [],
      },
    } as any);

    expect(snapshot?.continuedFromTurnId).toBe('turn-1');
    expect(snapshot?.continuedFromTraceId).toBe('trace:turn-1');
    expect(snapshot?.supersededByTurnId).toBe('turn-3');
    expect(snapshot?.supersessionReason).toBe('interrupted');
    expect(snapshot?.summary.continuedFromTurnId).toBe('turn-1');
    expect(snapshot?.summary.supersededByTurnId).toBe('turn-3');
  });

  it('adds an interim assistant message for interim-then-final turns', () => {
    const initial = createPendingTurn('Analyze this repo', 'turn_1', 1000, 'Thinking');
    const next = applyTurnUxPlan(initial, 'turn_1', {
      assistantSurfaceMode: 'interim_then_final',
      interimText: '稍等我查一下',
    });

    expect(next).toHaveLength(2);
    expect(next[1].kind).toBe('assistant');
    expect(next[1].content).toBe('稍等我查一下');
    expect(next[1].turnId).toBe('turn_1');
  });

  it('adds a lightweight reaction to the user message for reaction-only turns', () => {
    const initial = createPendingTurn('嗯', 'turn_2', 1000, 'Thinking');
    const next = applyTurnUxPlan(initial, 'turn_2', {
      assistantSurfaceMode: 'reaction_only',
      reactionStyle: 'acknowledge',
    });

    expect(next).toHaveLength(1);
    expect(next[0].kind).toBe('user');
    expect(next[0].reaction).toBe('👌');
  });

  it('applies persisted assistant reaction payloads without creating an assistant bubble', () => {
    const initial = createPendingTurn('嗯', 'turn_2', 1000, 'Thinking');
    const next = applyAgentResponse(initial, {
      content: '👌',
      timestamp: 2000,
      messageId: 'msg-reaction-1',
      messageKind: 'assistant_reaction',
      turnId: 'turn_2',
    });

    expect(next).toHaveLength(1);
    expect(next[0].kind).toBe('user');
    expect(next[0].reaction).toBe('👌');
  });

  it('adds a status card when thinking indicator asks for visible feedback', () => {
    const initial = createPendingTurn('查一下最近状态', 'turn_3', 1000, 'Thinking');
    const next = applyTurnUxPlan(
      initial,
      'turn_3',
      {
        assistantSurfaceMode: 'final_only',
        thinkingIndicator: 'visible',
      },
      {
        pendingLabel: '正在思考',
      }
    );

    expect(next).toHaveLength(2);
    expect(next[1].kind).toBe('status');
    expect(next[1].content).toBe('正在思考');
  });

  it('keeps the interim assistant card and appends the final assistant answer', () => {
    const initial = applyTurnUxPlan(
      createPendingTurn('Analyze this repo', 'turn_1', 1000, 'Thinking'),
      'turn_1',
      {
        assistantSurfaceMode: 'interim_then_final',
        interimText: '稍等我查一下',
      }
    );
    const next = applyAgentResponse(initial, {
      content: 'Here is the final answer.',
      timestamp: 2000,
      turnId: 'turn_1',
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn_1',
        mode: 'orchestration',
        status: 'completed',
        headline: '工具链已完成',
        active_steps: 0,
        completed_steps: 3,
        failed_steps: 0,
        duration_seconds: 3.2,
        trace_available: true,
        orchestration_id: 'orch_1',
      }),
      traceAvailable: true,
    });

    expect(next).toHaveLength(3);
    expect(next[1].messageKind).toBe('assistant_interim');
    expect(next[1].content).toContain('稍等我查一下');
    expect(next[2].messageKind).toBe('assistant_final');
    expect(next[2].content).toContain('final answer');
    expect(next[2].traceAvailable).toBe(true);
  });

  it('reuses the pending turn id when the final response arrives without turn metadata', () => {
    const initial = createPendingTurn('Analyze this repo', 'turn_9', 1000, 'Thinking');
    const next = applyAgentResponse(initial, {
      content: 'Final answer from the backend.',
      timestamp: 2000,
    });

    expect(next).toHaveLength(2);
    expect(next[1].kind).toBe('assistant');
    expect(next[1].turnId).toBe('turn_9');
    expect(next[1].content).toContain('Final answer');
  });

  it('normalizes history messages with trace metadata', () => {
    const normalized = normalizeHistoryMessages([
      {
        role: 'assistant',
        content: 'Thinking...',
        timestamp: 1000,
        turn_id: 'turn_2',
        kind: 'status',
        trace_available: true,
        trace_summary: {
          turn_id: 'turn_2',
          mode: 'function_calling',
          status: 'running',
          headline: '正在执行工具链',
          active_steps: 1,
          completed_steps: 0,
          failed_steps: 0,
          duration_seconds: 0.6,
          trace_available: true,
        },
      },
    ]);

    expect(normalized[0].kind).toBe('status');
    expect(normalized[0].traceSummary?.turnId).toBe('turn_2');
    expect(normalized[0].traceAvailable).toBe(true);
  });

  it('preserves attachment metadata when normalizing history messages', () => {
    const normalized = normalizeHistoryMessages([
      {
        role: 'user',
        content: '',
        timestamp: 1000,
        turn_id: 'turn_attachment_history',
        kind: 'user',
        attachments: [
          {
            attachment_id: 'att-1',
            kind: 'pdf',
            original_name: 'report.pdf',
            size_bytes: 1024,
          },
        ],
      },
    ]);

    expect(normalized[0].attachments).toEqual([
      {
        attachment_id: 'att-1',
        kind: 'pdf',
        original_name: 'report.pdf',
        size_bytes: 1024,
      },
    ]);
  });

  it('normalizes reply previews from history payloads', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'msg-reply',
        message_kind: 'user_text',
        role: 'user',
        content: 'Can you expand on that?',
        timestamp: 1000,
        turn_id: 'turn_reply',
        kind: 'user',
        reply_to: {
          message_id: 'msg-assistant-root',
          role: 'assistant',
          message_kind: 'assistant_final',
          content_excerpt: 'Run the desktop dev script from the repo root.',
        },
      },
    ]);

    expect(normalized[0].replyTo).toEqual({
      messageId: 'msg-assistant-root',
      role: 'assistant',
      messageKind: 'assistant_final',
      contentExcerpt: 'Run the desktop dev script from the repo root.',
    });
  });

  it('attaches a terminal trace summary back onto the user turn when no assistant row exists', () => {
    const initial = createPendingTurn('Analyze this repo', 'turn_user_only', 1000, 'Thinking');
    const next = upsertTraceSummary(
      initial,
      'turn_user_only',
      normalizeTraceSummary({
        turn_id: 'turn_user_only',
        mode: 'function_calling',
        status: 'interrupted',
        headline: 'Interrupted by a newer turn',
        active_steps: 0,
        completed_steps: 1,
        failed_steps: 0,
        duration_seconds: 0.8,
        trace_available: true,
      })
    );

    const userMessage = next.find((message) => message.role === 'user');
    expect(userMessage?.traceSummary?.status).toBe('interrupted');
    expect(userMessage?.traceAvailable).toBe(true);
  });

  it('normalizes second-based history timestamps into millisecond timestamps', () => {
    const normalized = normalizeHistoryMessages([
      {
        role: 'assistant',
        content: '时间测试',
        timestamp: 1710000000,
        turn_id: 'turn_ts',
        kind: 'assistant',
      },
    ]);

    expect(normalized[0].timestamp).toBe(1710000000 * 1000);
  });

  it('hydrates reaction-only history rows onto the persisted user message', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'msg-user',
        message_kind: 'user_text',
        role: 'user',
        content: '嗯',
        timestamp: 1000,
        turn_id: 'turn_reaction',
        kind: 'user',
      },
      {
        message_id: 'msg-reaction',
        message_kind: 'assistant_reaction',
        role: 'assistant',
        content: '👌',
        timestamp: 1001,
        turn_id: 'turn_reaction',
        kind: 'assistant',
      },
    ]);

    expect(normalized).toHaveLength(1);
    expect(normalized[0]).toMatchObject({
      id: 'msg-user',
      messageId: 'msg-user',
      turnId: 'turn_reaction',
      kind: 'user',
      content: '嗯',
      reaction: '👌',
    });
  });

  it('preserves persisted trace display preferences from history rows', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'msg-final',
        message_kind: 'assistant_final',
        role: 'assistant',
        content: '整理好了',
        timestamp: 1000,
        turn_id: 'turn_trace_hidden',
        kind: 'assistant',
        trace_available: true,
        trace_display_mode: 'none',
        allow_trace_collapse: false,
      },
    ]);

    expect(normalized[0]).toMatchObject({
      id: 'msg-final',
      messageId: 'msg-final',
      traceDisplayMode: 'none',
      allowTraceCollapse: false,
      traceAvailable: true,
    });
  });

  it('normalizes persisted message labels from history rows', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'msg-labeled',
        message_kind: 'assistant_final',
        role: 'assistant',
        content: 'Pinned answer',
        timestamp: 1000,
        turn_id: 'turn_label',
        kind: 'assistant',
        label: {
          kind: 'emoji',
          text: '👍',
          applied_by: 'user',
          source: 'manual',
          created_at_ms: 1100,
        },
      } as any,
    ]);

    expect(normalized[0].label).toEqual({
      kind: 'emoji',
      text: '👍',
      appliedBy: 'user',
      source: 'manual',
      createdAtMs: 1100,
    });
  });

  it('flattens the planning node out of the trace tree for drawer display', () => {
    const root = flattenPlanningNodeForDisplay({
      id: 'turn_1:root',
      kind: 'root',
      label: '工具链',
      status: 'running',
      startedAt: 1,
      endedAt: null,
      resultPreview: '',
      error: null,
      metadata: {},
      children: [
        {
          id: 'turn_1:planning',
          kind: 'planning',
          label: '任务编排',
          status: 'running',
          startedAt: 1,
          endedAt: null,
          resultPreview: '',
          error: null,
          metadata: {},
          children: [
            {
              id: 'turn_1:worker:1',
              kind: 'worker',
              label: 'scan backend',
              status: 'running',
              startedAt: 1,
              endedAt: null,
              resultPreview: '',
              error: null,
              metadata: {},
              children: [],
            },
          ],
        },
      ],
    });

    expect(root.children).toHaveLength(1);
    expect(root.children[0].kind).toBe('worker');
    expect(root.children[0].label).toBe('scan backend');
  });
});
