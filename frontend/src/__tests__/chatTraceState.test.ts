import { describe, expect, it } from 'vitest';
import {
  applyAgentResponse,
  createPendingTurn,
  normalizeHistoryMessages,
  normalizeTraceSummary,
  upsertTraceSummary,
} from '@/pages/chat-state';

describe('chat trace state helpers', () => {
  it('creates a compact pending turn with user and status messages', () => {
    const messages = createPendingTurn('Analyze this repo', 'turn_1', 1000, 'Thinking');

    expect(messages).toHaveLength(2);
    expect(messages[0].kind).toBe('user');
    expect(messages[1].kind).toBe('status');
    expect(messages[1].content).toBe('Thinking');
  });

  it('updates the status card instead of appending worker-like messages', () => {
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

  it('replaces the pending status card with the final assistant answer', () => {
    const initial = createPendingTurn('Analyze this repo', 'turn_1', 1000, 'Thinking');
    const next = applyAgentResponse(initial, {
      response: 'Here is the final answer.',
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
});
