/**
 * REST client for /api/code_agent endpoints.
 *
 * Backend returns plain JSON objects (no {success,data} wrapper). The
 * defensive ``unwrap`` matches how MCPApi handles both shapes.
 */
import { api } from '../client';
import type { ApiResponse } from '../client';

export type AdapterName = 'claude_code' | 'codex';

export interface ProbeResult {
  name: AdapterName;
  installed: boolean;
  binary_path: string | null;
  version: string | null;
  detected_at: number;
  error: string | null;
  extras: Record<string, unknown>;
}

export interface ConstraintsSettings {
  forbid_paths: string[];
  forbid_git_commit: boolean;
  forbid_git_push: boolean;
  default_timeout_s: number;
}

export interface ClaudeCodeSettings {
  binary_path: string;
  default_model: string;
  extra_args: string[];
  max_budget_usd: number;
  allowed_tools: string;
  disallowed_tools: string;
}

export interface CodexSettings {
  binary_path: string;
  default_model: string;
  extra_args: string[];
  sandbox: string;
  ask_for_approval: string;
}

export interface CodeAgentSettings {
  enabled: boolean;
  default_adapter: AdapterName;
  claude_code: ClaudeCodeSettings;
  codex: CodexSettings;
  constraints: ConstraintsSettings;
}

export interface ProbeResponse {
  results: Record<AdapterName, ProbeResult>;
}

export interface SettingsResponse {
  settings: CodeAgentSettings;
  workspace_used: string | null;
}

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K];
};

export type CodeAgentSettingsPatch = DeepPartial<CodeAgentSettings>;

const unwrap = <T>(payload: T | ApiResponse<T>): T => {
  if (
    payload &&
    typeof payload === 'object' &&
    'success' in (payload as ApiResponse<T>) &&
    typeof (payload as ApiResponse<T>).success === 'boolean'
  ) {
    return ((payload as ApiResponse<T>).data ?? payload) as T;
  }
  return payload as T;
};


export const codeAgentApi = {
  probe: async (force = false): Promise<ProbeResponse> => {
    const response = await api.get<ProbeResponse>(
      `/code_agent/probe${force ? '?force=true' : ''}`,
    );
    return unwrap(response as ProbeResponse | ApiResponse<ProbeResponse>);
  },

  rescan: async (): Promise<ProbeResponse> => {
    const response = await api.post<ProbeResponse>('/code_agent/rescan', {});
    return unwrap(response as ProbeResponse | ApiResponse<ProbeResponse>);
  },

  getSettings: async (workspace: string | null): Promise<SettingsResponse> => {
    const url = workspace
      ? `/code_agent/settings?workspace=${encodeURIComponent(workspace)}`
      : '/code_agent/settings';
    const response = await api.get<SettingsResponse>(url);
    return unwrap(response as SettingsResponse | ApiResponse<SettingsResponse>);
  },

  patchSettings: async (
    level: 'user' | 'project',
    patch: CodeAgentSettingsPatch,
    workspace: string | null,
  ): Promise<SettingsResponse> => {
    const response = await api.patch<SettingsResponse>('/code_agent/settings', {
      level,
      patch,
      workspace,
    });
    return unwrap(response as SettingsResponse | ApiResponse<SettingsResponse>);
  },

  resetProject: async (workspace: string): Promise<{ ok: boolean }> => {
    const response = await api.post<{ ok: boolean }>('/code_agent/settings/reset', {
      level: 'project',
      workspace,
    });
    return unwrap(response as { ok: boolean } | ApiResponse<{ ok: boolean }>);
  },
};
