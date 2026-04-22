/**
 * Control-plane API (permission gateway, plan mode, todo tracker,
 * ask_user_question) client bindings.
 *
 * Backend routes live under ``/api/control``; see
 * ``backend/src/magi/api/routers/control.py`` for the source of truth.
 */
import { api } from '../client';

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type PermissionMode =
  | 'default'
  | 'accept_edits'
  | 'plan'
  | 'bypass_permissions';

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
  const res = await api.get<ControlSettingsDTO>('/api/control/settings');
  return res.data as ControlSettingsDTO;
}

export async function updateControlSettings(
  payload: Partial<ControlSettingsDTO>,
): Promise<ControlSettingsDTO> {
  const res = await api.put<ControlSettingsDTO>(
    '/api/control/settings',
    payload,
  );
  return res.data as ControlSettingsDTO;
}

export async function getSessionSettings(
  sessionId: string,
): Promise<SessionSettingsBundleDTO> {
  const res = await api.get<SessionSettingsBundleDTO>(
    `/api/control/sessions/${encodeURIComponent(sessionId)}/settings`,
  );
  return res.data as SessionSettingsBundleDTO;
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
    `/api/control/sessions/${encodeURIComponent(sessionId)}/settings`,
    payload,
  );
  return res.data as SessionSettingsBundleDTO;
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
    '/api/control/rules',
    {
      params: {
        session_id: params?.sessionId ?? undefined,
        include_persistent: params?.includePersistent ?? true,
      },
    },
  );
  return (res.data as { rules: PermissionRuleDTO[] }).rules;
}

export async function deletePermissionRule(
  ruleId: string,
  sessionId?: string | null,
): Promise<void> {
  await api.delete(`/api/control/rules/${encodeURIComponent(ruleId)}`, {
    params: { session_id: sessionId ?? undefined },
  });
}

export async function clearSessionPermissionRules(
  sessionId: string,
): Promise<void> {
  await api.delete('/api/control/rules', {
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
  /** Canonical runtime turn id. */
  turn_id?: string | null;
  /** @deprecated Legacy alias of {@link turn_id}. */
  task_id: string | null;
  agent_id: string | null;
  origin: string | null;
  tool: string;
  tool_args: Record<string, unknown>;
  risk_level: string;
  preview: Record<string, unknown> | null;
  created_at_ms: number;
}

export async function listPendingPermissions(
  sessionId: string,
): Promise<PendingPermissionDTO[]> {
  const res = await api.get<{ items: PendingPermissionDTO[] }>(
    `/api/control/sessions/${encodeURIComponent(sessionId)}/permissions`,
  );
  return (res.data as { items: PendingPermissionDTO[] }).items;
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
    `/api/control/permission/${encodeURIComponent(requestId)}/respond`,
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
}

export async function getAskState(
  sessionId: string,
): Promise<AskStateDTO | null> {
  const res = await api.get<{ ask: AskStateDTO | null }>(
    `/api/control/sessions/${encodeURIComponent(sessionId)}/ask`,
  );
  return (res.data as { ask: AskStateDTO | null }).ask;
}

export async function respondAsk(
  requestId: string,
  answer: string,
): Promise<void> {
  await api.post(
    `/api/control/ask/${encodeURIComponent(requestId)}/respond`,
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
    `/api/control/sessions/${encodeURIComponent(sessionId)}/plan`,
  );
  return res.data as PlanStateDTO;
}

export type TodoStatus = 'not_started' | 'in_progress' | 'completed';

export interface TodoItemDTO {
  id: string;
  content: string;
  status: TodoStatus;
  created_at_ms: number;
  updated_at_ms: number;
}

export async function getTodos(sessionId: string): Promise<TodoItemDTO[]> {
  const res = await api.get<{ items: TodoItemDTO[] }>(
    `/api/control/sessions/${encodeURIComponent(sessionId)}/todos`,
  );
  return (res.data as { items: TodoItemDTO[] }).items;
}
