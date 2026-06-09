import { useEffect, useRef } from 'react';
import { listen } from '@tauri-apps/api/event';
import { apiClient } from '@/api/client';
import { useBackendHealthStore } from '@/stores/backend-health';

const INITIAL_CHECK_DELAY_MS = 3_000;
const POLL_INTERVAL_MS = 12_000;
const RECOVERY_POLL_INTERVAL_MS = 4_000;
const STARTUP_WARNING_GRACE_MS = 30_000;
const FAILURE_THRESHOLD = 2;
const DEGRADED_THRESHOLD = 2;

const BACKEND_EXIT_EVENT = 'backend-exit';

interface ReadyResponse {
  success: boolean;
  data: {
    ready: boolean;
    status: string;
    runtime_ready: boolean;
    runtime_status: string;
    worker_ready?: boolean;
    llm_ready?: boolean;
    agent_runtime_ready?: boolean;
    startup_state?: string;
    deferred_reason?: string | null;
  };
}

function getHealthDetails(data: ReadyResponse['data'] | undefined) {
  return {
    runtimeStatus: data?.runtime_status ?? null,
    startupState: data?.startup_state ?? null,
    deferredReason: data?.deferred_reason ?? null,
    llmReady: data?.llm_ready ?? null,
    agentRuntimeReady: data?.agent_runtime_ready ?? null,
  };
}

function isTransientStartup(data: ReadyResponse['data'] | undefined): boolean {
  return data?.startup_state === 'starting' || data?.startup_state === 'deferred';
}

/**
 * Poll /api/ready to detect backend health changes and listen for
 * the Tauri `backend-exit` event emitted when the sidecar process terminates.
 */
export function useBackendHealth(): void {
  const setHealth = useBackendHealthStore((s) => s.setHealth);
  const failCount = useRef(0);
  const degradedCount = useRef(0);
  const startedAt = useRef(Date.now());

  // Tauri backend-exit event listener
  useEffect(() => {
    let unlisten: (() => void) | undefined;

    const register = async () => {
      if (typeof window === 'undefined' || !('__TAURI_INTERNALS__' in window || '__TAURI__' in window)) {
        return;
      }
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
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const schedule = (delayMs: number) => {
      if (cancelled) {
        return;
      }
      timer = setTimeout(() => {
        void check();
      }, delayMs);
    };

    const check = async () => {
      try {
        const resp = await apiClient.get<ReadyResponse>('/ready');
        const data = resp.data?.data;
        const withinStartupGrace = isTransientStartup(data) && Date.now() - startedAt.current < STARTUP_WARNING_GRACE_MS;

        failCount.current = 0;
        if (data?.status === 'ready') {
          degradedCount.current = 0;
          setHealth('healthy', getHealthDetails(data));
        } else {
          degradedCount.current += 1;
          if (withinStartupGrace) {
            setHealth('healthy', getHealthDetails(data));
          } else if (degradedCount.current >= DEGRADED_THRESHOLD) {
            setHealth('degraded', getHealthDetails(data));
          }
        }

        schedule(data?.status === 'ready' ? POLL_INTERVAL_MS : RECOVERY_POLL_INTERVAL_MS);
      } catch {
        failCount.current += 1;
        degradedCount.current = 0;
        if (failCount.current >= FAILURE_THRESHOLD) {
          // Distinguish: can we still reach the Rust gateway?
          try {
            await apiClient.get('/health');
            // Gateway alive but Python down
            setHealth('offline', { runtimeStatus: 'unreachable' });
          } catch {
            // Whole backend unreachable
            setHealth('offline');
          }
        }

        schedule(RECOVERY_POLL_INTERVAL_MS);
      }
    };

    // Initial check after a short delay (give bootstrap time)
    schedule(INITIAL_CHECK_DELAY_MS);

    return () => {
      cancelled = true;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [setHealth]);
}
