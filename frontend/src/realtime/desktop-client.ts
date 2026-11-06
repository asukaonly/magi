import { authenticatedFetch, resolveApiBaseUrl } from '@/api/client';
import { getRuntimeConfig } from '@/runtime/config';
import { EventAccessError, SseClient } from './sse-client';

const ACCESS_ERROR_CODES = new Set([
  'invalid_client_credential', 'client_auth_required', 'center_authorization_rejected',
  'origin_not_allowed', 'local_credential_missing', 'local_credentials_invalid',
]);

async function fetchEvents(input: string, init: RequestInit): Promise<Response> {
  try {
    return await authenticatedFetch(input, init);
  } catch (error) {
    const code = typeof error === 'string' ? error : error instanceof Error ? error.message : null;
    if (code && ACCESS_ERROR_CODES.has(code)) throw new EventAccessError(code);
    throw error;
  }
}

/** Desktop binds a platform-neutral event reader to its active service session. */
export function createDesktopEventClient(scope: 'product' | 'diagnostics' = 'product'): SseClient {
  const serverId = getRuntimeConfig().serverId;
  if (!serverId) throw new Error('Service identity is unavailable');
  return new SseClient({ baseUrl: resolveApiBaseUrl(), serverId, fetch: fetchEvents }, scope);
}
