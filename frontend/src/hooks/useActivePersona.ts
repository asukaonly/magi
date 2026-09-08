/**
 * useActivePersona — fetches the currently active persona's display data
 * (name, avatar, created_at) for the chat shell PersonaHeader.
 *
 * Two-step fetch: GET /personas/active to resolve the active persona_id,
 * then GET /personas/{id} for the detail record. Silently returns
 * `persona: null` when no active persona exists (e.g. during onboarding)
 * so the PersonaHeader can render nothing instead of a skeleton.
 */
import { useCallback, useEffect, useState } from 'react';
import { personasApi } from '@/api/modules/personas';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useRequestOwner } from '@/hooks/useRequestOwner';

export interface ActivePersonaSnapshot {
  personaId: string;
  name: string;
  avatarPath: string;
  createdAt: number; // unix seconds
}

export interface UseActivePersonaResult {
  persona: ActivePersonaSnapshot | null;
  loading: boolean;
}

export function useActivePersona(): UseActivePersonaResult {
  const [persona, setPersona] = useState<ActivePersonaSnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const beginRead = useRequestOwner();
  const load = useCallback(async () => {
    const isCurrent = beginRead('active-persona');
    try {
      const active = await personasApi.getActive();
      const activeId = active.persona_id;
      if (!activeId) {
        if (isCurrent()) {
          setPersona(null);
          setLoading(false);
        }
        return;
      }
      const detail = await personasApi.get(activeId);
      const data = detail.data;
      if (isCurrent()) {
        setPersona(data
          ? {
              personaId: data.persona_id,
              name: data.name,
              avatarPath: data.avatar_path || '',
              createdAt: data.created_at,
            }
          : null);
        setLoading(false);
      }
    } catch {
      if (isCurrent()) {
        setLoading(false);
      }
    }
  }, [beginRead]);
  useEffect(() => { void load(); }, [load]);
  useCenterRefresh(load);

  return { persona, loading };
}
