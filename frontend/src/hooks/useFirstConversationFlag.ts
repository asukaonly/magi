import { useCallback, useEffect, useState } from 'react';
import { configApi } from '../api/modules/config';

export interface UseFirstConversationFlagResult {
  completed: boolean;
  loading: boolean;
  markCompleted: () => Promise<void>;
}

/**
 * Reads `preferences.first_conversation_completed` from the user config and
 * exposes a setter that persists `true` back to the backend. Used by
 * `<FirstConversationChips>` to gate visibility.
 */
export function useFirstConversationFlag(): UseFirstConversationFlagResult {
  const [completed, setCompleted] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    configApi
      .get()
      .then((response: any) => {
        if (cancelled) return;
        const cfg = response?.data; // unwrap gateway envelope
        setCompleted(Boolean(cfg?.preferences?.first_conversation_completed));
      })
      .catch(() => {
        if (cancelled) return;
        setCompleted(false);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const markCompleted = useCallback(async () => {
    setCompleted(true); // optimistic
    try {
      const response = await configApi.get();
      const current = (response as any)?.data;
      if (!current) return;
      const next = structuredClone(current) as any;
      if (!next.preferences) next.preferences = {};
      next.preferences.first_conversation_completed = true;
      await configApi.update(next);
    } catch (err) {
      console.warn('failed to persist first_conversation_completed', err);
    }
  }, []);

  return { completed, loading, markCompleted };
}
