import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useRequestOwner } from '@/hooks/useRequestOwner';
/**
 * Lists the plugins the backend can surface in the empty-state grid: the union
 * of locally-installed sources and registry-available plugins that could fill a
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

export function useInstallableSources(enabled = true) {
  const [items, setItems] = useState<InstallableItem[]>([]);
  const [catalogMode, setCatalogMode] =
    useState<InstallableCatalogMode | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<Error | null>(null);

  const beginRead = useRequestOwner(String(enabled));
  const load = useCallback(async (silent = false) => {
    const isCurrent = beginRead('catalog');
    if (!silent) { setLoading(true); setError(null); }
    try {
      const result = await listInstallable();
      if (!isCurrent()) return;
      setError(null);
      setItems(result.items);
      setCatalogMode(result.catalog_mode);
    } catch (caught) {
      if (!isCurrent()) return;
      if (!silent) setError(
        caught instanceof Error
          ? caught
          : new Error("Failed to load installable sources"),
      );
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [beginRead]);

  const refresh = useCallback(() => load(), [load]);

  useEffect(() => {
    if (enabled) {
      void refresh();
    }
  }, [enabled, refresh]);

  useCenterRefresh(() => load(true), enabled);

  return { items, catalogMode, loading, error, refresh };
}
