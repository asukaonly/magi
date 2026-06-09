/**
 * Lists the user's active system-suggestion dismissals and lets them clear one.
 *
 * Used by the Settings "dismissed suggestions" section and the sidebar badge.
 * `activeCount` counts only non-permanent dismissals (kind !== 'never'), since
 * the badge nudges the user to revisit suggestions they merely snoozed.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  listDismissals,
  clearDismissal,
  type DismissalItem,
} from '../api/modules/systemSuggestions';

export function useSuggestionDismissals() {
  const [items, setItems] = useState<DismissalItem[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listDismissals());
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const clear = useCallback(
    async (dedupeKey: string) => {
      await clearDismissal(dedupeKey);
      await refresh();
    },
    [refresh],
  );

  const activeCount = items.filter((d) => d.kind !== 'never').length;

  return { items, activeCount, loading, refresh, clear };
}
