import { invoke } from "@tauri-apps/api/core";

export interface RuntimeConfig {
  isDesktop: boolean;
  apiBaseUrl: string;
  sessionToken?: string;
  apiPid?: number;
  runtimeWorkerPid?: number;
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

export interface BackendStartupDiagnostics {
  logPath?: string;
  logExcerpt?: string;
  logReadError?: string;
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

export async function readBackendStartupDiagnostics(): Promise<BackendStartupDiagnostics | null> {
  if (!isTauriRuntime()) {
    return null;
  }

  try {
    const diagnostics = await invoke<BackendStartupDiagnostics>("read_backend_startup_diagnostics");
    if (!diagnostics?.logPath && !diagnostics?.logExcerpt && !diagnostics?.logReadError) {
      return null;
    }
    return diagnostics;
  } catch {
    return null;
  }
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
  // Poll the gateway liveness endpoint — a plain 200 confirms the Axum
  // gateway is bound and serving. We do not require the Python worker
  // readiness signal here; that is monitored separately by the
  // health-check hook after startup completes.
  const healthUrl = `${apiBaseUrl.replace(/\/+$/, "").replace(/\/api$/, "")}/api/health`;
  const deadline = Date.now() + READY_CHECK_TIMEOUT_MS;

  while (Date.now() <= deadline) {
    try {
      const response = await fetch(healthUrl, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (response.ok) {
        return;
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
    const t0 = performance.now();

    // Phase 1: spawn backend (returns immediately).
    onProgress?.("spawning");
    const result = await invoke<StartBackendResult>("start_backend");
    console.log(`[startup] start_backend: ${(performance.now() - t0).toFixed(0)}ms`);
    if (!result?.ok || !result.baseUrl) {
      throw new Error(result?.error || "Desktop backend startup failed");
    }

    const apiBaseUrl = normalizeApiBaseUrl(result.baseUrl);

    // Phase 2: poll until the Rust gateway reports ready.
    onProgress?.("waiting_for_worker");
    const pollStart = performance.now();
    const deadline = Date.now() + STARTUP_POLL_TIMEOUT_MS;
    let pollCount = 0;
    while (Date.now() <= deadline) {
      const poll = await invoke<PollStartupResult>("poll_backend_startup");
      pollCount++;

      if (poll.error) {
        throw new Error(poll.error);
      }

      if (poll.ready) {
        console.log(`[startup] poll_backend_startup ready after ${pollCount} polls, ${(performance.now() - pollStart).toFixed(0)}ms`);
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
    const readyStart = performance.now();
    await waitForBackendReady(apiBaseUrl);
    console.log(`[startup] waitForBackendReady: ${(performance.now() - readyStart).toFixed(0)}ms`);
    console.log(`[startup] total: ${(performance.now() - t0).toFixed(0)}ms`);

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
