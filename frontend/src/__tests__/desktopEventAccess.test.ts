import { afterEach, expect, it, vi } from 'vitest';
import { createDesktopEventClient } from '@/realtime/desktop-client';

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }));
vi.mock('@/api/client', () => ({ authenticatedFetch: fetchMock, resolveApiBaseUrl: () => 'https://center.example/api' }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => ({ serverId: 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0' }) }));
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });

it.each([
  ['invalid_client_credential', true],
  ['local_credential_missing', true],
  [new Error('center_authorization_rejected'), true],
  ['center_network_unavailable', false],
  ['auth_busy', false],
  [new TypeError('Failed to fetch'), false],
])('distinguishes native session rejection %s from temporary unavailability', async (error, accessDenied) => {
  vi.useFakeTimers();
  fetchMock.mockRejectedValue(error);
  const client = createDesktopEventClient();
  const status = vi.fn();
  client.subscribeStatus(status);
  await expect(client.connect()).rejects.toBeDefined();
  expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ connected: false, accessDenied }));
  client.disconnect();
});
