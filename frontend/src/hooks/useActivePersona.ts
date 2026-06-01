/**
 * useActivePersona — fetches the currently active persona's display data
 * (name, avatar, created_at) for the chat shell PersonaHeader.
 *
 * Two-step fetch: GET /personas/active to resolve the active persona_id,
 * then GET /personas/{id} for the detail record. Silently returns
 * `persona: null` when no active persona exists (e.g. during onboarding)
 * so the PersonaHeader can render nothing instead of a skeleton.
 */
import { useEffect, useState } from 'react';
import { personasApi } from '@/api/modules/personas';

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

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const active = await personasApi.getActive();
        const activeId = active.persona_id;
        if (!activeId) {
          if (!cancelled) {
            setPersona(null);
            setLoading(false);
          }
          return;
        }
        const detail = await personasApi.get(activeId);
        const data = detail.data;
        if (!cancelled) {
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
        if (!cancelled) {
          setPersona(null);
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { persona, loading };
}
