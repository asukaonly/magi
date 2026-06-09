import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchAvailability,
  refreshAvailability,
  type AvailabilityEntry,
} from '../api/modules/availability';

export interface UseAvailabilityResult {
  entries: AvailabilityEntry[];
  byId: Record<string, AvailabilityEntry>;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

/**
 * Fetch availability for a list of plugin IDs (or all plugins when omitted).
 * Re-fetches whenever the joined ID string changes. `refresh()` re-runs the fetch
 * and asks the backend to invalidate its cache first.
 */
export function useAvailability(pluginIds?: string[]): UseAvailabilityResult {
  const idsKey = useMemo(
    () => (pluginIds ? [...pluginIds].sort().join(',') : ''),
    [pluginIds],
  );
  const [entries, setEntries] = useState<AvailabilityEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const cancelled = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchAvailability(pluginIds);
      if (!cancelled.current) setEntries(result);
    } catch (err) {
      if (!cancelled.current) setError(err as Error);
    } finally {
      if (!cancelled.current) setLoading(false);
    }
  }, [idsKey]);

  useEffect(() => {
    cancelled.current = false;
    load();
    return () => {
      cancelled.current = true;
    };
  }, [load]);

  const refresh = useCallback(async () => {
    await refreshAvailability(pluginIds);
    await load();
  }, [pluginIds, load]);

  const byId = useMemo(() => {
    const map: Record<string, AvailabilityEntry> = {};
    for (const entry of entries) {
      map[entry.plugin_id] = entry;
    }
    return map;
  }, [entries]);

  return { entries, byId, loading, error, refresh };
}
