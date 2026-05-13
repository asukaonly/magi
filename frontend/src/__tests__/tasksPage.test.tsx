import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TasksPage } from '@/pages/Tasks';
import { useChatShellStore } from '@/stores';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import type { BackgroundTaskDTO, ScheduleActivityDTO, ScheduleDTO } from '@/api';

const {
  backgroundTasksListMock,
  schedulesListMock,
  schedulesListActivityMock,
  schedulesRunMock,
  schedulesUpdateMock,
  schedulesRemoveMock,
} = vi.hoisted(() => ({
  backgroundTasksListMock: vi.fn(),
  schedulesListMock: vi.fn(),
  schedulesListActivityMock: vi.fn(),
  schedulesRunMock: vi.fn(),
  schedulesUpdateMock: vi.fn(),
  schedulesRemoveMock: vi.fn(),
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
    list: backgroundTasksListMock,
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
    run: schedulesRunMock,
    update: schedulesUpdateMock,
    remove: schedulesRemoveMock,
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

const LocationProbe = () => {
  const location = useLocation();
  const state = location.state as { returnTo?: string } | null;
  return (
    <div data-testid="location" data-return-to={state?.returnTo ?? ''}>
      {`${location.pathname}${location.search}`}
    </div>
  );
};

describe('TasksPage', () => {
  beforeEach(() => {
    backgroundTasksListMock.mockResolvedValue({ tasks: [], active_count: 0, total: 0 });
    schedulesListMock.mockResolvedValue({ schedules: [] });
    schedulesListActivityMock.mockResolvedValue({ activities: [] });
    schedulesRunMock.mockResolvedValue({
      schedule: makeSchedule(),
      result: { success: true, message: 'manual_run_started' },
    });
    schedulesUpdateMock.mockResolvedValue({ schedule: makeSchedule() });
    schedulesRemoveMock.mockResolvedValue(undefined);
    useBackgroundTaskStore.setState({
      tasksById: {},
      orderedIds: [],
      activeCount: 0,
      lastRefreshedAt: 0,
    });
    useChatShellStore.setState({
      activePanel: 'none',
      settingsNavigationIntent: null,
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
    backgroundTasksListMock.mockResolvedValue({ tasks: [task], active_count: 1, total: 1 });

    render(
      <MemoryRouter>
        <TasksPage />
      </MemoryRouter>,
    );

    await screen.findByText('Deep research on transformers');
  });

  it('paginates background tasks with a fixed footer control', async () => {
    const user = userEvent.setup();
    const tasks = Array.from({ length: 25 }, (_, index) => makeTask({
      task_id: `bg_${index + 1}`,
      status: 'succeeded',
      spec: {
        ...makeTask().spec,
        title: `Task ${index + 1}`,
      },
      created_at: 1000 + index,
      updated_at: 1000 + index,
    })).reverse();

    backgroundTasksListMock.mockImplementation(async ({ limit = 20, offset = 0 } = {}) => ({
      tasks: tasks.slice(offset, offset + limit),
      active_count: 0,
      total: tasks.length,
    }));

    render(
      <MemoryRouter>
        <TasksPage />
      </MemoryRouter>,
    );

    await screen.findByText('Task 25');
    expect(screen.getByText('tasks.pagination.info')).toBeInTheDocument();
    expect(screen.queryByText('Task 5')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'tasks.pagination.next' }));

    await waitFor(() => {
      expect(backgroundTasksListMock).toHaveBeenLastCalledWith({
        userId: 'local_user',
        limit: 20,
        offset: 20,
      });
    });
    expect(await screen.findByText('Task 5')).toBeInTheDocument();
    expect(screen.queryByText('Task 25')).not.toBeInTheDocument();
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
    await screen.findByRole('button', { name: 'tasks.scheduled.actions.openSettings' });
    expect(screen.queryByRole('button', { name: 'tasks.scheduled.actions.disable' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'tasks.scheduled.actions.delete' })).not.toBeInTheDocument();
    expect(screen.queryByText('tasks.scheduled.columns.type')).not.toBeInTheDocument();
    expect(screen.getByText('interval 5m')).toBeInTheDocument();
  });

  it('opens schedule settings over the tasks page', async () => {
    const user = userEvent.setup();
    schedulesListMock.mockResolvedValue({ schedules: [makeSchedule()] });
    schedulesListActivityMock.mockResolvedValue({ activities: [makeActivity()] });

    render(
      <MemoryRouter initialEntries={['/tasks?tab=scheduled']}>
        <TasksPage />
        <LocationProbe />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.openSettings' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/tasks?tab=scheduled');
    expect(useChatShellStore.getState().activePanel).toBe('settings');
    expect(useChatShellStore.getState().settingsNavigationIntent).toEqual({
      section: 'timeline',
      source: 'screen_time',
    });
  });

  it('shows prompt target details for agent-created schedules', async () => {
    const user = userEvent.setup();
    schedulesListMock.mockResolvedValue({
      schedules: [
        makeSchedule({
          schedule_id: 'agent-task:drink-water',
          target_type: 'user_agent_task',
          target_key: 'agent-task:drink-water',
          target_payload: {
            kind: 'agent_task',
            title: 'Drink water reminder',
            prompt: '提醒我及时喝水',
          },
          metadata: {
            owner_kind: 'agent_created',
            target_kind: 'agent_task',
            display_name: 'Drink water reminder',
          },
          editable: true,
          owner_kind: 'agent_created',
          settings_link: null,
        }),
      ],
    });
    schedulesListActivityMock.mockResolvedValue({ activities: [] });

    render(
      <MemoryRouter initialEntries={['/tasks?tab=scheduled']}>
        <TasksPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.edit' }));

    await screen.findByDisplayValue('提醒我及时喝水');
    expect(screen.getByDisplayValue('提醒我及时喝水')).toBeInTheDocument();
  });

  it('runs a scheduled task immediately from the scheduled tab', async () => {
    const user = userEvent.setup();
    const schedule = makeSchedule({
      schedule_id: 'agent-task:drink-water',
      target_type: 'user_agent_task',
      target_key: 'agent-task:drink-water',
      target_payload: {
        kind: 'agent_task',
        title: 'Drink water reminder',
        prompt: '提醒我及时喝水',
      },
      metadata: {
        owner_kind: 'agent_created',
        target_kind: 'agent_task',
        display_name: 'Drink water reminder',
      },
      editable: true,
      owner_kind: 'agent_created',
      settings_link: null,
    });
    schedulesListMock.mockResolvedValue({ schedules: [schedule] });
    schedulesListActivityMock.mockResolvedValue({ activities: [] });
    schedulesRunMock.mockResolvedValue({
      schedule,
      result: { success: true, message: 'agent_task_enqueued' },
    });

    render(
      <MemoryRouter initialEntries={['/tasks?tab=scheduled']}>
        <TasksPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.runNow' }));

    await waitFor(() => {
      expect(schedulesRunMock).toHaveBeenCalledWith('agent-task:drink-water');
    });
  });

  it('updates schedule enabled state from the scheduled tab', async () => {
    const user = userEvent.setup();
    const schedule = makeSchedule({
      schedule_id: 'agent-task:drink-water',
      target_type: 'user_agent_task',
      target_key: 'agent-task:drink-water',
      editable: true,
      settings_link: null,
    });
    schedulesListMock.mockResolvedValue({ schedules: [schedule] });
    schedulesListActivityMock.mockResolvedValue({ activities: [] });
    schedulesUpdateMock.mockResolvedValue({
      schedule: {
        ...schedule,
        enabled: false,
      },
    });

    render(
      <MemoryRouter initialEntries={['/tasks?tab=scheduled']}>
        <TasksPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.disable' }));

    await waitFor(() => {
      expect(schedulesUpdateMock).toHaveBeenCalledWith('agent-task:drink-water', { enabled: false });
    });
  });

  it('deletes a scheduled task from the scheduled tab', async () => {
    const user = userEvent.setup();
    const schedule = makeSchedule({
      schedule_id: 'agent-task:drink-water',
      target_type: 'user_agent_task',
      target_key: 'agent-task:drink-water',
      editable: true,
      settings_link: null,
    });
    schedulesListMock.mockResolvedValue({ schedules: [schedule] });
    schedulesListActivityMock.mockResolvedValue({ activities: [] });

    render(
      <MemoryRouter initialEntries={['/tasks?tab=scheduled']}>
        <TasksPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.delete' }));

    await waitFor(() => {
      expect(schedulesRemoveMock).toHaveBeenCalledWith('agent-task:drink-water');
    });
  });

  it('limits schedule activity to the next hour window', async () => {
    const now = Math.floor(Date.now() / 1000);
    schedulesListMock.mockResolvedValue({ schedules: [makeSchedule()] });
    schedulesListActivityMock.mockResolvedValue({
      activities: [
        makeActivity({
          activity_id: 'upcoming:soon',
          title: 'soon',
          planned_at: now + 30 * 60,
        }),
        makeActivity({
          activity_id: 'upcoming:later',
          title: 'later',
          planned_at: now + 2 * 60 * 60,
        }),
      ],
    });

    render(
      <MemoryRouter initialEntries={['/tasks?tab=scheduled']}>
        <TasksPage />
      </MemoryRouter>,
    );

    await screen.findByText('soon');

    await waitFor(() => {
      expect(screen.queryByText('later')).not.toBeInTheDocument();
    });
  });
});
