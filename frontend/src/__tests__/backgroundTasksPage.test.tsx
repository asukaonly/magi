import { useEffect } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import eventExamples from '../../../contracts/api/frontend-events-examples.json';
import { BackgroundTasksPage } from '@/pages/tasks-pages/BackgroundTasksPage';
import { useBackgroundTaskStore } from '@/stores/background-tasks';

const mocks = vi.hoisted(() => ({ list: vi.fn(), refresh: new Set<() => Promise<unknown> | void>(), t: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('@/api/modules/backgroundTasks', () => ({ backgroundTasksApi: { list: mocks.list } }));
vi.mock('@/pages/tasks-pages/components/BackgroundTaskDetailDrawer', () => ({ BackgroundTaskDetailDrawer: () => null }));
vi.mock('@/hooks/useCenterRefresh', () => ({ useCenterRefresh: (read: () => Promise<unknown> | void) => {
  useEffect(() => { mocks.refresh.add(read); return () => { mocks.refresh.delete(read); }; }, [read]);
} }));
const refresh = () => act(async () => { await Promise.all([...mocks.refresh].map(read => read())); });
const snapshot = {
  tasks: [{ ...eventExamples.task, status: 'running', spec: { ...eventExamples.task.spec, title: 'Existing task' } }],
  total: 1, active_count: 1,
};

describe('BackgroundTasksPage read failures', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.refresh.clear();
    useBackgroundTaskStore.getState().reset();
    mocks.list.mockResolvedValue(snapshot);
  });

  it('does not mistake a failed read for an empty list and supports retry', async () => {
    mocks.list.mockRejectedValueOnce(new TypeError('Offline'));
    render(<MemoryRouter><BackgroundTasksPage /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('tasks.feedback.loadFailed');
    expect(screen.queryByText('tasks.empty.title')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    await screen.findByText('Existing task');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps the last snapshot on background failure and clears the error after automatic recovery', async () => {
    render(<MemoryRouter><BackgroundTasksPage /></MemoryRouter>);
    await screen.findByText('Existing task');
    mocks.list.mockRejectedValueOnce(new TypeError('Offline'));
    await refresh();
    expect(screen.getByRole('alert')).toHaveTextContent('tasks.feedback.loadFailed');
    expect(screen.getByText('Existing task')).toBeInTheDocument();
    await refresh();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Existing task')).toBeInTheDocument();
  });

  it('ignores a late failure after a newer successful snapshot', async () => {
    let rejectRead: (error: Error) => void = () => {};
    mocks.list.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRead = reject; }));
    render(<MemoryRouter><BackgroundTasksPage /></MemoryRouter>);
    await waitFor(() => expect(mocks.list).toHaveBeenCalledOnce());
    await refresh();
    expect(screen.getByText('Existing task')).toBeInTheDocument();
    await act(async () => { rejectRead(new TypeError('Offline')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
