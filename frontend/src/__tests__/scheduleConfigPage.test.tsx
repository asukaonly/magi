import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ScheduleConfigPage } from '@/pages/tasks-pages';
import { useChatShellStore } from '@/stores';
import { useSchedulesStore } from '@/stores/schedules';
import type { ScheduleDTO } from '@/api';

const {
  schedulesListMock,
  schedulesRunMock,
  schedulesUpdateMock,
  schedulesRemoveMock,
  schedulesCreateMock,
} = vi.hoisted(() => ({
  schedulesListMock: vi.fn(),
  schedulesRunMock: vi.fn(),
  schedulesUpdateMock: vi.fn(),
  schedulesRemoveMock: vi.fn(),
  schedulesCreateMock: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? k }),
}));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

vi.mock('@/api/modules/schedules', () => ({
  schedulesApi: {
    list: schedulesListMock,
    listActivity: vi.fn(),
    run: schedulesRunMock,
    update: schedulesUpdateMock,
    remove: schedulesRemoveMock,
    create: schedulesCreateMock,
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

const makeSchedule = (overrides: Partial<ScheduleDTO> = {}): ScheduleDTO => ({
  schedule_id: 'source-sync:screen-time:screen_time',
  target_type: 'source_sync',
  target_key: 'screen-time:screen_time',
  trigger: { trigger_type: 'interval', config: { seconds: 300 } },
  target_payload: { plugin_id: 'screen-time', source_type: 'screen_time' },
  enabled: true,
  metadata: { plugin_id: 'screen-time', source_type: 'screen_time' },
  job_id: 'source-sync:screen-time:screen_time',
  editable: false,
  owner_kind: 'source_settings',
  settings_link: { section: 'timeline', source_name: 'screen_time' },
  target_state: {
    target_type: 'source_sync',
    target_key: 'screen-time:screen_time',
    running: false,
    next_run_at: 1710000500,
  },
  ...overrides,
});

const makeAgentSchedule = (overrides: Partial<ScheduleDTO> = {}): ScheduleDTO => makeSchedule({
  schedule_id: 'user-1',
  target_type: 'user_agent_task',
  target_key: 'user-1',
  target_payload: { kind: 'agent_task', prompt: 'reminder', title: 'Drink water' },
  metadata: { display_name: 'Drink water', target_kind: 'agent_task' },
  editable: true,
  owner_kind: 'agent_created',
  settings_link: null,
  ...overrides,
});

describe('ScheduleConfigPage', () => {
  beforeEach(() => {
    schedulesListMock.mockReset();
    schedulesRunMock.mockReset();
    schedulesUpdateMock.mockReset();
    schedulesRemoveMock.mockReset();
    schedulesCreateMock.mockReset();
    schedulesListMock.mockResolvedValue({ schedules: [] });
    schedulesUpdateMock.mockResolvedValue({ schedule: makeSchedule() });
    schedulesRemoveMock.mockResolvedValue(undefined);
    schedulesRunMock.mockResolvedValue({ schedule: makeSchedule(), result: { success: true } });
    schedulesCreateMock.mockResolvedValue({ schedule: makeAgentSchedule() });
    useChatShellStore.setState({ activePanel: 'none', settingsNavigationIntent: null });
    useSchedulesStore.getState().reset();
  });

  it('renders source schedule with openSettings (not edit/delete)', async () => {
    schedulesListMock.mockResolvedValue({ schedules: [makeSchedule()] });
    render(<MemoryRouter><ScheduleConfigPage /></MemoryRouter>);
    await screen.findByRole('button', { name: 'tasks.scheduled.actions.openSettings' });
    expect(screen.queryByRole('button', { name: 'tasks.scheduled.actions.delete' })).not.toBeInTheDocument();
  });

  it('navigates to settings when opening source schedule settings', async () => {
    const user = userEvent.setup();
    schedulesListMock.mockResolvedValue({ schedules: [makeSchedule()] });
    render(<MemoryRouter><ScheduleConfigPage /></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.openSettings' }));
    expect(useChatShellStore.getState().activePanel).toBe('settings');
    expect(useChatShellStore.getState().settingsNavigationIntent).toEqual({
      section: 'timeline',
      source: 'screen_time',
    });
  });

  it('runs schedule via schedulesApi.run', async () => {
    const user = userEvent.setup();
    schedulesListMock.mockResolvedValue({ schedules: [makeAgentSchedule()] });
    render(<MemoryRouter><ScheduleConfigPage /></MemoryRouter>);
    // ▶ icon button now opens a popover with [立即运行, 带参运行…] options;
    // a direct click no longer fires the run. Step through both clicks.
    // The trigger button's aria-label uses defaultValue ('运行') so the
    // test i18n mock (which returns defaultValue ?? key) resolves to '运行'.
    await user.click(await screen.findByRole('button', { name: '运行' }));
    await user.click(await screen.findByText('tasks.scheduled.actions.runNow'));
    await waitFor(() => {
      // No params provided through the menu path → second arg is undefined.
      expect(schedulesRunMock).toHaveBeenCalledWith('user-1', undefined);
    });
  });

  it('disables schedule via schedulesApi.update', async () => {
    const user = userEvent.setup();
    schedulesListMock.mockResolvedValue({ schedules: [makeAgentSchedule()] });
    render(<MemoryRouter><ScheduleConfigPage /></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.more' }));
    await user.click(await screen.findByRole('menuitem', { name: 'tasks.scheduled.actions.disable' }));
    await waitFor(() => {
      expect(schedulesUpdateMock).toHaveBeenCalledWith('user-1', { enabled: false });
    });
  });

  it('deletes schedule via schedulesApi.remove', async () => {
    const user = userEvent.setup();
    schedulesListMock.mockResolvedValue({ schedules: [makeAgentSchedule()] });
    render(<MemoryRouter><ScheduleConfigPage /></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: 'tasks.scheduled.actions.more' }));
    await user.click(await screen.findByRole('menuitem', { name: 'tasks.scheduled.actions.delete' }));
    await waitFor(() => {
      expect(schedulesRemoveMock).toHaveBeenCalledWith('user-1');
    });
  });

  it('show-disabled toggle re-fetches with enabledOnly=false', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ScheduleConfigPage /></MemoryRouter>);
    await waitFor(() => {
      expect(schedulesListMock).toHaveBeenLastCalledWith({ enabledOnly: true });
    });
    await user.click(screen.getByLabelText('tasks.scheduled.filters.showDisabled'));
    await waitFor(() => {
      expect(schedulesListMock).toHaveBeenLastCalledWith({ enabledOnly: false });
    });
  });

  it('user category empty CTA renders when filter active and no schedules', async () => {
    const user = userEvent.setup();
    schedulesListMock.mockResolvedValue({ schedules: [makeSchedule()] }); // only source
    render(<MemoryRouter><ScheduleConfigPage /></MemoryRouter>);
    await user.click(await screen.findByRole('tab', { name: /tasks.scheduled.categories.user/ }));
    await screen.findByText('tasks.scheduled.empty.userCtaTitle');
  });
});
