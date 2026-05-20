import React from 'react';
import { render, screen } from '@testing-library/react';
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
