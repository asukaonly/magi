import { describe, expect, it } from 'vitest';
import {
  buildReplyPreviewFromMessage,
  getExecutionActionState,
  getChatPresentationSurface,
  projectControlStatusCardPresentation,
  projectExecutionProgressPresentation,
  projectChatTimelineMessage,
  projectChatTimelineRow,
} from '@/domain/chat/presentation';
import {
  applyAgentResponse,
  applyTurnUxPlan,
  buildSystemSuggestionTriggerText,
  createPendingTurn,
  type ChatTimelineMessage,
  flattenPlanningNodeForDisplay,
  normalizeHistoryMessages,
  normalizeTraceSnapshot,
  normalizeTraceSummary,
  shouldShowTraceEntry,
  upsertTraceSummary,
} from '@/domain/chat/state';

describe('chat trace state helpers', () => {
  it('creates a compact pending turn with only the user message by default', () => {
    const messages = createPendingTurn('Analyze this repo', 'turn_1', 1000, 'Thinking');

    expect(messages).toHaveLength(1);
    expect(messages[0].kind).toBe('user');
  });

  it('appends rhythm segments for the same turn instead of replacing earlier segments', () => {
    const first = applyAgentResponse([], {
      content: '先接住问题。',
      timestamp: 1000,
      messageId: 'msg-rhythm-1',
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 0, segment_count: 2 } },
    });

    const second = applyAgentResponse(first, {
      content: '再说明核心答案。',
      timestamp: 1200,
      messageId: 'msg-rhythm-2',
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 1, segment_count: 2 } },
    });

    expect(second).toHaveLength(2);
    expect(second.map((message) => message.content)).toEqual(['先接住问题。', '再说明核心答案。']);
  });

  it('keeps rhythm segments when the canonical compatibility event arrives later', () => {
    const first = applyAgentResponse([], {
      content: '先接住问题。',
      timestamp: 1000,
      messageId: 'msg-rhythm-1',
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 0, segment_count: 2 } },
    });
    const second = applyAgentResponse(first, {
      content: '再说明核心答案。',
      timestamp: 1200,
      messageId: 'msg-rhythm-2',
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 1, segment_count: 2 } },
    });

    const afterCanonicalEvent = applyAgentResponse(second, {
      content: '先接住问题。\n再说明核心答案。',
      timestamp: 1300,
      turnId: 'turn-rhythm',
    });

    expect(afterCanonicalEvent).toHaveLength(2);
    expect(afterCanonicalEvent.map((message) => message.messageKind)).toEqual([
      'assistant_rhythm_segment',
      'assistant_rhythm_segment',
    ]);
    expect(afterCanonicalEvent.map((message) => message.content)).toEqual(['先接住问题。', '再说明核心答案。']);
  });

  it('replaces rhythm segments with one final reply when a fallback final message arrives', () => {
    const first = applyAgentResponse([], {
      content: '先接住问题。',
      timestamp: 1000,
      messageId: 'msg-rhythm-1',
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 0, segment_count: 2 } },
    });
    const second = applyAgentResponse(first, {
      content: '再说明核心答案。',
      timestamp: 1200,
      messageId: 'msg-rhythm-2',
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 1, segment_count: 2 } },
    });

    const afterFallback = applyAgentResponse(second, {
      content: '先接住问题。\n再说明核心答案。',
      timestamp: 1300,
      messageId: 'msg-final',
      messageKind: 'assistant_final',
      turnId: 'turn-rhythm',
    });

    expect(afterFallback).toHaveLength(1);
    expect(afterFallback[0].messageKind).toBe('assistant_final');
    expect(afterFallback[0].messageId).toBe('msg-final');
    expect(afterFallback[0].content).toBe('先接住问题。\n再说明核心答案。');
  });

  it('waits for every rhythm segment before building the system suggestion trigger', () => {
    const userMessage: ChatTimelineMessage = {
      id: 'user-rhythm',
      role: 'user',
      kind: 'user',
      content: '这个功能怎么走？',
      timestamp: 1000,
      turnId: 'turn-rhythm',
    };
    const firstSegment: ChatTimelineMessage = {
      id: 'msg-rhythm-1',
      role: 'assistant',
      kind: 'assistant',
      content: '先正常生成完整回答。',
      timestamp: 1100,
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 0, segment_count: 2 } },
    };
    const secondSegment: ChatTimelineMessage = {
      id: 'msg-rhythm-2',
      role: 'assistant',
      kind: 'assistant',
      content: '再拆成几条自然气泡。',
      timestamp: 2100,
      messageKind: 'assistant_rhythm_segment',
      turnId: 'turn-rhythm',
      payload: { rhythm: { segment_index: 1, segment_count: 2 } },
    };

    expect(buildSystemSuggestionTriggerText([userMessage, firstSegment])).toBe('');
    expect(buildSystemSuggestionTriggerText([userMessage, firstSegment, secondSegment])).toBe(
      '这个功能怎么走？\n先正常生成完整回答。\n再拆成几条自然气泡。',
    );
  });

  it('keeps the system suggestion trigger behavior for single final replies', () => {
    expect(buildSystemSuggestionTriggerText([
      {
        id: 'user-final',
        role: 'user',
        kind: 'user',
        content: '说下结果',
        timestamp: 1000,
        turnId: 'turn-final',
      },
      {
        id: 'assistant-final',
        role: 'assistant',
        kind: 'assistant',
        content: '已经完成。',
        timestamp: 1200,
        messageKind: 'assistant_final',
        turnId: 'turn-final',
      },
    ])).toBe('说下结果\n已经完成。');
  });

  it('classifies control and runtime status surfaces explicitly', () => {
    expect(getChatPresentationSurface({
      id: 'msg-control',
      role: 'assistant',
      kind: 'status',
      content: 'Need approval',
      timestamp: 1000,
      messageKind: 'permission_request',
    })).toBe('control_status');

    expect(getChatPresentationSurface({
      id: 'msg-runtime',
      role: 'assistant',
      kind: 'status',
      content: 'Running tools',
      timestamp: 1001,
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn-runtime',
        mode: 'orchestration',
        status: 'running',
        headline: 'Running tools',
        active_steps: 1,
        completed_steps: 0,
        failed_steps: 0,
        duration_seconds: 0.2,
        trace_available: true,
      }),
    })).toBe('runtime_status');

    expect(getChatPresentationSurface({
      id: 'msg-transcript',
      role: 'assistant',
      kind: 'assistant',
      content: 'Done',
      timestamp: 1002,
      messageKind: 'assistant_final',
    })).toBe('transcript');
  });

  it('projects transcript decorations for interim, final, and interrupted user turns', () => {
    const interimAssistant = projectChatTimelineMessage({
      id: 'msg-interim',
      role: 'assistant',
      kind: 'assistant',
      content: 'Running tools',
      timestamp: 1000,
      messageKind: 'assistant_interim',
    });

    expect(interimAssistant.surface).toBe('transcript');
    if (interimAssistant.surface === 'transcript') {
      expect(interimAssistant.transcript.showExecutionBubbleFooter).toBe(true);
      expect(interimAssistant.transcript.showHeaderTraceEntry).toBe(false);
      expect(interimAssistant.transcript.bubbleTop.showReplyStrip).toBe(false);
      expect(interimAssistant.transcript.bubbleTop.showAttachments).toBe(false);
    }

    const finalAssistant = projectChatTimelineMessage({
      id: 'msg-final',
      role: 'assistant',
      kind: 'assistant',
      content: 'Done',
      timestamp: 1001,
      messageKind: 'assistant_final',
    });

    expect(finalAssistant.surface).toBe('transcript');
    if (finalAssistant.surface === 'transcript') {
      expect(finalAssistant.transcript.showExecutionBubbleFooter).toBe(false);
      expect(finalAssistant.transcript.showHeaderTraceEntry).toBe(true);
      expect(finalAssistant.transcript.belowBubble.showMessageLabel).toBe(false);
    }

    const secondRhythmSegment = projectChatTimelineMessage({
      id: 'msg-rhythm-2',
      role: 'assistant',
      kind: 'assistant',
      content: 'Second segment',
      timestamp: 1002,
      messageKind: 'assistant_rhythm_segment',
      payload: {
        rhythm: {
          segment_index: 1,
          segment_count: 2,
        },
      },
    });

    expect(secondRhythmSegment.surface).toBe('transcript');
    if (secondRhythmSegment.surface === 'transcript') {
      expect(secondRhythmSegment.transcript.showHeaderTraceEntry).toBe(false);
    }

    const interruptedUser = projectChatTimelineMessage({
      id: 'msg-user',
      role: 'user',
      kind: 'user',
      content: 'Continue',
      timestamp: 1002,
      reaction: '👌',
      replyTo: {
        messageId: 'msg-origin',
        role: 'assistant',
        contentExcerpt: 'Earlier answer',
      },
      attachments: [
        {
          attachment_id: 'att-1',
          kind: 'image',
          original_name: 'diagram.png',
          size_bytes: 1024,
        },
      ],
      label: {
        kind: 'custom',
        text: 'Follow up',
        appliedBy: 'local_user',
        source: 'manual',
        createdAtMs: 1003,
      },
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn-user',
        mode: 'function_calling',
        status: 'interrupted',
        headline: 'Interrupted by newer turn',
        active_steps: 0,
        completed_steps: 1,
        failed_steps: 0,
        duration_seconds: 0.8,
        trace_available: true,
      }),
    });

    expect(interruptedUser.surface).toBe('transcript');
    if (interruptedUser.surface === 'transcript') {
      expect(interruptedUser.transcript.belowBubble.showReactionBadge).toBe(true);
      expect(interruptedUser.transcript.bubbleTop.showReplyStrip).toBe(true);
      expect(interruptedUser.transcript.bubbleTop.showAttachments).toBe(true);
      expect(interruptedUser.transcript.belowBubble.showMessageLabel).toBe(true);
      expect(interruptedUser.transcript.belowBubble.showUserTraceStatus).toBe(true);
      expect(interruptedUser.transcript.actions.replyPreview).toBeNull();
      expect(interruptedUser.transcript.actions.canQuickLabel).toBe(false);
    }
  });

  it('shows recalled memories only on the terminal rhythm segment', () => {
    const recalledMemories = [{
      kind: 'event',
      sourceLayer: 'L1',
      statement: 'Visited example.com',
      topic: 'example.com',
    }];
    const firstSegment = projectChatTimelineMessage({
      id: 'msg-rhythm-1',
      role: 'assistant',
      kind: 'assistant',
      content: 'First segment',
      timestamp: 1000,
      messageKind: 'assistant_rhythm_segment',
      recalledMemories,
      payload: { rhythm: { segment_index: 0, segment_count: 2 } },
    });
    const terminalSegment = projectChatTimelineMessage({
      id: 'msg-rhythm-2',
      role: 'assistant',
      kind: 'assistant',
      content: 'Second segment',
      timestamp: 2000,
      messageKind: 'assistant_rhythm_segment',
      recalledMemories,
      payload: { rhythm: { segment_index: 1, segment_count: 2 } },
    });

    expect(firstSegment.surface).toBe('transcript');
    expect(terminalSegment.surface).toBe('transcript');
    if (firstSegment.surface === 'transcript' && terminalSegment.surface === 'transcript') {
      expect(firstSegment.transcript.showRecalledMemories).toBe(false);
      expect(terminalSegment.transcript.showRecalledMemories).toBe(true);
    }
  });

  it('keeps trace entry available on transcript rows when only the stored summary reports trace availability', () => {
    const projected = projectChatTimelineRow({
      id: 'msg-background-ack',
      role: 'assistant',
      kind: 'assistant',
      content: 'Started background task: Repo sync. I\'ll let you know when it finishes.',
      timestamp: 1000,
      turnId: 'turn-background',
      messageKind: 'assistant_final',
      traceAvailable: false,
    }, {
      summaries: {
        'turn-background': {
          traceAvailable: true,
        },
      },
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: [],
    });

    expect(projected.surface).toBe('transcript');
    if (projected.surface === 'transcript') {
      expect(projected.transcript.showHeaderTraceEntry).toBe(true);
      expect(projected.transcript.traceEntry.canOpen).toBe(true);
      expect(projected.transcript.traceEntry.turnId).toBe('turn-background');
    }
  });

  it('hides the interim execution panel once the turn has a final assistant message', () => {
    const interimMessage: ChatTimelineMessage = {
      id: 'msg-interim',
      role: 'assistant',
      kind: 'assistant',
      content: 'Let me think...',
      timestamp: 1000,
      turnId: 'turn-1',
      messageKind: 'assistant_interim',
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn-1',
        mode: 'plan',
        status: 'completed',
        headline: 'Planned',
        active_steps: 0,
        completed_steps: 3,
        failed_steps: 0,
        duration_seconds: 5,
        trace_available: true,
      }),
    };
    const baseProjection = projectChatTimelineRow(interimMessage, {
      summaries: {},
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: [],
    });
    expect(baseProjection.surface).toBe('transcript');
    if (baseProjection.surface === 'transcript') {
      expect(baseProjection.transcript.executionProgress).not.toBeNull();
    }

    const finalizedProjection = projectChatTimelineRow(interimMessage, {
      summaries: {},
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: [],
      finalizedTurnIds: new Set(['turn-1']),
    });
    expect(finalizedProjection.surface).toBe('transcript');
    if (finalizedProjection.surface === 'transcript') {
      expect(finalizedProjection.transcript.showExecutionBubbleFooter).toBe(true);
      expect(finalizedProjection.transcript.executionProgress).toBeNull();
    }
  });

  it('builds a reply preview from a persisted timeline message', () => {
    expect(buildReplyPreviewFromMessage({
      id: 'msg-reply',
      role: 'assistant',
      kind: 'assistant',
      content: 'Root assistant answer',
      timestamp: 1000,
      messageId: 'msg-assistant-root',
      messageKind: 'assistant_final',
    })).toEqual({
      messageId: 'msg-assistant-root',
      role: 'assistant',
      messageKind: 'assistant_final',
      contentExcerpt: 'Root assistant answer',
    });
  });

  it('projects execution action state for running, cancelling, and detaching turns', () => {
    const runningMessage: ChatTimelineMessage = {
      id: 'msg-running',
      role: 'assistant',
      kind: 'assistant',
      content: 'Running tools',
      timestamp: 1000,
      turnId: 'turn-running',
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn-running',
        mode: 'orchestration',
        status: 'running',
        headline: 'Running tools',
        active_steps: 2,
        completed_steps: 1,
        failed_steps: 0,
        duration_seconds: 1.2,
        trace_available: true,
      }),
    };

    expect(getExecutionActionState(runningMessage, {
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: [],
    })).toMatchObject({
      turnId: 'turn-running',
      executionState: 'running',
      isCancelling: false,
      isDetaching: false,
      showCancelButton: true,
      showDetachButton: true,
    });

    expect(getExecutionActionState(runningMessage, {
      executionControlByTurnId: {
        'turn-running': {
          state: 'cancelling',
          label: 'Cancelling run',
        },
      },
      cancellingTurnIds: ['turn-running'],
      detachingTurnIds: [],
    })).toMatchObject({
      turnId: 'turn-running',
      executionState: 'cancelling',
      isCancelling: true,
      isDetaching: false,
      showCancelButton: true,
      showDetachButton: false,
      executionControl: {
        state: 'cancelling',
        label: 'Cancelling run',
      },
    });

    expect(getExecutionActionState(runningMessage, {
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: ['turn-running'],
    })).toMatchObject({
      turnId: 'turn-running',
      executionState: 'detaching',
      isCancelling: false,
      isDetaching: true,
      showCancelButton: false,
      showDetachButton: false,
    });
  });

  it('uses restored backend run state to suppress execution controls', () => {
    const cancelledMessage: ChatTimelineMessage = {
      id: 'msg-cancelled',
      role: 'assistant',
      kind: 'status',
      content: 'Run cancelled',
      timestamp: 1000,
      turnId: 'turn-cancelled',
      runState: {
        state: 'cancelled',
        run_id: 'run-1',
        run_revision: 0,
        can_cancel: false,
        can_detach: false,
      },
    };

    expect(getExecutionActionState(cancelledMessage, {
      executionControlByTurnId: {
        'turn-cancelled': {
          state: 'running',
          label: 'Running tool chain',
        },
      },
      cancellingTurnIds: [],
      detachingTurnIds: [],
    })).toMatchObject({
      turnId: 'turn-cancelled',
      executionState: 'cancelled',
      isCancelling: false,
      isDetaching: false,
      showCancelButton: false,
      showDetachButton: false,
    });
  });

  it('projects execution progress descriptor including trace-entry state', () => {
    const runningMessage: ChatTimelineMessage = {
      id: 'msg-running-panel',
      role: 'assistant',
      kind: 'assistant',
      content: 'Running tools',
      timestamp: 1000,
      turnId: 'turn-running-panel',
      traceDisplayMode: 'prominent',
      traceAvailable: true,
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn-running-panel',
        mode: 'orchestration',
        status: 'running',
        headline: 'Running tools',
        active_steps: 2,
        completed_steps: 1,
        failed_steps: 0,
        duration_seconds: 1.2,
        trace_available: true,
        plan_summary: {
          planner: 'task_agent',
          parallel_mode: 'parallel',
          total_steps: 4,
          remaining_steps: 1,
          steps: [
            {
              subtask_id: 'subtask_1',
              label: 'Inspect current docs',
              status: 'completed',
            },
            {
              subtask_id: 'subtask_2',
              label: 'Map runtime structure',
              status: 'running',
            },
          ],
        },
      }),
    };

    expect(projectExecutionProgressPresentation(runningMessage, {
      executionControlByTurnId: {
        'turn-running-panel': {
          state: 'cancelling',
          label: 'Cancelling run',
        },
      },
      cancellingTurnIds: ['turn-running-panel'],
      detachingTurnIds: [],
      summary: { traceAvailable: true },
      variant: 'bubble',
    })).toMatchObject({
      turnId: 'turn-running-panel',
      executionControlLabel: 'Cancelling run',
      executionState: 'cancelling',
      isCancelling: true,
      isDetaching: false,
      showCancelButton: true,
      showDetachButton: false,
      showSubtitle: true,
      statusTitle: null,
      statusTitleKey: 'chat.trace.execution.cancellingTitle',
      subtitle: {
        key: 'chat.trace.execution.cancellingBody',
      },
      planStage: {
        key: 'chat.trace.plan.stage.cancelling',
        values: { completed: 3, total: 4 },
      },
      footer: null,
      showBubbleTitle: true,
      indicator: 'loader',
      showSpinningIndicator: true,
      traceStats: {
        activeSteps: 2,
        completedSteps: 1,
        failedSteps: 0,
      },
      planSummary: {
        parallelMode: 'parallel',
        totalSteps: 4,
        remainingSteps: 1,
        steps: [
          { key: 'subtask_1', label: 'Inspect current docs', status: 'completed' },
          { key: 'subtask_2', label: 'Map runtime structure', status: 'running' },
        ],
      },
      traceEntry: {
        turnId: 'turn-running-panel',
        canOpen: true,
        variant: 'default',
      },
    });
  });

  it('keeps plan progress independent from trace activity counts', () => {
    const message: ChatTimelineMessage = {
      id: 'msg-semantic-plan-progress',
      role: 'assistant',
      kind: 'assistant',
      content: 'Organizing files',
      timestamp: 1000,
      turnId: 'turn-semantic-plan-progress',
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn-semantic-plan-progress',
        mode: 'orchestration',
        status: 'running',
        headline: 'Organizing files',
        active_steps: 0,
        completed_steps: 900,
        failed_steps: 77,
        duration_seconds: 10,
        trace_available: true,
        plan_summary: {
          planner: 'task_agent',
          parallel_mode: 'sequential',
          total_steps: 30,
          remaining_steps: 5,
          steps: [],
        },
      }),
    };

    const presentation = projectExecutionProgressPresentation(message, {
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: [],
    });

    expect(presentation.planStage).toEqual({
      key: 'chat.trace.plan.stage.runningFallback',
      values: { completed: 25, total: 30 },
    });
  });

  it('uses interim assistant text as the running bubble label', () => {
    const interimMessage: ChatTimelineMessage = {
      id: 'msg-interim-running',
      role: 'assistant',
      kind: 'assistant',
      content: '我看一下。',
      timestamp: 1000,
      turnId: 'turn-interim-running',
      messageKind: 'assistant_interim',
      traceDisplayMode: 'prominent',
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn-interim-running',
        mode: 'orchestration',
        status: 'running',
        headline: '正在分析项目',
        active_steps: 1,
        completed_steps: 0,
        failed_steps: 0,
        duration_seconds: 0.4,
        trace_available: true,
      }),
      traceAvailable: true,
    };

    expect(projectExecutionProgressPresentation(interimMessage, {
      executionControlByTurnId: {},
      cancellingTurnIds: [],
      detachingTurnIds: [],
      summary: { traceAvailable: true },
      variant: 'bubble',
    })).toMatchObject({
      executionState: 'running',
      statusTitle: '正在分析项目',
      showBubbleTitle: false,
    });
  });

  it('projects control status card descriptors from control payloads', () => {
    expect(projectControlStatusCardPresentation({
      id: 'permission:req-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'permission_request',
      content: 'git_push',
      timestamp: 1000,
      payload: {
        permission_request_id: 'req-1',
        tool: 'git_push',
        risk_level: 'high',
        origin: 'main_loop',
        tool_args: { remote: 'origin' },
      },
    })).toMatchObject({
      kind: 'permission_request',
      requestId: 'req-1',
      tool: 'git_push',
      riskLevel: 'high',
      riskTone: 'danger',
      origin: 'main_loop',
      argsPreview: '{\n  "remote": "origin"\n}',
    });

    expect(projectControlStatusCardPresentation({
      id: 'ask:ask-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'ask_request',
      content: 'Which branch should I use?',
      timestamp: 1001,
      payload: {
        ask_request_id: 'ask-1',
        question: 'Which branch should I use?',
        options: ['main', 'develop'],
        allow_free_text: true,
        background: true,
      },
    })).toMatchObject({
      kind: 'ask_request',
      question: 'Which branch should I use?',
      options: ['main', 'develop'],
      allowFreeText: true,
      isBackground: true,
    });

    expect(projectControlStatusCardPresentation({
      id: 'plan:turn-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'plan_state',
      content: '1. Inspect\n2. Fix',
      timestamp: 1002,
      payload: {
        active: true,
        plan_text: '1. Inspect\n2. Fix',
      },
    })).toMatchObject({
      kind: 'plan_state',
      active: true,
      planText: '1. Inspect\n2. Fix',
    });

    expect(projectControlStatusCardPresentation({
      id: 'todo:turn-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'todo_state',
      content: 'Inspect runtime drift\nPatch UI',
      timestamp: 1003,
      payload: {
        items: [
          { id: 'todo-1', content: 'Inspect runtime drift', status: 'in_progress' },
          { content: 'Patch UI', status: 'done' },
          { status: 'mystery' },
        ],
      },
    })).toMatchObject({
      kind: 'todo_state',
      items: [
        { id: 'todo-1', content: 'Inspect runtime drift', status: 'in_progress' },
        { id: 'Patch UI', content: 'Patch UI', status: 'completed' },
        { id: 'todo-2', content: '', status: 'not_started' },
      ],
    });

    expect(projectControlStatusCardPresentation({
      id: 'bg:task-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'background_task_completion',
      content: 'Repo sync\nFinished successfully',
      timestamp: 1004,
      payload: {
        background_task_id: 'task-1',
        background_task_status: 'succeeded',
        background_task_title: 'Repo sync',
      },
    })).toMatchObject({
      kind: 'background_task_completion',
      taskId: 'task-1',
      status: 'succeeded',
      statusTone: 'success',
      title: 'Repo sync',
      bodyText: 'Finished successfully',
    });

    expect(projectControlStatusCardPresentation({
      id: 'bg-pending:msg-1',
      role: 'assistant',
      kind: 'status',
      messageKind: 'background_task_pending',
      content: '[Background task] /deep-scan\n(running…)',
      timestamp: 1100,
      payload: {
        background_task_id: 'task-2',
        background_task_status: 'pending',
        background_task_title: '/deep-scan',
        skill_name: 'deep-scan',
        invocation_text: '/deep-scan',
      },
    })).toMatchObject({
      kind: 'background_task_pending',
      taskId: 'task-2',
      title: '/deep-scan',
      skillName: 'deep-scan',
      invocationText: '/deep-scan',
    });
  });

  it('adds a runtime status card when trace activity begins', () => {
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
    expect(next[1].messageKind).toBeNull();
    expect(next[1].content).toBe('正在执行工具链');
    expect(next[1].traceAvailable).toBe(true);
  });

  it('removes transient trace status when the final assistant answer arrives', () => {
    const withTraceStatus = upsertTraceSummary(
      createPendingTurn('杭州天气怎么样', 'turn_weather', 1000, 'Thinking'),
      'turn_weather',
      normalizeTraceSummary({
        turn_id: 'turn_weather',
        mode: 'function_calling',
        status: 'running',
        headline: 'Running tool chain',
        active_steps: 1,
        completed_steps: 0,
        failed_steps: 0,
        duration_seconds: 0.4,
        trace_available: true,
      })
    );

    const next = applyAgentResponse(withTraceStatus, {
      content: '要继续查询天气，请先配置和风天气 API Key。',
      timestamp: 2000,
      messageId: 'msg-weather-final',
      messageKind: 'assistant_final',
      turnId: 'turn_weather',
      traceSummary: normalizeTraceSummary({
        turn_id: 'turn_weather',
        mode: 'function_calling',
        status: 'completed',
        headline: 'Tool chain completed',
        active_steps: 0,
        completed_steps: 2,
        failed_steps: 0,
        duration_seconds: 1.2,
        trace_available: true,
      }),
      traceAvailable: true,
    });

    expect(next).toHaveLength(2);
    expect(next[0].kind).toBe('user');
    expect(next[1]).toMatchObject({
      kind: 'assistant',
      messageKind: 'assistant_final',
      content: '要继续查询天气，请先配置和风天气 API Key。',
      turnId: 'turn_weather',
      traceAvailable: true,
    });
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

  it('keeps trace entry helper enabled for collapsible direct replies', () => {
    const directReply = applyAgentResponse(
      applyTurnUxPlan(
        createPendingTurn('你好', 'turn-direct', 1000, 'Thinking'),
        'turn-direct',
        {
          assistantSurfaceMode: 'final_only',
          traceDisplayMode: 'collapsible',
        }
      ),
      {
        content: '你好，我在。',
        timestamp: 2000,
        turnId: 'turn-direct',
        uxPlan: {
          assistantSurfaceMode: 'final_only',
          traceDisplayMode: 'collapsible',
        },
        traceSummary: normalizeTraceSummary({
          turn_id: 'turn-direct',
          mode: 'direct_llm',
          status: 'completed',
          headline: '直答已完成',
          active_steps: 0,
          completed_steps: 1,
          failed_steps: 0,
          duration_seconds: 0.8,
          trace_available: true,
        }),
        traceAvailable: true,
      }
    ).find((message) => message.kind === 'assistant')!;

    expect(directReply.traceDisplayMode).toBe('collapsible');
    expect(shouldShowTraceEntry(directReply)).toBe(true);
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

  it('adds an interim assistant bubble when thinking indicator asks for visible feedback', () => {
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
    expect(next[1].kind).toBe('assistant');
    expect(next[1].messageKind).toBe('assistant_interim');
    expect(next[1].content).toBe('正在思考');
  });

  it('inserts a late interim bubble after its own user turn', () => {
    const initial = [
      ...createPendingTurn('第一次架构扫描', 'turn_first', 1000, 'Thinking'),
      ...createPendingTurn('第二次架构扫描', 'turn_second', 2000, 'Thinking'),
    ];

    const next = applyTurnUxPlan(initial, 'turn_first', {
      assistantSurfaceMode: 'interim_then_final',
      interimText: '我看一下。',
    });

    expect(next.map((message) => [message.turnId, message.role, message.content])).toEqual([
      ['turn_first', 'user', '第一次架构扫描'],
      ['turn_first', 'assistant', '我看一下。'],
      ['turn_second', 'user', '第二次架构扫描'],
    ]);
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

  it('preserves durable todo state cards when the final assistant answer arrives', () => {
    const initial = [
      ...createPendingTurn('Analyze this repo', 'turn_todo', 1000, 'Thinking'),
      {
        id: 'todo:turn_todo',
        role: 'assistant' as const,
        kind: 'status' as const,
        messageKind: 'todo_state',
        content: 'Inspect runtime drift\nPatch UI',
        timestamp: 1500,
        turnId: 'turn_todo',
        payload: {
          items: [
            { id: 'todo-1', content: 'Inspect runtime drift', status: 'in_progress' },
            { id: 'todo-2', content: 'Patch UI', status: 'completed' },
          ],
        },
      },
    ];

    const next = applyAgentResponse(initial, {
      content: 'Here is the final answer.',
      timestamp: 2000,
      turnId: 'turn_todo',
    });

    expect(next).toHaveLength(3);
    expect(next[1]).toMatchObject({
      kind: 'status',
      messageKind: 'todo_state',
      turnId: 'turn_todo',
    });
    expect(next[2]).toMatchObject({
      kind: 'assistant',
      messageKind: 'assistant_final',
      turnId: 'turn_todo',
      content: 'Here is the final answer.',
    });
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

  it('preserves persona id when normalizing history messages', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'msg-persona',
        message_kind: 'assistant_final',
        persona_id: 'persona-asuka',
        role: 'assistant',
        content: 'Same thread, different persona.',
        timestamp: 1000,
        turn_id: 'turn_persona',
        kind: 'assistant',
      },
    ]);

    expect(normalized[0].personaId).toBe('persona-asuka');
  });

  it('normalizes recalled memory summary from history payloads', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'msg-memory-summary',
        message_kind: 'assistant_final',
        role: 'assistant',
        content: 'You visited it 12 times.',
        timestamp: 1000,
        turn_id: 'turn_memory_summary',
        kind: 'assistant',
        payload: {
          recalled_memory_summary: {
            coverage_kind: 'exhaustive',
            can_claim_total: true,
            total_count: 12,
            domain: 'browser',
          },
        },
      },
    ]);

    expect(normalized[0].recalledMemorySummary).toEqual({
      coverageKind: 'exhaustive',
      canClaimTotal: true,
      totalCount: 12,
      domain: 'browser',
    });
  });

  it('normalizes recalled memory summary from live assistant payloads', () => {
    const next = applyAgentResponse([], {
      content: 'You visited it 12 times.',
      timestamp: 1000,
      messageKind: 'assistant_final',
      payload: {
        recalled_memory_summary: {
          coverage_kind: 'exhaustive',
          can_claim_total: true,
          total_count: 12,
          domain: 'browser',
        },
      },
    });

    expect(next[0].recalledMemorySummary).toEqual({
      coverageKind: 'exhaustive',
      canClaimTotal: true,
      totalCount: 12,
      domain: 'browser',
    });
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

  it('preserves persisted collapsible trace preferences for direct replies', () => {
    const normalized = normalizeHistoryMessages([
      {
        message_id: 'msg-direct',
        message_kind: 'assistant_final',
        role: 'assistant',
        content: '你好，我在。',
        timestamp: 1000,
        turn_id: 'turn_direct_trace',
        kind: 'assistant',
        trace_available: true,
        trace_display_mode: 'collapsible',
        allow_trace_collapse: false,
      },
    ]);

    expect(normalized[0]).toMatchObject({
      id: 'msg-direct',
      messageId: 'msg-direct',
      traceDisplayMode: 'collapsible',
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

  it('preserves the planning node in the trace tree for drawer display', () => {
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
    expect(root.children[0].kind).toBe('planning');
    expect(root.children[0].label).toBe('任务编排');
  });

  it('synthesizes a planning node from raw dispatch rows when the backend snapshot is still unshaped', () => {
    const root = flattenPlanningNodeForDisplay({
      id: 'turn_2:root',
      kind: 'root',
      label: 'Tool chain',
      status: 'completed',
      startedAt: 10,
      endedAt: 20,
      resultPreview: '',
      error: null,
      metadata: {},
      children: [
        {
          id: 'turn_2:intent',
          kind: 'intent',
          label: 'Intent resolution',
          status: 'completed',
          startedAt: 10,
          endedAt: 11,
          resultPreview: '',
          error: null,
          metadata: {},
          children: [],
        },
        {
          id: 'turn_2:dispatch:1',
          kind: 'dispatch',
          label: 'Worker dispatch',
          status: 'completed',
          startedAt: 11,
          endedAt: 11,
          resultPreview: 'Compare Magi and Hindsight memory systems',
          error: null,
          metadata: {},
          children: [],
        },
        {
          id: 'turn_2:iteration:1',
          kind: 'iteration',
          label: 'Round 1',
          status: 'completed',
          startedAt: 12,
          endedAt: 19,
          resultPreview: '',
          error: null,
          metadata: { iteration: 1 },
          children: [],
        },
        {
          id: 'turn_2:response',
          kind: 'response',
          label: 'Response emission',
          status: 'completed',
          startedAt: 19,
          endedAt: 20,
          resultPreview: 'Final answer ready',
          error: null,
          metadata: {},
          children: [],
        },
      ],
    });

    expect(root.children).toHaveLength(3);
    expect(root.children.map((child) => child.kind)).toEqual(['intent', 'planning', 'response']);
    expect(root.children[1]).toMatchObject({
      kind: 'planning',
      label: 'Task orchestration',
      metadata: { synthetic: true, hidden_iteration_count: 1 },
    });
    expect(root.children[1].children[0]).toMatchObject({
      kind: 'dispatch',
      label: 'Compare Magi and Hindsight memory systems',
      resultPreview: '',
    });
  });
});
