import { beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
const { queue, repair, forget, activate } = vi.hoisted(() => ({ queue: vi.fn(), repair: vi.fn(), forget: vi.fn(), activate: vi.fn() }));
vi.mock('@/runtime/connections', () => ({ readConnectionQueue: queue, repairConnection: repair, forgetConnection: forget, activateConnection: activate }));
vi.mock('react-i18next', () => {
  const t = (key: string, args?: { count?: number }) => args?.count === undefined ? key : `${key}: ${args.count}`;
  return { useTranslation: () => ({ t }) };
});
import { ConnectionRepairDialog } from '@/components/connections/ConnectionRepairDialog';
const profile = { id: 'saved-profile', mode: 'remote' as const, name: 'Home', api_base_url: 'https://old.example/api', server_id: 'server', client_id: 'device' };
beforeEach(() => { vi.clearAllMocks(); queue.mockResolvedValue({ pending: 3, failed: 1 }); repair.mockResolvedValue(profile); forget.mockResolvedValue(undefined); activate.mockResolvedValue(undefined); });
const renderDialog = (action: 'repair' | 'forget' = 'repair') => render(<ConnectionRepairDialog profile={profile} action={action} hasUnsavedSettings={false} onClose={vi.fn()} onSaved={vi.fn()} />);

it('repairs the existing address without discarding its queued data', async () => {
  renderDialog();
  await screen.findByText('connections.repair.queued: 4');
  fireEvent.change(screen.getByLabelText('connections.address'), { target: { value: 'https://new.example' } });
  fireEvent.click(screen.getByText('connections.repair.save'));
  await waitFor(() => expect(repair).toHaveBeenCalledWith({ profileId: 'saved-profile', address: 'https://new.example', name: 'Home', pairingToken: null, deviceName: '', discardPending: false }));
  expect(forget).not.toHaveBeenCalled();
  await waitFor(() => expect(activate).toHaveBeenCalledWith('saved-profile'));
});

it('requires explicit queue discard before replacing authorization', async () => {
  renderDialog();
  await screen.findByText('connections.repair.queued: 4');
  fireEvent.change(screen.getByLabelText('connections.repair.code'), { target: { value: 'new-code' } });
  fireEvent.change(screen.getByLabelText('connections.deviceName'), { target: { value: 'Laptop' } });
  expect(screen.getByText('connections.repair.save')).toBeDisabled();
  expect(repair).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByText('connections.repair.save'));
  await waitFor(() => expect(repair).toHaveBeenCalledWith(expect.objectContaining({ profileId: 'saved-profile', pairingToken: 'new-code', discardPending: true })));
});

it('shows pending records and requires consent before forgetting', async () => {
  renderDialog('forget');
  await screen.findByText('connections.repair.queued: 4');
  expect(screen.getByText('connections.repair.forgetConfirm')).toBeDisabled();
  expect(forget).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByText('connections.repair.forgetConfirm'));
  await waitFor(() => expect(forget).toHaveBeenCalledWith('saved-profile', true));
});

it('keeps the form and saved queue intact when identity verification fails', async () => {
  repair.mockRejectedValue('repair_center_changed');
  renderDialog();
  await screen.findByText('connections.repair.queued: 4');
  fireEvent.click(screen.getByText('connections.repair.save'));
  expect(await screen.findByRole('alert')).toHaveTextContent('connections.repair.centerChanged');
  expect(activate).not.toHaveBeenCalled();
  expect(forget).not.toHaveBeenCalled();
});

it('does not activate a repair that finishes after the dialog unmounts', async () => {
  let finish!: () => void;
  repair.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  const view = renderDialog();
  await screen.findByText('connections.repair.queued: 4');
  fireEvent.click(screen.getByText('connections.repair.save'));
  expect(repair).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => finish());
  expect(activate).not.toHaveBeenCalled();
});
