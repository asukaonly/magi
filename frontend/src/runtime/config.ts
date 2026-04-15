export interface RuntimeConfig {
  isDesktop: boolean;
  apiBaseUrl: string;
  sessionToken?: string;
  apiPid?: number;
  runtimeWorkerPid?: number;
}

interface ReadyCheckResponse {
  success?: boolean;
  data?: {
    ready?: boolean;
    status?: string;
  };
}

interface StartBackendResult {
  ok: boolean;
  baseUrl?: string;
  sessionToken?: string;
  apiPid?: number;
  runtimeWorkerPid?: number;
  error?: string;
}

interface PollStartupResult {
  ready: boolean;
  phase: string;
  error?: string;
}

const DEFAULT_API_BASE_URL = "http://localhost:8000/api";
const RESTRICTED_HOSTS = new Set(["0.0.0.0", "::", "[::]"]);
const READY_CHECK_INTERVAL_MS = 250;
const READY_CHECK_TIMEOUT_MS = 30000;
const STARTUP_POLL_INTERVAL_MS = 500;
const STARTUP_POLL_TIMEOUT_MS = 60000;

export type StartupPhase = "spawning" | "waiting_for_worker" | "connecting" | "ready" | "error";
export type StartupProgressCallback = (phase: StartupPhase) => void;

let runtimeConfig: RuntimeConfig = {
  isDesktop: true,
  apiBaseUrl: normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL),
};

let initialized = false;
let startupError: string | null = null;

export function isTauriRuntime(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return "__TAURI_INTERNALS__" in window || "__TAURI__" in window;
}

function resolvePreferredHost(preferredHost?: string): string {
  const browserHost = typeof window === "undefined" ? "" : window.location.hostname || "";
  const candidate = (preferredHost || browserHost).trim();
  if (candidate && !RESTRICTED_HOSTS.has(candidate)) {
    return candidate;
  }
  return "127.0.0.1";
}

export function normalizeConnectableUrl(raw: string, preferredHost?: string): string {
  const value = (raw || "").trim().replace(/\/+$/, "");
  if (!value) {
    return value;
  }

  try {
    const url = new URL(value);
    if (RESTRICTED_HOSTS.has(url.hostname)) {
      url.hostname = resolvePreferredHost(preferredHost);
    }
    return url.toString().replace(/\/+$/, "");
  } catch {
    return value;
  }
}

export function normalizeApiBaseUrl(raw: string, preferredHost?: string): string {
  const value = normalizeConnectableUrl(raw || DEFAULT_API_BASE_URL, preferredHost);
  return value.endsWith("/api") ? value : `${value}/api`;
}


function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function waitForBackendReady(apiBaseUrl: string): Promise<void> {
  const readyUrl = `${apiBaseUrl.replace(/\/+$/, "")}/ready`;
  const deadline = Date.now() + READY_CHECK_TIMEOUT_MS;

  while (Date.now() <= deadline) {
    try {
      const response = await fetch(readyUrl, {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
      });
      if (response.ok) {
        const payload = (await response.json()) as ReadyCheckResponse;
        if (payload.data?.ready) {
          return;
        }
      }
    } catch {
      // Keep polling until timeout while the backend is still starting.
    }

    await sleep(READY_CHECK_INTERVAL_MS);
  }

  throw new Error("Backend readiness check timed out");
}

export async function initializeRuntime(
  onProgress?: StartupProgressCallback,
): Promise<RuntimeConfig> {
  if (initialized) {
    if (startupError) {
      throw new Error(startupError);
    }
    return runtimeConfig;
  }

  if (!isTauriRuntime()) {
    startupError = "Desktop runtime requires Tauri shell";
    initialized = true;
    throw new Error(startupError);
  }

  try {
    const { invoke } = await import("@tauri-apps/api/core");

    // Phase 1: spawn backend (returns immediately).
    onProgress?.("spawning");
    const result = await invoke<StartBackendResult>("start_backend");
    if (!result?.ok || !result.baseUrl) {
      throw new Error(result?.error || "Desktop backend startup failed");
    }

    const apiBaseUrl = normalizeApiBaseUrl(result.baseUrl);

    // Phase 2: poll until the Rust gateway reports ready.
    onProgress?.("waiting_for_worker");
    const deadline = Date.now() + STARTUP_POLL_TIMEOUT_MS;
    while (Date.now() <= deadline) {
      const poll = await invoke<PollStartupResult>("poll_backend_startup");

      if (poll.error) {
        throw new Error(poll.error);
      }

      if (poll.ready) {
        onProgress?.("connecting");
        break;
      }

      // Update phase from Rust side.
      if (poll.phase === "waiting_for_worker") {
        onProgress?.("waiting_for_worker");
      }

      await sleep(STARTUP_POLL_INTERVAL_MS);
    }

    // Final readiness check: ensure /api/ready responds.
    await waitForBackendReady(apiBaseUrl);

    onProgress?.("ready");

    runtimeConfig = {
      isDesktop: true,
      apiBaseUrl,
      sessionToken: result.sessionToken || undefined,
      apiPid: result.apiPid,
      runtimeWorkerPid: result.runtimeWorkerPid,
    };
    initialized = true;
    startupError = null;
    window.__MAGI_RUNTIME__ = runtimeConfig;
    return runtimeConfig;
  } catch (error) {
    startupError = error instanceof Error ? error.message : "Desktop backend startup failed";
    initialized = true;
    throw new Error(startupError);
  }
}

export function resetRuntimeInitialization(): void {
  initialized = false;
  startupError = null;
}

export function getRuntimeConfig(): RuntimeConfig {
  return window.__MAGI_RUNTIME__ || runtimeConfig;
}
