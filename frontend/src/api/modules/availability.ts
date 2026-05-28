/**
 * Availability API client.
 *
 * Wraps `GET /availability` and `POST /availability/refresh`, which surface the
 * AvailabilityResolver's view of whether each plugin's data source is reachable
 * on this machine (file present, executable on PATH, app installed, etc.).
 */
import { api, unwrapGatewayPayload } from '../client';

export type AvailabilityReason =
  | 'available'
  | 'unsupported_platform'
  | 'missing_file'
  | 'missing_executable'
  | 'app_not_installed'
  | 'no_descriptor'
  | 'check_error';

export interface AvailabilityEntry {
  plugin_id: string;
  available: boolean;
  reason: AvailabilityReason;
  detail: string | null;
  /** ISO-8601 timestamp of when the resolver last evaluated this plugin. */
  checked_at: string;
}

interface AvailabilityListResponse {
  entries: AvailabilityEntry[];
}

interface AvailabilityRefreshResponse {
  invalidated_plugin_ids: string[];
}

/**
 * Fetch availability for a set of plugins.
 *
 * When `pluginIds` is omitted (or empty) the gateway returns availability for
 * every plugin currently known to the host.
 */
export async function fetchAvailability(
  pluginIds?: string[],
): Promise<AvailabilityEntry[]> {
  const params =
    pluginIds && pluginIds.length > 0
      ? { plugin_ids: pluginIds.join(',') }
      : {};
  const response = await api.get<AvailabilityListResponse>('/availability', {
    params,
  });
  return unwrapGatewayPayload(response).entries;
}

/**
 * Invalidate the resolver's cache for a set of plugins (or all when ids omitted).
 * Returns the plugin ids the resolver actually evicted.
 */
export async function refreshAvailability(
  pluginIds?: string[],
): Promise<string[]> {
  const body =
    pluginIds && pluginIds.length > 0 ? { plugin_ids: pluginIds } : {};
  const response = await api.post<AvailabilityRefreshResponse>(
    '/availability/refresh',
    body,
  );
  return unwrapGatewayPayload(response).invalidated_plugin_ids;
}
