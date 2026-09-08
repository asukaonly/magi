import type { components as EventComponents } from '../generated/events-types';
/**
 * REST client for /api/code_agent endpoints.
 *
 * Backend returns plain JSON objects (no {success,data} wrapper). The
 * defensive ``unwrap`` matches how MCPApi handles both shapes.
 */
import { api } from '../client';
import type { ApiResponse } from '../client';
import type { components as ConfigComponents } from '../generated/config-types';
import { validateCodeAgentSettingsResponse, validateCodeAgentProbeResponse } from '../generated/config-validators';
import { ApiContractError } from '../config-contract';
import { parseDelegationResponse } from '../code-agent-contract';

type ConfigWire = ConfigComponents['schemas'];
export type CodeAgentSettings = ConfigWire['CodeAgentSettings'];
export type AdapterName = ConfigWire['ProbeResult']['name'];
export type DefaultAdapterName = CodeAgentSettings['default_adapter'];
export type ProbeResult = ConfigWire['ProbeResult'];
export type ConstraintsSettings = CodeAgentSettings['constraints'];
export type ClaudeCodeSettings = CodeAgentSettings['claude_code'];
export type CodexSettings = CodeAgentSettings['codex'];
export type ProbeResponse = ConfigWire['CodeAgentProbeResponse'];
export type SettingsResponse = ConfigWire['CodeAgentSettingsResponse'];

function readSettings(value: unknown): SettingsResponse {
  if (!validateCodeAgentSettingsResponse(value)) throw new ApiContractError('code tool settings');
  return value;
}
function readProbe(value: unknown): ProbeResponse {
  if (!validateCodeAgentProbeResponse(value)
    || value.results.claude_code.name !== 'claude_code'
    || value.results.codex.name !== 'codex') throw new ApiContractError('code tool probe');
  return value;
}

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends unknown[] ? T[K] : T[K] extends object ? DeepPartial<T[K]> : T[K];
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
    const response = await api.get<unknown>(
      `/code_agent/probe${force ? '?force=true' : ''}`,
    );
    return readProbe(response);
  },

  rescan: async (): Promise<ProbeResponse> => {
    const response = await api.post<unknown>('/code_agent/rescan', {});
    return readProbe(response);
  },

  getSettings: async (workspace: string | null): Promise<SettingsResponse> => {
    const url = workspace
      ? `/code_agent/settings?workspace=${encodeURIComponent(workspace)}`
      : '/code_agent/settings';
    const response = await api.get<unknown>(url);
    return readSettings(response);
  },

  patchSettings: async (
    level: 'user' | 'project',
    patch: CodeAgentSettingsPatch,
    workspace: string | null,
    expectedRevision: string,
  ): Promise<SettingsResponse> => {
    const response = await api.patch<unknown>('/code_agent/settings', {
      level,
      patch,
      workspace,
      expected_revision: expectedRevision,
    });
    return readSettings(response);
  },

  resetProject: async (workspace: string, expectedRevision: string): Promise<SettingsResponse> => {
    const response = await api.post<unknown>('/code_agent/settings/reset', {
      level: 'project',
      workspace,
      expected_revision: expectedRevision,
    });
    return readSettings(response);
  },

  getDelegation: async (
    sessionId: string,
    delegationId: string,
    workspace: string,
  ): Promise<DelegationFetchResponse> => {
    const response = await api.get<unknown>(
      `/code_agent/delegations/${encodeURIComponent(sessionId)}/${encodeURIComponent(delegationId)}?workspace=${encodeURIComponent(workspace)}`,
    );
    return parseDelegationResponse(response, delegationId);
  },

  cancelDelegation: async (
    sessionId: string,
    delegationId: string,
    workspace: string,
  ): Promise<{ ok: boolean }> => {
    const response = await api.post<{ ok: boolean }>(
      `/code_agent/delegations/${encodeURIComponent(sessionId)}/${encodeURIComponent(delegationId)}/cancel`,
      { workspace },
    );
    return unwrap(response as { ok: boolean } | ApiResponse<{ ok: boolean }>);
  },

  applyDelegation: async (
    sessionId: string,
    delegationId: string,
    workspace: string,
  ): Promise<{ outcome: ApplyOutcome }> => {
    const response = await api.post<{ outcome: ApplyOutcome }>(
      `/code_agent/delegations/${encodeURIComponent(sessionId)}/${encodeURIComponent(delegationId)}/apply`,
      { workspace },
    );
    return unwrap(response as { outcome: ApplyOutcome } | ApiResponse<{ outcome: ApplyOutcome }>);
  },

  discardDelegation: async (
    sessionId: string,
    delegationId: string,
    workspace: string,
  ): Promise<{ ok: boolean }> => {
    const response = await api.post<{ ok: boolean }>(
      `/code_agent/delegations/${encodeURIComponent(sessionId)}/${encodeURIComponent(delegationId)}/discard`,
      { workspace },
    );
    return unwrap(response as { ok: boolean } | ApiResponse<{ ok: boolean }>);
  },
};


// ===========================================================================
// Delegation runtime contracts
// ===========================================================================

export type DelegationLifecycle =
  | 'started'
  | 'running'
  | 'finished'
  | 'failed'
  | 'cancelled'
  | 'discarded'
  | 'applied';

export type RunEvent = EventComponents['schemas']['RunEvent'];
export type RunEventKind = RunEvent['kind'];

export type DiffStats = EventComponents['schemas']['DiffStats'];
export type CostInfo = EventComponents['schemas']['CostInfo'];
export type DelegateResult = EventComponents['schemas']['DelegateResult'] & { discarded_at?: number };

export interface DelegationFetchResponse {
  result: DelegateResult | null;
  events_tail: RunEvent[];
  diff_text: string;
}

export interface ApplyOutcome {
  applied: boolean;
  files_applied: string[];
  rejects: string[];
  error: string | null;
}

export interface DelegationStateBroadcast {
  user_id: string;
  session_id: string;
  turn_id: string;
  delegation_id: string;
  state: DelegationLifecycle;
  summary: Record<string, unknown>;
}

export interface DelegationEventBroadcast {
  user_id: string;
  session_id: string;
  turn_id: string;
  delegation_id: string;
  event: RunEvent;
}
