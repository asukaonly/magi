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
const RESTRICTED_HOSTS = new Set(["0.0.0.0", "::", "[::]"]);

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

export function buildWsBaseUrl(apiBaseUrl: string): string {
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

