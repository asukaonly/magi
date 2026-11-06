import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const { clients, revoke, pairing, profiles, runtime, t } = vi.hoisted(() => ({ clients: vi.fn(), revoke: vi.fn(), pairing: vi.fn(), profiles: vi.fn(), runtime: { profileId: 'local', apiBaseUrl: 'http://127.0.0.1:54321/api' }, t: (key: string) => key }));
vi.mock('@/components/connections/CenterNotificationPolicy', () => ({ CenterNotificationPolicy: () => null }));
vi.mock('@/api/modules/server', () => ({ serverApi: { clients, revoke, pairingGrant: pairing } }));
vi.mock('@/runtime/connections', () => ({ listConnectionProfiles: profiles }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => runtime, resetRuntimeInitialization: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }));
import { CenterAccessPanel } from '@/components/connections/CenterAccessPanel';
const client = { client_id: 'device-a', name: 'Living room', created_at_ms: 1, revoked_at_ms: null, role: 'admin', collector_scope: null };
beforeEach(() => {
  vi.clearAllMocks(); clients.mockResolvedValue([client]); revoke.mockResolvedValue(undefined);
  runtime.apiBaseUrl = 'http://127.0.0.1:54321/api';
  profiles.mockResolvedValue({ state: { profiles: [{ mode: 'local', id: 'local' }] } });
  window.localStorage.clear();
});
afterEach(() => vi.useRealTimers());
describe('center device access', () => {
  it('requires confirmation and removes only the revoked device from the active list', async () => {
    render(<CenterAccessPanel />);
    await screen.findByText('Living room');
    fireEvent.click(screen.getByText('connections.access.revoke'));
    expect(revoke).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('common.cancel'));
    expect(revoke).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('connections.access.revoke'));
    fireEvent.click(screen.getByText('connections.access.confirmRevoke'));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('device-a'));
    expect(await screen.findByText('connections.access.empty')).toBeInTheDocument();
  });
  it('creates a masked short-lived code on demand without persisting it', async () => {
    render(<CenterAccessPanel />);
    await screen.findByText('Living room');
    expect(pairing).not.toHaveBeenCalled();
    pairing.mockResolvedValue({ pairing_token: 'temporary-private-code', expires_at_ms: Date.now() + 1000 });
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByText('connections.access.createCode')); });
    expect(screen.getByLabelText('connections.pairingCode')).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText('connections.pairingCode')).toHaveValue('temporary-private-code');
    expect(screen.getByLabelText('connections.address')).toHaveValue('http://127.0.0.1:54321');
    expect(screen.getByText('connections.access.localAddressHint')).toBeInTheDocument();
    expect(JSON.stringify(window.localStorage)).not.toContain('temporary-private-code');
    await act(async () => { await vi.advanceTimersByTimeAsync(1001); });
    expect(screen.queryByLabelText('connections.pairingCode')).toBeNull();
    expect(screen.queryByLabelText('connections.address')).toBeNull();
  });
  it('copies the service origin rather than the development page address', async () => {
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    try {
      runtime.apiBaseUrl = 'https://magi.example:8443/api';
      pairing.mockResolvedValue({ pairing_token: 'temporary-private-code', expires_at_ms: Date.now() + 60_000 });
      render(<CenterAccessPanel />);
      await screen.findByText('Living room');
      fireEvent.click(screen.getByText('connections.access.createCode'));
      expect(await screen.findByLabelText('connections.address')).toHaveValue('https://magi.example:8443');
      expect(screen.queryByText('connections.access.localAddressHint')).toBeNull();
      fireEvent.click(screen.getByText('connections.access.copyAddress'));
      await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://magi.example:8443'));
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original);
      else Reflect.deleteProperty(navigator, 'clipboard');
    }
  });
  it('keeps failed revocation visible and does not claim that access was removed', async () => {
    revoke.mockRejectedValue(new Error('Response lost'));
    render(<CenterAccessPanel />);
    await screen.findByText('Living room');
    fireEvent.click(screen.getByText('connections.access.revoke'));
    fireEvent.click(screen.getByText('connections.access.confirmRevoke'));
    expect(await screen.findByRole('alert')).toHaveTextContent('connections.access.actionFailed');
    expect(screen.getByText('Living room')).toBeInTheDocument();
  });
});
