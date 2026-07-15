/**
 * Lists the plugins the backend can surface in the empty-state grid: the union
 * of locally-installed sensors and registry-available plugins that could fill a
 * data gap, availability-filtered server-side.
 *
 * Powers the Timeline/Memory empty-state CTA grid. Each item's `installed` flag
 * drives the install-first activation path (install-then-activate for
 * registry-only plugins).
 */
import { useCallback, useEffect, useState } from "react";
import {
  listInstallable,
  type InstallableCatalogMode,
  type InstallableItem,
} from "../api/modules/systemSuggestions";

export function useInstallableSensors(enabled = true) {
  const [items, setItems] = useState<InstallableItem[]>([]);
  const [catalogMode, setCatalogMode] =
    useState<InstallableCatalogMode | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listInstallable();
      setItems(result.items);
      setCatalogMode(result.catalog_mode);
    } catch (caught) {
      setItems([]);
      setCatalogMode(null);
      setError(
        caught instanceof Error
          ? caught
          : new Error("Failed to load installable sources"),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) {
      void refresh();
    }
  }, [enabled, refresh]);

  return { items, catalogMode, loading, error, refresh };
}
