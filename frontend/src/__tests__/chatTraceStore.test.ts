import { beforeEach, describe, expect, it } from 'vitest';
import { useChatTraceStore } from '@/stores';

describe('chat trace store', () => {
  beforeEach(() => {
    useChatTraceStore.getState().reset();
  });

  it('preserves drawer state when history summaries are reloaded', () => {
    const store = useChatTraceStore.getState();
    store.openDrawer('turn_1');
    store.setSnapshot({
      turn_id: 'turn_1',
      user_id: 'local_user',
      session_id: 'session_1',
      status: 'completed',
      mode: 'orchestration',
      started_at: 1,
      ended_at: 2,
      summary: {
        turn_id: 'turn_1',
        mode: 'orchestration',
        status: 'completed',
        headline: '工具链已完成',
        active_steps: 0,
        completed_steps: 3,
        failed_steps: 0,
        duration_seconds: 1.0,
        trace_available: true,
      },
      root: {
        id: 'turn_1:root',
        kind: 'root',
        label: 'Root',
        status: 'completed',
        started_at: 1,
        ended_at: 2,
        result_preview: '',
        error: null,
        metadata: {},
        children: [],
      },
    });

    store.replaceSummaries([
      {
        turnId: 'turn_1',
        mode: 'orchestration',
        status: 'completed',
        headline: '工具链已完成',
        activeSteps: 0,
        completedSteps: 3,
        failedSteps: 0,
        durationSeconds: 1.0,
        traceAvailable: true,
        planSummary: null,
        continuedFromTurnId: null,
        continuedFromTraceId: null,
        supersededByTurnId: null,
        supersessionReason: null,
        totalInputTokens: 0,
        totalOutputTokens: 0,
        totalReasoningTokens: 0,
        runtimeMetrics: {},
      },
    ]);

    const next = useChatTraceStore.getState();
    expect(next.drawerOpen).toBe(true);
    expect(next.activeTurnId).toBe('turn_1');
    expect(next.snapshots.turn_1).toBeDefined();
    expect(next.summaries.turn_1).toBeDefined();
  });
});
