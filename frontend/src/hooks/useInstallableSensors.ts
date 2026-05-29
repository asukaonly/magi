/**
 * Lists the plugins the backend can surface in the empty-state grid: the union
 * of locally-installed sensors and registry-available plugins that could fill a
 * data gap, availability-filtered server-side.
 *
 * Powers the Timeline/Memory empty-state CTA grid. Each item's `installed` flag
 * drives the install-first activation path (install-then-activate for
 * registry-only plugins).
 */
import { useCallback, useEffect, useState } from 'react';
import { listInstallable, type InstallableItem } from '../api/modules/systemSuggestions';

export function useInstallableSensors() {
  const [items, setItems] = useState<InstallableItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listInstallable());
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { items, loading, refresh };
}
