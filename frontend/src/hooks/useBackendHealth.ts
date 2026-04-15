import { useEffect, useRef } from 'react';
import { apiClient } from '@/api/client';
import { useBackendHealthStore } from '@/stores/backend-health';

const POLL_INTERVAL_MS = 12_000;
const FAILURE_THRESHOLD = 2;

const BACKEND_EXIT_EVENT = 'backend-exit';

interface ReadyResponse {
  success: boolean;
  data: {
    ready: boolean;
    status: string;
    runtime_ready: boolean;
    runtime_status: string;
  };
}

/**
 * Poll /api/ready to detect backend health changes and listen for
 * the Tauri `backend-exit` event emitted when the sidecar process terminates.
 */
export function useBackendHealth(): void {
  const setHealth = useBackendHealthStore((s) => s.setHealth);
  const failCount = useRef(0);

  // Tauri backend-exit event listener
  useEffect(() => {
    let unlisten: (() => void) | undefined;

    const register = async () => {
      if (typeof window === 'undefined' || !('__TAURI_INTERNALS__' in window || '__TAURI__' in window)) {
        return;
      }
      const { listen } = await import('@tauri-apps/api/event');
      unlisten = await listen<string>(BACKEND_EXIT_EVENT, () => {
        failCount.current = FAILURE_THRESHOLD;
        setHealth('exited');
      });
    };

    void register();
    return () => {
      unlisten?.();
    };
  }, [setHealth]);

  // Periodic health polling
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;

    const check = async () => {
      try {
        const resp = await apiClient.get<ReadyResponse>('/ready');
        const data = resp.data?.data;
        failCount.current = 0;
        if (data?.status === 'ready') {
          setHealth('healthy', data.runtime_status);
        } else {
          setHealth('degraded', data?.runtime_status ?? null);
        }
      } catch {
        failCount.current += 1;
        if (failCount.current >= FAILURE_THRESHOLD) {
          // Distinguish: can we still reach the Rust gateway?
          try {
            await apiClient.get('/health');
            // Gateway alive but Python down
            setHealth('offline', 'unreachable');
          } catch {
            // Whole backend unreachable
            setHealth('offline');
          }
        }
      }
    };

    // Initial check after a short delay (give bootstrap time)
    const initialTimeout = setTimeout(() => {
      void check();
      timer = setInterval(() => void check(), POLL_INTERVAL_MS);
    }, 3_000);

    return () => {
      clearTimeout(initialTimeout);
      if (timer) clearInterval(timer);
    };
  }, [setHealth]);
}
