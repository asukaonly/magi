export interface RuntimeConfig {
  isDesktop: boolean;
  apiBaseUrl: string;
  wsBaseUrl: string;
  sessionToken?: string;
  backendPid?: number;
}

interface StartBackendResult {
  ok: boolean;
  baseUrl?: string;
  wsBaseUrl?: string;
  sessionToken?: string;
  pid?: number;
  error?: string;
}

const DEFAULT_API_BASE_URL = "http://localhost:8000/api";

let runtimeConfig: RuntimeConfig = {
  isDesktop: false,
  apiBaseUrl: normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL),
  wsBaseUrl: "",
};
runtimeConfig.wsBaseUrl = buildWsBaseUrl(runtimeConfig.apiBaseUrl);

let initialized = false;
let startupError: string | null = null;

function isTauriRuntime(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return "__TAURI_INTERNALS__" in window || "__TAURI__" in window;
}

function normalizeApiBaseUrl(raw: string): string {
  const value = (raw || DEFAULT_API_BASE_URL).trim().replace(/\/+$/, "");
  return value.endsWith("/api") ? value : `${value}/api`;
}

function buildWsBaseUrl(apiBaseUrl: string): string {
  const origin = apiBaseUrl.replace(/\/api$/, "");
  return origin.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
}

export async function initializeRuntime(): Promise<RuntimeConfig> {
  if (initialized) {
    if (startupError) {
      throw new Error(startupError);
    }
    return runtimeConfig;
  }

  if (!isTauriRuntime()) {
    runtimeConfig = {
      ...runtimeConfig,
      isDesktop: false,
      wsBaseUrl: buildWsBaseUrl(runtimeConfig.apiBaseUrl),
      sessionToken: undefined,
      backendPid: undefined,
    };
    initialized = true;
    window.__MAGI_RUNTIME__ = runtimeConfig;
    return runtimeConfig;
  }

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const result = await invoke<StartBackendResult>("start_backend");
    if (!result?.ok || !result.baseUrl) {
      throw new Error(result?.error || "Desktop backend startup failed");
    }

    const apiBaseUrl = normalizeApiBaseUrl(result.baseUrl);
    runtimeConfig = {
      isDesktop: true,
      apiBaseUrl,
      wsBaseUrl: result.wsBaseUrl || buildWsBaseUrl(apiBaseUrl),
      sessionToken: result.sessionToken || undefined,
      backendPid: result.pid,
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

