import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { APP_EVENTS } from '@/constants/events';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { BackgroundTasksPage } from '@/pages/tasks-pages/BackgroundTasksPage';

const mocks = vi.hoisted(() => ({ list: vi.fn(), t: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('@/api', () => ({ backgroundTasksApi: { list: mocks.list } }));
vi.mock('@/pages/tasks-pages/TasksPageFrame', () => ({ TasksPageFrame: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock('@/pages/tasks-pages/components/BackgroundTaskDetailDrawer', () => ({ BackgroundTaskDetailDrawer: () => null }));
vi.mock('@/pages/tasks-pages/components/BackgroundTaskRow', () => ({ BackgroundTaskRow: () => null }));
vi.mock('@/pages/tasks-pages/components/TasksPaginationBar', () => ({
  TasksPaginationBar: ({ total, onPageChange }: { total: number; onPageChange: (offset: number) => void }) => <div>
    <span data-testid="total">{total}</span>
    <button onClick={() => onPageChange(20)}>Next</button>
    <button onClick={() => onPageChange(0)}>First</button>
  </div>,
}));
const snapshot = (total: number) => ({ tasks: [], active_count: 0, total });
beforeEach(() => { mocks.list.mockReset(); useBackgroundTaskStore.getState().reset(); });

it('rejects a late page response after moving away and back to that page', async () => {
  let resolveFirst!: (value: ReturnType<typeof snapshot>) => void;
  mocks.list.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
    .mockResolvedValueOnce(snapshot(42)).mockResolvedValue(snapshot(77));
  render(<MemoryRouter><BackgroundTasksPage /></MemoryRouter>);
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(1));
  act(() => screen.getByText('Next').click());
  await waitFor(() => expect(screen.getByTestId('total')).toHaveTextContent('42'));
  act(() => screen.getByText('First').click());
  await waitFor(() => expect(screen.getByTestId('total')).toHaveTextContent('77'));
  await act(async () => resolveFirst(snapshot(999)));
  expect(screen.getByTestId('total')).toHaveTextContent('77');
});

it('reconciles the current page after a center hint and retains it on read failure', async () => {
  mocks.list.mockResolvedValue(snapshot(42));
  render(<MemoryRouter><BackgroundTasksPage /></MemoryRouter>);
  await waitFor(() => expect(screen.getByTestId('total')).toHaveTextContent('42'));
  act(() => screen.getByText('Next').click());
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  mocks.list.mockResolvedValue(snapshot(57));
  act(() => window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED)));
  await waitFor(() => expect(screen.getByTestId('total')).toHaveTextContent('57'), { timeout: 3000 });
  expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 }));
  mocks.list.mockRejectedValue(new Error('Disconnected'));
  act(() => window.dispatchEvent(new Event('focus')));
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(4), { timeout: 3000 });
  expect(screen.getByTestId('total')).toHaveTextContent('57');
});
