import { useCallback, useEffect, useRef, useState } from 'react';
import {
  memoryPortraitApi,
  type PortraitPayload,
} from '@/api/modules/memoryPortrait';

const THROTTLE_MS = 5 * 60 * 1000;

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

  const fetchPayload = useCallback(
    async (force: boolean) => {
      if (!sessionId || !userId || !personaId) {
        setPayload(null);
        return;
      }
      setIsLoading(true);
      setError(null);
      try {
        const result = await memoryPortraitApi.get(sessionId, userId, { force });
        setPayload(result);
        lastFetchAt.current = Date.now();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, userId, personaId],
  );

  useEffect(() => {
    if (!sessionId || !userId || !personaId) {
      return;
    }
    void fetchPayload(false);
  }, [sessionId, userId, fetchPayload, personaId]);

  useEffect(() => {
    if (lastPersonaId.current && lastPersonaId.current !== personaId) {
      void fetchPayload(true);
    }
    lastPersonaId.current = personaId;
  }, [personaId, fetchPayload]);

  const refresh = useCallback(() => {
    if (Date.now() - lastFetchAt.current < THROTTLE_MS) {
      return;
    }
    void fetchPayload(false);
  }, [fetchPayload]);

  return { payload, isLoading, error, refresh };
}
