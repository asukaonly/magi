import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const { createMock, updateMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  updateMock: vi.fn(),
}));

vi.mock('@/api', async () => {
  const actual = await vi.importActual<typeof import('@/api')>('@/api');
  return {
    ...actual,
    schedulesApi: {
      ...actual.schedulesApi,
      create: createMock,
      update: updateMock,
    },
  };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? k }),
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { ScheduleEditDrawer } from '@/pages/tasks-pages/components/ScheduleEditDrawer';

describe('ScheduleEditDrawer create mode', () => {
  beforeEach(() => {
    createMock.mockReset();
    updateMock.mockReset();
    createMock.mockResolvedValue({ schedule: {} });
  });

  it('reuses the create identifier after a lost response', async () => {
    createMock.mockRejectedValueOnce(new Error('Disconnected')).mockResolvedValueOnce({ schedule: {} });
    render(<ScheduleEditDrawer mode="create" schedule={null} onClose={vi.fn()} onSaved={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('tasks.scheduled.fields.promptText'), 'Only one reminder');
    await userEvent.click(screen.getByRole('button', { name: 'tasks.scheduled.actions.save' }));
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole('button', { name: 'tasks.scheduled.actions.save' }));
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(2));
    expect(createMock.mock.calls[0][0]).toEqual(createMock.mock.calls[1][0]);
  });

  it('keeps an obsolete edit open until the user explicitly reloads', async () => {
    const schedule = { schedule_id: 'shared', revision: 1, target_type: 'user_agent_task', target_key: 'shared', trigger: { trigger_type: 'interval' as const, config: { seconds: 60 } }, target_payload: { kind: 'agent_task', prompt: 'Original' }, metadata: {}, enabled: true };
    updateMock.mockRejectedValueOnce({ status: 409 });
    const onClose = vi.fn();
    const onReload = vi.fn().mockResolvedValue(undefined);
    const view = render(<ScheduleEditDrawer schedule={schedule} onClose={onClose} onSaved={vi.fn()} onReload={onReload} />);
    const input = screen.getByLabelText('tasks.scheduled.fields.promptText');
    await userEvent.clear(input);
    await userEvent.type(input, 'My draft');
    await userEvent.click(screen.getByRole('button', { name: 'tasks.scheduled.actions.save' }));
    await screen.findByRole('alert');
    expect(input).toHaveValue('My draft');
    expect(onClose).not.toHaveBeenCalled();
    expect(updateMock).toHaveBeenCalledWith('shared', expect.objectContaining({ revision: 1 }));
    expect(screen.getByRole('button', { name: 'tasks.scheduled.actions.save' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'tasks.scheduled.actions.reloadCenter' }));
    await waitFor(() => expect(onReload).toHaveBeenCalledOnce());
    view.rerender(<ScheduleEditDrawer schedule={{ ...schedule, revision: 2 }} onClose={onClose} onSaved={vi.fn()} onReload={onReload} />);
    expect(input).toHaveValue('Original');
    expect(updateMock).toHaveBeenCalledTimes(1);
  });

  it('renders displayName + prompt input and submits via schedulesApi.create', async () => {
    const onClose = vi.fn();
    const onSaved = vi.fn();

    render(
      <ScheduleEditDrawer
        mode="create"
        schedule={null}
        onClose={onClose}
        onSaved={onSaved}
      />,
    );

    const nameInput = screen.getByLabelText('tasks.scheduled.fields.displayName');
    await userEvent.type(nameInput, 'Daily Summary');

    const promptInput = screen.getByLabelText('tasks.scheduled.fields.promptText');
    await userEvent.type(promptInput, 'Summarize today');

    await userEvent.click(screen.getByRole('button', { name: 'tasks.scheduled.actions.save' }));

    expect(createMock).toHaveBeenCalledTimes(1);
    const body = createMock.mock.calls[0][0];
    expect(body).toMatchObject({
      display_name: 'Daily Summary',
      prompt: 'Summarize today',
      trigger: expect.objectContaining({ trigger_type: 'interval' }),
      enabled: true,
    });
    expect(typeof body.schedule_id).toBe('string');
    expect(body.schedule_id.startsWith('user-')).toBe(true);
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
