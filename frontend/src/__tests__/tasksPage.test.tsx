import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TasksPage } from '@/pages/Tasks';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import type { BackgroundTaskDTO } from '@/api';

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

describe('TasksPage', () => {
  beforeEach(() => {
    useBackgroundTaskStore.setState({
      tasksById: {},
      orderedIds: [],
      activeCount: 0,
      lastRefreshedAt: null,
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
});
