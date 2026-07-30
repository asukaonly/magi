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
  sessionToken?: string;
  apiPid?: number;
  runtimeWorkerPid?: number;
}
