import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { memoryApi, type MemoryMaintenanceTask } from '@/api/modules/memory';
import { TaskMaintenancePanel } from '@/pages/memory-pages/governance/GovernanceMaintenancePanels';

vi.mock('@/api/modules/memory', () => ({ memoryApi: { getMaintenanceTasks: vi.fn() } }));
const label = (_key: string, fallback: string, values?: Record<string, unknown>) => (
  fallback.replace(/\{\{(\w+)\}\}/g, (_, key) => String(values?.[key] ?? ''))
);
const tasks: MemoryMaintenanceTask[] = [
  { id: 'events', status: 'disabled', schedule_count: 1, enabled_count: 0, last_run_at: null, last_result: null },
  { id: 'structure', status: 'paused', schedule_count: 3, enabled_count: 0, last_run_at: null, last_result: null },
  { id: 'chapter', status: 'unavailable', schedule_count: 1, enabled_count: 0, last_run_at: null, last_result: null },
  { id: 'summary', status: 'partial', schedule_count: 5, enabled_count: 2, last_run_at: 1_700_000_000, last_result: 'failed' },
  { id: 'skills', status: 'enabled', schedule_count: 1, enabled_count: 1, last_run_at: null, last_result: null },
];
const mount = () => render(<MemoryRouter><TaskMaintenancePanel label={label} /></MemoryRouter>);

describe('memory maintenance status', () => {
  beforeEach(() => vi.mocked(memoryApi.getMaintenanceTasks).mockReset());
  afterEach(() => vi.useRealTimers());

  it('renders real availability and last execution separately', async () => {
    vi.mocked(memoryApi.getMaintenanceTasks).mockResolvedValue({ tasks });
    mount();
    await screen.findByText('已停用');
    expect(within(screen.getByRole('group', { name: '结构维护' })).getByText('已暂停')).toBeInTheDocument();
    expect(screen.getByText('不可用')).toBeInTheDocument();
    const summaries = within(screen.getByRole('group', { name: '总结维护' }));
    expect(summaries.getByText('部分可用')).toBeInTheDocument();
    expect(summaries.getByText('最近执行失败')).toBeInTheDocument();
    expect(screen.getAllByText('已启用')).toHaveLength(1);
  });

  it('shows unknown on failure and retries without retaining green status', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.getMaintenanceTasks)
      .mockResolvedValueOnce({ tasks })
      .mockRejectedValueOnce(new Error('Unavailable'))
      .mockResolvedValueOnce({ tasks });
    mount();
    await screen.findByText('已启用');
    await user.click(screen.getByRole('button', { name: '刷新状态' }));
    await screen.findByRole('alert');
    expect(screen.queryByText('已启用')).not.toBeInTheDocument();
    expect(screen.getAllByText('状态未知').length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: '刷新状态' }));
    await screen.findByText('已启用');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not assume enabled while loading or when a category is absent', async () => {
    let resolve!: (value: { tasks: MemoryMaintenanceTask[] }) => void;
    vi.mocked(memoryApi.getMaintenanceTasks).mockReturnValue(new Promise((done) => { resolve = done; }));
    mount();
    expect(screen.queryByText('已启用')).not.toBeInTheDocument();
    await act(async () => resolve({ tasks: [] }));
    await waitFor(() => expect(screen.queryByText('正在读取')).not.toBeInTheDocument());
    expect(screen.getAllByText('状态未知').length).toBeGreaterThan(0);
  });

  it('refreshes while mounted and stops polling after unmount', async () => {
    vi.useFakeTimers();
    vi.mocked(memoryApi.getMaintenanceTasks).mockResolvedValue({ tasks });
    const view = mount();
    await act(async () => {});
    expect(memoryApi.getMaintenanceTasks).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(memoryApi.getMaintenanceTasks).toHaveBeenCalledTimes(2);
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(memoryApi.getMaintenanceTasks).toHaveBeenCalledTimes(2);
  });
});
