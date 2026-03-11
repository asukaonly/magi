import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { vi } from 'vitest';

import ToolchainDrawer from '@/components/chat/ToolchainDrawer';
import type { NormalizedExecutionTraceSnapshot } from '@/pages/chat-state';

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
        id: 'tool-weather',
        kind: 'tool',
        label: 'weather',
        status: 'completed',
        startedAt: 1710000005000,
        endedAt: 1710000005470,
        resultPreview: 'success',
        error: null,
        metadata: {
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
  it('constrains the detail pane inside the drawer so the right side can scroll independently', async () => {
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

    expect(await screen.findAllByText('weather')).toHaveLength(2);

    const dialog = screen.getByRole('dialog');
    expect(dialog.className).toContain('flex');
    expect(dialog.className).toContain('flex-col');
    expect(dialog.className).toContain('overflow-hidden');

    const panesGrid = Array.from(document.body.querySelectorAll('div')).find((element) =>
      element.className.includes('xl:grid-cols-[minmax(520px,0.92fr)_minmax(720px,1.08fr)]')
    );
    expect(panesGrid).toBeTruthy();
    expect(panesGrid?.className).toContain('overflow-hidden');
  });
});
