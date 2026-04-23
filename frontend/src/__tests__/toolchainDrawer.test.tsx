import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { vi } from 'vitest';

import ToolchainDrawer from '@/components/chat/ToolchainDrawer';
import type { NormalizedExecutionTraceSnapshot } from '@/domain/chat/state';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

const SNAPSHOT: NormalizedExecutionTraceSnapshot = {
  turnId: 'turn-1',
  userId: 'user-1',
  sessionId: 'session-1',
  status: 'completed',
  mode: 'function_calling',
  orchestrationId: null,
  startedAt: 1710000000000,
  endedAt: 1710000019000,
  continuedFromTurnId: 'turn-0',
  continuedFromTraceId: 'trace:turn-0',
  supersededByTurnId: null,
  supersessionReason: null,
  summary: {
    turnId: 'turn-1',
    mode: 'function_calling',
    status: 'completed',
    headline: '工具链已完成',
    activeSteps: 0,
    completedSteps: 1,
    failedSteps: 0,
    durationSeconds: 19.2,
    traceAvailable: true,
    orchestrationId: null,
    continuedFromTurnId: 'turn-0',
    continuedFromTraceId: 'trace:turn-0',
    supersededByTurnId: null,
    supersessionReason: null,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    totalReasoningTokens: 0,
  },
  root: {
    id: 'root',
    kind: 'root',
    label: 'root',
    status: 'completed',
    startedAt: 1710000000000,
    endedAt: 1710000019000,
    resultPreview: '',
    error: null,
    metadata: {},
    children: [
      {
        id: 'intent-1',
        kind: 'intent',
        label: 'Intent resolution',
        status: 'completed',
        startedAt: 1710000001000,
        endedAt: 1710000002000,
        resultPreview: 'trace_implementation',
        error: null,
        metadata: {
          intent_label: 'code_execution',
          execution_mode: 'function_calling',
          route_reason: 'Need to inspect code and reorder tools for efficient discovery.',
          task_hint: {
            task_intent: 'trace_implementation',
            domain: 'codebase',
            operation: 'discover',
          },
          router_tools: ['file_read', 'grep', 'glob'],
          selected_tools: ['glob', 'grep', 'file_read'],
          recommended_tools: [
            {
              tool: 'glob',
              priority: 1,
              reason: 'Use first to locate candidate files or folders from path or module clues.',
              domains: ['codebase'],
              operations: ['discover'],
            },
            {
              tool: 'grep',
              priority: 2,
              reason: 'Use after narrowing scope to find symbols and strings before confirming them.',
              domains: ['codebase'],
              operations: ['narrow'],
            },
          ],
        },
        children: [],
      },
      {
        id: 'tool-weather',
        kind: 'tool',
        label: 'weather',
        status: 'completed',
        startedAt: 1710000005000,
        endedAt: 1710000005470,
        resultPreview: 'success',
        error: null,
        metadata: {
          provider: 'glm',
          model: 'glm-5',
          input_tokens: 2125,
          output_tokens: 22,
          reasoning_tokens: 0,
          thinking_enabled: false,
          execution_time: 0.47,
          location: '杭州',
          payload: Array.from({ length: 40 }, (_, index) => `line-${index}`),
        },
        children: [],
      },
    ],
  },
};

describe('toolchain drawer', () => {
  it('renders as a right-side drawer with compact trace navigation', async () => {
    render(
      <ToolchainDrawer
        open
        onOpenChange={() => {}}
        loading={false}
        snapshot={SNAPSHOT}
        title="工具链"
        subtitle="查看本轮回答的执行顺序、并行分支和步骤结果。"
      />
    );

    expect(await screen.findAllByText('weather')).toHaveLength(1);

    const dialog = screen.getByRole('dialog');
    expect(dialog.className).toContain('flex');
    expect(dialog.className).toContain('flex-col');
    expect(dialog.className).toContain('overflow-hidden');
    expect(dialog.className).not.toContain('w-full');
    expect(dialog.className).toContain('max-w-[1180px]');
    expect(dialog.className).toContain('trace-theme-surface');

    const panesGrid = Array.from(document.body.querySelectorAll('div')).find((element) =>
      element.className.includes('xl:grid-cols-[minmax(320px,0.74fr)_minmax(0,1.26fr)]')
    );
    expect(panesGrid).toBeTruthy();
    expect(panesGrid?.className).toContain('overflow-hidden');

    const timestampValues = screen.getAllByText(/\d{2}:\d{2}:\d{2}\.\d{3}/);
    expect(timestampValues.length).toBeGreaterThanOrEqual(2);
    // Tool-kind nodes no longer show model/provider in dedicated blocks;
    // those are available inside the collapsed raw metadata section.
    expect(screen.getByText('chat.trace.continuedFromTurn')).toBeInTheDocument();
    expect(screen.getByText('turn-0')).toBeInTheDocument();
    expect(screen.queryByText('Execution Timeline')).not.toBeInTheDocument();
    expect(screen.queryByText('1 steps')).not.toBeInTheDocument();
  });

  it('renders structured task intent and tool ranking details for intent nodes', async () => {
    render(
      <ToolchainDrawer
        open
        onOpenChange={() => {}}
        loading={false}
        snapshot={SNAPSHOT}
        title="工具链"
        subtitle="查看本轮回答的执行顺序、并行分支和步骤结果。"
      />
    );

    expect(await screen.findByText('chat.trace.taskIntent')).toBeInTheDocument();
    expect(screen.getAllByText('trace_implementation').length).toBeGreaterThan(0);
    expect(screen.getByText('chat.trace.routerTools')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.selectedTools')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.recommendedTools')).toBeInTheDocument();
    expect(screen.getAllByText('codebase').length).toBeGreaterThan(0);
    expect(screen.getAllByText('discover').length).toBeGreaterThan(0);
    expect(screen.getAllByText('glob').length).toBeGreaterThan(0);
    expect(screen.getByText('Use first to locate candidate files or folders from path or module clues.')).toBeInTheDocument();
  });
});
