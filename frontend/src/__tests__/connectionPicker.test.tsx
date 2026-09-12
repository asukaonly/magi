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
  it('explains missing local credentials instead of showing a native error code', async () => {
    activate.mockRejectedValue('local_credential_missing');
    render(<ConnectionPicker />);
    fireEvent.click(await screen.findByText('connections.connect'));
    fireEvent.click(screen.getByText('connections.confirmSwitch'));
    expect(await screen.findByRole('alert')).toHaveTextContent('connections.errors.localCredentialMissing');
    expect(screen.queryByText('local_credential_missing')).not.toBeInTheDocument();
  });
  it('confirms before selecting a local connection', async () => {
    render(<ConnectionPicker />);
    fireEvent.click(await screen.findByText('connections.connect'));
    expect(activate).not.toHaveBeenCalled();
    expect(screen.getByText('connections.confirmSwitchTitle')).toBeInTheDocument();
    fireEvent.click(screen.getByText('connections.confirmSwitch'));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('local'));
    expect(pair).not.toHaveBeenCalled();
  });
  it.each(['https://center.example', 'http://127.0.0.1:19080'])('pairs %s before activation', async (address) => {
    pair.mockResolvedValue({ id: 'remote' }); render(<ConnectionPicker />);
    await screen.findByText('connections.ownerAccess');
    fireEvent.change(screen.getByLabelText('connections.name'), { target: { value: 'Home' } });
    fireEvent.change(screen.getByLabelText('connections.deviceName'), { target: { value: 'Work laptop' } });
    expect(screen.getByLabelText('connections.address')).toHaveAccessibleDescription('connections.addressHint');
    fireEvent.change(screen.getByLabelText('connections.address'), { target: { value: address } });
    fireEvent.change(screen.getByLabelText('connections.pairingCode'), { target: { value: 'one-time-code' } });
    fireEvent.click(screen.getByText('connections.pair'));
    expect(pair).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('connections.confirmPair'));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('remote'));
    expect(pair).toHaveBeenCalledWith(address, 'one-time-code', 'Home', 'Work laptop');
    expect(pair.mock.invocationCallOrder[0]).toBeLessThan(activate.mock.invocationCallOrder[0]);
  });
  it('keeps invalid pairings editable and never activates a rejected center', async () => {
    pair.mockRejectedValue(new Error('Pairing expired')); render(<ConnectionPicker />);
    await screen.findByText('connections.ownerAccess');
    fireEvent.change(screen.getByLabelText('connections.name'), { target: { value: 'Home' } });
    fireEvent.change(screen.getByLabelText('connections.deviceName'), { target: { value: 'Work laptop' } });
    fireEvent.change(screen.getByLabelText('connections.address'), { target: { value: 'https://center.example' } });
    fireEvent.change(screen.getByLabelText('connections.pairingCode'), { target: { value: 'expired-code' } });
    fireEvent.click(screen.getByText('connections.pair'));
    fireEvent.click(screen.getByText('connections.confirmPair'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Pairing expired');
    expect(activate).not.toHaveBeenCalled(); expect(screen.getByLabelText('connections.pairingCode')).not.toBeDisabled();
  });

  it('marks the active connection without offering a redundant switch', async () => {
    list.mockResolvedValue({
      supports_remote: true,
      state: { active_profile_id: 'local', profiles: [{ id: 'local', mode: 'local' }] },
    });
    render(<ConnectionPicker />);

    expect(await screen.findByText('connections.active')).toBeInTheDocument();
    expect(screen.queryByText('connections.connect')).not.toBeInTheDocument();
    expect(screen.queryByText('connections.switch')).not.toBeInTheDocument();
  });

  it('warns that pending settings will be lost before switching', async () => {
    render(<ConnectionPicker hasUnsavedSettings />);
    fireEvent.click(await screen.findByText('connections.connect'));

    expect(screen.getByRole('alert')).toHaveTextContent('connections.unsavedSettingsWarning');
    fireEvent.click(screen.getByText('common.cancel'));
    expect(activate).not.toHaveBeenCalled();
  });
});
