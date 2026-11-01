import { authenticatedFetch, resolveApiBaseUrl } from '@/api/client';
import { getRuntimeConfig } from '@/runtime/config';
import { SseClient } from './sse-client';

/** Desktop binds a platform-neutral event reader to its active service session. */
export function createDesktopEventClient(scope: 'product' | 'diagnostics' = 'product'): SseClient {
  const serverId = getRuntimeConfig().serverId;
  if (!serverId) throw new Error('Service identity is unavailable');
  return new SseClient({ baseUrl: resolveApiBaseUrl(), serverId, fetch: authenticatedFetch }, scope);
}
