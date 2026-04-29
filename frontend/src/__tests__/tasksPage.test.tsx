import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';
import { beforeEach, describe, it, vi } from 'vitest';

import { TasksPage } from '@/pages/Tasks';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import type { BackgroundTaskDTO, ScheduleActivityDTO, ScheduleDTO } from '@/api';

const { schedulesListMock, schedulesListActivityMock } = vi.hoisted(() => ({
  schedulesListMock: vi.fn(),
  schedulesListActivityMock: vi.fn(),
}));

const tFn = (key: string, opts?: { defaultValue?: string }) =>
  opts?.defaultValue ?? key;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: tFn,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock('@/api/modules/backgroundTasks', () => ({
  backgroundTasksApi: {
    list: vi.fn().mockResolvedValue({ tasks: [], active_count: 0 }),
    get: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(),
    dismiss: vi.fn(),
  },
}));

vi.mock('@/api/modules/schedules', () => ({
  schedulesApi: {
    list: schedulesListMock,
    listActivity: schedulesListActivityMock,
    update: vi.fn(),
    cancelActivity: vi.fn(),
  },
}));

vi.mock('@/components/ui/sheet', () => ({
  Sheet: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
    open ? <div data-testid="sheet">{children}</div> : null,
  SheetContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const makeTask = (overrides: Partial<BackgroundTaskDTO> = {}): BackgroundTaskDTO => ({
  task_id: 'bg_abc',
  status: 'running',
  attempt_index: 0,
  spec: {
    user_id: 'u',
    session_id: 's',
    origin_turn_id: 't',
    title: 'Deep research on transformers',
    goal: 'g',
    selected_tools: [],
    workspace_path: null,
    trigger_source: 'rule',
    priority: 0,
    max_iterations: 10,
    timeout_seconds: null,
  },
  orchestration_id: null,
  user_task_id: null,
  summary: null,
  result_payload: {},
  error: null,
  cancel_reason: null,
  created_at: 1000,
  started_at: null,
  finished_at: null,
  updated_at: 1000,
  ...overrides,
});

const makeSchedule = (overrides: Partial<ScheduleDTO> = {}): ScheduleDTO => ({
  schedule_id: 'sensor-sync:screen-time:screen_time',
  target_type: 'sensor_sync',
  target_key: 'screen-time:screen_time',
  trigger: {
    trigger_type: 'interval',
    config: { seconds: 300 },
  },
  target_payload: { plugin_id: 'screen-time', source_type: 'screen_time' },
  enabled: true,
  metadata: { plugin_id: 'screen-time', source_type: 'screen_time' },
  job_id: 'sensor-sync:screen-time:screen_time',
  editable: false,
  owner_kind: 'sensor_settings',
  settings_link: { section: 'timeline', source_name: 'screen_time' },
  target_state: {
    target_type: 'sensor_sync',
    target_key: 'screen-time:screen_time',
    running: false,
    next_run_at: 1710000500,
  },
  ...overrides,
});

const makeActivity = (overrides: Partial<ScheduleActivityDTO> = {}): ScheduleActivityDTO => ({
  activity_id: 'upcoming:sensor-sync:screen-time:screen_time',
  schedule_id: 'sensor-sync:screen-time:screen_time',
  title: 'screen_time',
  target_type: 'sensor_sync',
  target_key: 'screen-time:screen_time',
  status: 'upcoming',
  planned_at: 1710000500,
  started_at: null,
  duration_ms: null,
  cancellable: false,
  cancel_kind: null,
  error: null,
  ...overrides,
});

describe('TasksPage', () => {
  beforeEach(() => {
    schedulesListMock.mockResolvedValue({ schedules: [] });
    schedulesListActivityMock.mockResolvedValue({ activities: [] });
    useBackgroundTaskStore.setState({
      tasksById: {},
      orderedIds: [],
      activeCount: 0,
      lastRefreshedAt: 0,
    });
  });

  it('renders the empty state when no tasks are hydrated', async () => {
    render(
      <MemoryRouter>
        <TasksPage />
      </MemoryRouter>,
    );

    await screen.findByText('tasks.empty.title');
  });

  it('renders a running task row from the store', async () => {
    const task = makeTask();
    useBackgroundTaskStore.getState().hydrate([task], 1);

    render(
      <MemoryRouter>
        <TasksPage />
      </MemoryRouter>,
    );

    await screen.findByText('Deep research on transformers');
  });

  it('renders scheduled tasks in the scheduled tab', async () => {
    schedulesListMock.mockResolvedValue({ schedules: [makeSchedule()] });
    schedulesListActivityMock.mockResolvedValue({ activities: [makeActivity()] });

    render(
      <MemoryRouter initialEntries={['/tasks?tab=scheduled']}>
        <TasksPage />
      </MemoryRouter>,
    );

    await screen.findAllByText('screen_time');
    await screen.findByText('tasks.scheduled.actions.openSettings');
  });
});
