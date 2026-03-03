/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface RuntimeConfig {
  isDesktop: boolean;
  apiBaseUrl: string;
  wsBaseUrl: string;
  sessionToken?: string;
  backendPid?: number;
}

interface Window {
  __MAGI_RUNTIME__?: RuntimeConfig;
}
