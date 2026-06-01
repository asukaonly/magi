import { useCallback, useEffect, useRef, useState } from 'react';
import {
  memoryPortraitApi,
  type PortraitPayload,
} from '@/api/modules/memoryPortrait';

const THROTTLE_MS = 5 * 60 * 1000;
const COMPUTING_POLL_MS = 10_000;     // poll backend every 10s while computing
const COMPUTING_POLL_MAX_ATTEMPTS = 6; // stop after ~60s total

export interface UseMemoryPortraitArgs {
  sessionId: string;
  userId: string;
  personaId: string;
}

export interface UseMemoryPortraitResult {
  payload: PortraitPayload | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useMemoryPortrait({
  sessionId,
  userId,
  personaId,
}: UseMemoryPortraitArgs): UseMemoryPortraitResult {
  const [payload, setPayload] = useState<PortraitPayload | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastFetchAt = useRef<number>(0);
  const lastPersonaId = useRef<string>(personaId);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollAttemptsRef = useRef<number>(0);

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const fetchPayload = useCallback(
    async (force: boolean): Promise<PortraitPayload | null> => {
      if (!sessionId || !userId || !personaId) {
        setPayload(null);
        return null;
      }
      setIsLoading(true);
      setError(null);
      try {
        const result = await memoryPortraitApi.get(sessionId, userId, { force });
        setPayload(result);
        lastFetchAt.current = Date.now();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, userId, personaId],
  );

  const schedulePollIfComputing = useCallback(
    (latest: PortraitPayload | null) => {
      clearPollTimer();
      // Keep polling whenever the backend is still working: either the
      // initial "computing" cold-start, or a stale-while-revalidate
      // response where a background recompute is in flight.
      const stillComputing =
        !!latest &&
        (latest.cold_start_reason === 'computing' || latest.is_stale === true);
      if (!stillComputing) {
        pollAttemptsRef.current = 0;
        return;
      }
      if (pollAttemptsRef.current >= COMPUTING_POLL_MAX_ATTEMPTS) {
        return;
      }
      pollAttemptsRef.current += 1;
      pollTimerRef.current = setTimeout(() => {
        void (async () => {
          const next = await fetchPayload(false);
          schedulePollIfComputing(next);
        })();
      }, COMPUTING_POLL_MS);
    },
    [clearPollTimer, fetchPayload],
  );

  // Initial fetch + reset polling whenever the session/user/persona triple changes.
  useEffect(() => {
    if (!sessionId || !userId || !personaId) {
      clearPollTimer();
      return;
    }
    pollAttemptsRef.current = 0;
    void (async () => {
      const next = await fetchPayload(false);
      schedulePollIfComputing(next);
    })();
    return clearPollTimer;
  }, [sessionId, userId, personaId, fetchPayload, schedulePollIfComputing, clearPollTimer]);

  // Persona switch forces a fresh fetch (server cache key changes anyway).
  useEffect(() => {
    if (lastPersonaId.current && lastPersonaId.current !== personaId) {
      pollAttemptsRef.current = 0;
      void (async () => {
        const next = await fetchPayload(true);
        schedulePollIfComputing(next);
      })();
    }
    lastPersonaId.current = personaId;
  }, [personaId, fetchPayload, schedulePollIfComputing]);

  const refresh = useCallback(() => {
    if (Date.now() - lastFetchAt.current < THROTTLE_MS) {
      return;
    }
    pollAttemptsRef.current = 0;
    void (async () => {
      const next = await fetchPayload(false);
      schedulePollIfComputing(next);
    })();
  }, [fetchPayload, schedulePollIfComputing]);

  return { payload, isLoading, error, refresh };
}
