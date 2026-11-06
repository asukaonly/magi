import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const { pairing, runtime, t } = vi.hoisted(() => ({ pairing: vi.fn(), runtime: { apiBaseUrl: 'https://magi.example/api' }, t: (key: string) => key }));
vi.mock('@/api/modules/server', () => ({ serverApi: { pairingGrant: pairing } }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => runtime }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }));
import { PairingCodeDialog } from '@/components/connections/PairingCodeDialog';
const grant = { network: { listen_host: '127.0.0.1', listen_port: 52936, lan_ips: ['192.168.1.9', '100.100.0.8'] }, pairing_token: 'a1b2c3d4'.repeat(8), expires_at_ms: Date.now() + 1800000 };
const open = () => fireEvent.click(screen.getByRole('button', { name: 'connections.access.createCode' }));
const close = () => fireEvent.click(within(screen.getByRole('dialog')).getAllByRole('button', { name: 'common.close' })[0]);
beforeEach(() => { runtime.apiBaseUrl = 'https://magi.example/api'; pairing.mockReset(); pairing.mockResolvedValue(grant); });

it('opens immediately during generation and lets users retry a failed request', async () => {
  let reject!: (error: Error) => void;
  pairing.mockImplementationOnce(() => new Promise((_, failure) => { reject = failure; }));
  render(<PairingCodeDialog />);
  open();
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('connections.access.generating');
  await act(async () => reject(new Error('Offline')));
  expect(screen.getByRole('alert')).toHaveTextContent('connections.access.generateFailed');
  fireEvent.click(screen.getByRole('button', { name: 'connections.access.regenerate' }));
  expect(await screen.findByLabelText('connections.pairingCode')).toHaveValue(grant.pairing_token);
});

it('discards closed-dialog results even when a new request has already finished', async () => {
  let resolve!: (value: typeof grant) => void;
  pairing.mockImplementationOnce(() => new Promise((finish) => { resolve = finish; }));
  render(<PairingCodeDialog />);
  open(); close(); open();
  expect(await screen.findByLabelText('connections.pairingCode')).toHaveValue(grant.pairing_token);
  await act(async () => resolve({ ...grant, pairing_token: 'stale-code' }));
  expect(screen.getByLabelText('connections.pairingCode')).toHaveValue(grant.pairing_token);
  close();
  expect(screen.queryByDisplayValue(grant.pairing_token)).not.toBeInTheDocument();
});

it('copies the complete code and keeps it readable if clipboard access fails', async () => {
  const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  const writeText = vi.fn().mockRejectedValueOnce(new Error('Denied')).mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  try {
    render(<PairingCodeDialog />); open();
    await screen.findByLabelText('connections.pairingCode');
    fireEvent.click(screen.getByRole('button', { name: 'connections.access.copy' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('connections.access.copyFailed');
    expect(screen.getByLabelText('connections.pairingCode')).toHaveValue(grant.pairing_token);
    fireEvent.click(screen.getByRole('button', { name: 'connections.access.copy' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'connections.access.copied' })).toBeInTheDocument());
    expect(writeText).toHaveBeenLastCalledWith(grant.pairing_token);
  } finally {
    if (original) Object.defineProperty(navigator, 'clipboard', original);
    else Reflect.deleteProperty(navigator, 'clipboard');
  }
});


it('distinguishes a loopback connection from private IPs and an unknown remote endpoint', async () => {
  runtime.apiBaseUrl = 'http://127.0.0.1:52936/api';
  render(<PairingCodeDialog />); open();
  expect(await screen.findByLabelText('connections.pairingCode')).toHaveAttribute('type', 'text');
  expect(screen.getByLabelText('connections.address')).toHaveValue('http://127.0.0.1:52936');
  expect(screen.getByText('192.168.1.9')).toBeInTheDocument();
  expect(screen.getByText('100.100.0.8')).toBeInTheDocument();
  expect(screen.getByText('connections.access.remoteAddressUnknown')).toBeInTheDocument();
  expect(screen.getByText('connections.access.localNetworkHint')).toBeInTheDocument();
  expect(screen.queryByDisplayValue('http://192.168.1.9:52936')).not.toBeInTheDocument();
});

it('keeps the actual HTTPS entry point and its port instead of substituting a server IP', async () => {
  runtime.apiBaseUrl = 'https://magi.example:8443/api';
  render(<PairingCodeDialog />); open();
  expect(await screen.findByLabelText('connections.address')).toHaveValue('https://magi.example:8443');
  expect(screen.getByText('192.168.1.9')).toBeInTheDocument();
  expect(screen.queryByText('connections.access.remoteAddressUnknown')).not.toBeInTheDocument();
  expect(screen.getByText('connections.access.remoteNetworkHint')).toBeInTheDocument();
});

it('still shows the pairing code when listener metadata is unavailable', async () => {
  pairing.mockResolvedValue({ ...grant, network: null });
  render(<PairingCodeDialog />); open();
  expect(await screen.findByLabelText('connections.pairingCode')).toHaveValue(grant.pairing_token);
  expect(screen.getByText('connections.access.networkUnavailable')).toBeInTheDocument();
});
