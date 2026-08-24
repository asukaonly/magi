/**
 * Control-plane API (permission gateway, plan mode, todo tracker,
 * ask_user_question) client bindings.
 *
 * Backend routes live under ``/api/control``; the shared axios client already
 * includes the ``/api`` prefix, so requests here stay relative to ``/control``.
 * See ``backend/src/magi/api/routers/control.py`` for the source of truth.
 */
import { api } from '../client';

function unwrapControlResponse<T>(response: T | { success?: boolean; data?: T }): T {
  if (
    response
    && typeof response === 'object'
    && 'success' in response
    && 'data' in response
    && (response as { data?: T }).data !== undefined
  ) {
    return (response as { data: T }).data;
  }
  if (
    response
    && typeof response === 'object'
    && 'data' in response
    && (response as { data?: T }).data !== undefined
  ) {
    return (response as { data: T }).data;
  }
  return response as T;
}

const asRecord = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' ? value as Record<string, unknown> : {}
);

const numberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

const stringOrNull = (value: unknown): string | null => {
  const text = String(value ?? '').trim();
  return text || null;
};

const secondsToMs = (value: unknown): number | null => {
  const numeric = numberOrNull(value);
  return numeric === null ? null : Math.round(numeric * 1000);
};

const deadlineFrom = (
  raw: Record<string, unknown>,
  createdAtMs: number | null,
): number | null => {
  const explicitMs = numberOrNull(raw.expires_at_ms);
  if (explicitMs !== null) return explicitMs;
  const explicitSeconds = secondsToMs(raw.expires_at);
  if (explicitSeconds !== null) return explicitSeconds;
  const timeoutSeconds = numberOrNull(raw.timeout_seconds);
  if (timeoutSeconds !== null && createdAtMs !== null) {
    return Math.round(createdAtMs + timeoutSeconds * 1000);
  }
  return null;
};

const createdAtFields = (raw: Record<string, unknown>): {
  created_at: number;
  created_at_ms: number;
} => {
  const createdAtMs = numberOrNull(raw.created_at_ms)
    ?? numberOrNull(raw.asked_at_ms)
    ?? secondsToMs(raw.created_at)
    ?? secondsToMs(raw.asked_at)
    ?? Date.now();
  const createdAt = numberOrNull(raw.created_at)
    ?? numberOrNull(raw.asked_at)
    ?? createdAtMs / 1000;
  return { created_at: createdAt, created_at_ms: createdAtMs };
};

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type PermissionMode =
  | 'all'
  | 'high_only'
  | 'off';

export type PermissionScope =
  | 'one_shot'
  | 'session'
  | 'persistent_exact'
  | 'persistent_pattern';

export type PermissionOutcome = 'allowed' | 'denied';

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface ControlSettingsDTO {
  permission_mode: PermissionMode;
  plan_approval_required: boolean;
}

export interface SessionControlOverrideDTO {
  permission_mode: PermissionMode | null;
  plan_approval_required: boolean | null;
}

export interface SessionSettingsBundleDTO {
  base: ControlSettingsDTO;
  override: SessionControlOverrideDTO | null;
  effective: ControlSettingsDTO;
}

export async function getControlSettings(): Promise<ControlSettingsDTO> {
  const res = await api.get<ControlSettingsDTO>('/control/settings');
  return unwrapControlResponse<ControlSettingsDTO>(res);
}

export async function updateControlSettings(
  payload: Partial<ControlSettingsDTO>,
): Promise<ControlSettingsDTO> {
  const res = await api.put<ControlSettingsDTO>(
    '/control/settings',
    payload,
  );
  return unwrapControlResponse<ControlSettingsDTO>(res);
}

export async function getSessionSettings(
  sessionId: string,
): Promise<SessionSettingsBundleDTO> {
  const res = await api.get<SessionSettingsBundleDTO>(
    `/control/sessions/${encodeURIComponent(sessionId)}/settings`,
  );
  return unwrapControlResponse<SessionSettingsBundleDTO>(res);
}

export interface SessionSettingsUpdateInput {
  permission_mode?: PermissionMode | null;
  plan_approval_required?: boolean | null;
  clear?: boolean;
}

export async function updateSessionSettings(
  sessionId: string,
  payload: SessionSettingsUpdateInput,
): Promise<SessionSettingsBundleDTO> {
  const res = await api.put<SessionSettingsBundleDTO>(
    `/control/sessions/${encodeURIComponent(sessionId)}/settings`,
    payload,
  );
  return unwrapControlResponse<SessionSettingsBundleDTO>(res);
}

// ---------------------------------------------------------------------------
// Permission rules
// ---------------------------------------------------------------------------

export interface PermissionRuleDTO {
  rule_id: string;
  tool: string;
  pattern: string | null;
  scope: PermissionScope;
  outcome: PermissionOutcome;
  session_id: string | null;
  reason: string | null;
  created_at_ms: number;
}

export async function listPermissionRules(params?: {
  sessionId?: string | null;
  includePersistent?: boolean;
}): Promise<PermissionRuleDTO[]> {
  const res = await api.get<{ rules: PermissionRuleDTO[] }>(
    '/control/rules',
    {
      params: {
        session_id: params?.sessionId ?? undefined,
        include_persistent: params?.includePersistent ?? true,
      },
    },
  );
  return unwrapControlResponse<{ rules: PermissionRuleDTO[] }>(res).rules;
}

export async function deletePermissionRule(
  ruleId: string,
  sessionId?: string | null,
): Promise<void> {
  await api.delete(`/control/rules/${encodeURIComponent(ruleId)}`, {
    params: { session_id: sessionId ?? undefined },
  });
}

export async function clearSessionPermissionRules(
  sessionId: string,
): Promise<void> {
  await api.delete('/control/rules', {
    params: { session_id: sessionId },
  });
}

// ---------------------------------------------------------------------------
// Pending permission prompts
// ---------------------------------------------------------------------------

export interface PendingPermissionDTO {
  request_id: string;
  session_id: string | null;
  user_id: string | null;
  turn_id: string | null;
  agent_id: string | null;
  origin: string | null;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: string;
  workspace: string | null;
  preview: string | null;
  signals: string[];
  created_at: number;
  created_at_ms: number;
  timeout_seconds: number | null;
  expires_at_ms: number | null;
}

function normalizePendingPermission(rawValue: unknown): PendingPermissionDTO {
  const raw = asRecord(rawValue);
  const created = createdAtFields(raw);
  const argumentsValue = asRecord(raw.arguments ?? raw.tool_args);
  return {
    ...raw,
    request_id: String(raw.request_id ?? ''),
    session_id: stringOrNull(raw.session_id),
    user_id: stringOrNull(raw.user_id),
    turn_id: stringOrNull(raw.turn_id),
    agent_id: stringOrNull(raw.agent_id),
    origin: stringOrNull(raw.origin),
    tool_name: String(raw.tool_name ?? raw.tool ?? ''),
    arguments: argumentsValue,
    risk_level: String(raw.risk_level ?? ''),
    workspace: stringOrNull(raw.workspace),
    preview: stringOrNull(raw.preview),
    signals: Array.isArray(raw.signals) ? raw.signals.map(String) : [],
    created_at: created.created_at,
    created_at_ms: created.created_at_ms,
    timeout_seconds: numberOrNull(raw.timeout_seconds),
    expires_at_ms: deadlineFrom(raw, created.created_at_ms),
  } as PendingPermissionDTO;
}

export async function listPendingPermissions(
  sessionId: string,
): Promise<PendingPermissionDTO[]> {
  const res = await api.get<{ items: PendingPermissionDTO[] }>(
    `/control/sessions/${encodeURIComponent(sessionId)}/permissions`,
  );
  return unwrapControlResponse<{ items: PendingPermissionDTO[] }>(res)
    .items
    .map(normalizePendingPermission);
}

export interface PermissionRespondInput {
  outcome: 'allow' | 'deny';
  scope?: PermissionScope;
  pattern?: string;
  reason?: string;
}

export async function respondPermission(
  requestId: string,
  payload: PermissionRespondInput,
): Promise<void> {
  await api.post(
    `/control/permission/${encodeURIComponent(requestId)}/respond`,
    payload,
  );
}

// ---------------------------------------------------------------------------
// Ask / plan / todos
// ---------------------------------------------------------------------------

export interface AskStateDTO {
  request_id: string;
  question: string;
  options: string[];
  allow_free_text: boolean;
  status: 'pending' | 'answered' | 'timeout' | 'cancelled';
  answer: string | null;
  created_at_ms: number;
  timeout_seconds: number | null;
  expires_at_ms: number | null;
}

function normalizeAskState(rawValue: unknown): AskStateDTO | null {
  if (!rawValue) return null;
  const raw = asRecord(rawValue);
  const created = createdAtFields(raw);
  const resolution = String(raw.resolution ?? '').trim().toLowerCase();
  const statusRaw = String(raw.status ?? '').trim().toLowerCase();
  const status = (
    statusRaw
    || (resolution === 'user' ? 'answered' : resolution)
    || 'pending'
  ) as AskStateDTO['status'];
  return {
    ...raw,
    request_id: String(raw.request_id ?? ''),
    question: String(raw.question ?? ''),
    options: Array.isArray(raw.options) ? raw.options.map(String) : [],
    allow_free_text: Boolean(raw.allow_free_text ?? true),
    status,
    answer: raw.answer === null || raw.answer === undefined ? null : String(raw.answer),
    created_at_ms: created.created_at_ms,
    timeout_seconds: numberOrNull(raw.timeout_seconds),
    expires_at_ms: deadlineFrom(raw, created.created_at_ms),
  } as AskStateDTO;
}

export async function getAskState(
  sessionId: string,
): Promise<AskStateDTO | null> {
  const res = await api.get<{ ask: AskStateDTO | null }>(
    `/control/sessions/${encodeURIComponent(sessionId)}/ask`,
  );
  return normalizeAskState(unwrapControlResponse<{ ask: AskStateDTO | null }>(res).ask);
}

export async function respondAsk(
  requestId: string,
  answer: string,
): Promise<void> {
  await api.post(
    `/control/ask/${encodeURIComponent(requestId)}/respond`,
    { answer },
  );
}

export interface PlanStateDTO {
  active: boolean;
  plan_text: string | null;
  entered_at_ms: number | null;
  exited_at_ms: number | null;
}

export async function getPlanState(sessionId: string): Promise<PlanStateDTO> {
  const res = await api.get<PlanStateDTO>(
    `/control/sessions/${encodeURIComponent(sessionId)}/plan`,
  );
  return unwrapControlResponse<PlanStateDTO>(res);
}
