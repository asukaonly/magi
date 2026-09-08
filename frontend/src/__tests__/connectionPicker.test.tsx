import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
const { list, pair, activate } = vi.hoisted(() => ({ list: vi.fn(), pair: vi.fn(), activate: vi.fn() }));
vi.mock('@/runtime/connections', () => ({ listConnectionProfiles: list, pairCenter: pair, activateConnection: activate, forgetConnection: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
import { ConnectionPicker } from '@/components/connections/ConnectionPicker';
beforeEach(() => {
  vi.clearAllMocks(); list.mockResolvedValue({ supports_remote: true, state: { active_profile_id: null, profiles: [{ id: 'local', mode: 'local' }] } });
  activate.mockResolvedValue(undefined);
});
describe('connection selection', () => {
  it('allows local selection without requiring a remote pairing form', async () => {
    render(<ConnectionPicker />); fireEvent.click(await screen.findByText('connections.connect'));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('local'));
    expect(pair).not.toHaveBeenCalled();
  });
  it('pairs before activation and explains full owner access', async () => {
    pair.mockResolvedValue({ id: 'remote' }); render(<ConnectionPicker />);
    await screen.findByText('connections.ownerAccess');
    fireEvent.change(screen.getByLabelText('connections.name'), { target: { value: 'Home' } });
    fireEvent.change(screen.getByLabelText('connections.address'), { target: { value: 'https://center.example' } });
    fireEvent.change(screen.getByLabelText('connections.pairingCode'), { target: { value: 'one-time-code' } });
    fireEvent.click(screen.getByText('connections.pair'));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('remote'));
    expect(pair).toHaveBeenCalledWith('https://center.example', 'one-time-code', 'Home');
    expect(pair.mock.invocationCallOrder[0]).toBeLessThan(activate.mock.invocationCallOrder[0]);
  });
  it('keeps invalid pairings editable and never activates a rejected center', async () => {
    pair.mockRejectedValue(new Error('Pairing expired')); render(<ConnectionPicker />);
    await screen.findByText('connections.ownerAccess');
    fireEvent.change(screen.getByLabelText('connections.name'), { target: { value: 'Home' } });
    fireEvent.change(screen.getByLabelText('connections.address'), { target: { value: 'https://center.example' } });
    fireEvent.change(screen.getByLabelText('connections.pairingCode'), { target: { value: 'expired-code' } });
    fireEvent.click(screen.getByText('connections.pair'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Pairing expired');
    expect(activate).not.toHaveBeenCalled(); expect(screen.getByLabelText('connections.pairingCode')).not.toBeDisabled();
  });
});
