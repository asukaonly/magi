import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const { get, set, t } = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn(), t: (key: string) => key }));
vi.mock('@/api/modules/server', () => ({ serverApi: { notificationPolicy: get, setNotificationPolicy: set } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }));
import { CenterNotificationPolicy } from '@/components/connections/CenterNotificationPolicy';
beforeEach(() => { vi.clearAllMocks(); get.mockResolvedValue({ mode: 'single_device' }); });
it('saves the center policy and retains the actual saved value on failure', async () => {
  render(<CenterNotificationPolicy />);
  const select = await screen.findByRole('combobox');
  set.mockRejectedValueOnce(new Error('Offline'));
  fireEvent.change(select, { target: { value: 'all_devices' } });
  expect(await screen.findByRole('alert')).toHaveTextContent('connections.notifications.saveFailed');
  expect(select).toHaveValue('single_device');
  set.mockResolvedValueOnce({ mode: 'all_devices' });
  fireEvent.change(select, { target: { value: 'all_devices' } });
  await waitFor(() => expect(select).toHaveValue('all_devices'));
});
