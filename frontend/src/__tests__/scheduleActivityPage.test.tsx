import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ScheduleActivityPage } from '@/pages/tasks-pages';
import type { ScheduleActivityDTO } from '@/api';

const {
  schedulesListMock,
  schedulesListActivityMock,
} = vi.hoisted(() => ({
  schedulesListMock: vi.fn(),
  schedulesListActivityMock: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? k }),
}));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

vi.mock('@/api/modules/schedules', () => ({
  schedulesApi: {
    list: schedulesListMock,
    listActivity: schedulesListActivityMock,
    run: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    create: vi.fn(),
    cancelActivity: vi.fn(),
  },
}));

const makeActivity = (overrides: Partial<ScheduleActivityDTO> = {}): ScheduleActivityDTO => ({
  activity_id: 'execution:1',
  schedule_id: 'sched-1',
  title: 'Test activity',
  target_type: 'user_agent_task',
  target_key: 'sched-1',
  status: 'succeeded',
  planned_at: 1710000000,
  started_at: 1710000000,
  finished_at: 1710000005,
  duration_ms: 5000,
  cancellable: false,
  cancel_kind: null,
  error: null,
  background_task_id: null,
  ...overrides,
});

describe('ScheduleActivityPage', () => {
  beforeEach(() => {
    schedulesListMock.mockReset();
    schedulesListActivityMock.mockReset();
    schedulesListMock.mockResolvedValue({ schedules: [] });
    schedulesListActivityMock.mockResolvedValue({ activities: [makeActivity()] });
  });

  it('renders activity rows from the API and calls listActivity with sinceSeconds', async () => {
    render(<MemoryRouter><ScheduleActivityPage /></MemoryRouter>);
    await screen.findByText('Test activity');
    await waitFor(() => {
      expect(schedulesListActivityMock).toHaveBeenCalled();
    });
    const call = schedulesListActivityMock.mock.calls[0];
    expect(call?.[0]).toEqual(expect.objectContaining({
      sinceSeconds: expect.any(Number),
      limit: 100,
    }));
  });

  it('shows empty state message when activities is []', async () => {
    schedulesListActivityMock.mockResolvedValue({ activities: [] });
    render(<MemoryRouter><ScheduleActivityPage /></MemoryRouter>);
    await screen.findByText('tasks.scheduled.empty.activity');
  });
});
