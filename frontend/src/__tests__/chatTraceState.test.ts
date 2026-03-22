import { describe, expect, it } from 'vitest';
import {
  applyAgentResponse,
  applyTurnUxPlan,
  createPendingTurn,
  flattenPlanningNodeForDisplay,
  normalizeHistoryMessages,
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

  it('replaces the interim assistant card with the final assistant answer', () => {
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

    expect(next).toHaveLength(2);
    expect(next[1].kind).toBe('assistant');
    expect(next[1].content).toContain('final answer');
    expect(next[1].traceAvailable).toBe(true);
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
