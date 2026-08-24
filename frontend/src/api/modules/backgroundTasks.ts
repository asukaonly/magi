import { api, unwrapGatewayPayload } from '../client';

/** Lifecycle status for a single background task. */
export type BackgroundTaskStatus =
  | 'pending'
  | 'running'
  | 'cancelling'
  | 'cancelled'
  | 'succeeded'
  | 'failed';

/** Which upstream signal caused a task to be spawned in the background. */
export type BackgroundTaskTriggerSource =
  | 'planner'
  | 'rule'
  | 'classifier'
  | 'user'
  | 'manual'
  | 'schedule';

export interface BackgroundTaskSpecDTO {
  user_id: string;
  session_id: string;
  origin_turn_id: string;
  title: string;
  goal: string;
  selected_tools: string[];
  workspace_path: string | null;
  trigger_source: BackgroundTaskTriggerSource;
  priority: number;
  max_iterations: number;
  timeout_seconds: number | null;
}

export interface BackgroundTaskDTO {
  task_id: string;
  status: BackgroundTaskStatus;
  attempt_index: number;
  spec: BackgroundTaskSpecDTO;
  user_task_id: string | null;
  summary: string | null;
  result_payload: Record<string, unknown>;
  error: string | null;
  cancel_reason: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  updated_at: number;
}

export interface BackgroundTaskEventDTO {
  event_id: string;
  task_id: string;
  attempt_index: number;
  event_type: string;
  from_status: BackgroundTaskStatus | null;
  to_status: BackgroundTaskStatus | null;
  message: string | null;
  payload: Record<string, unknown>;
  created_at: number;
}

export interface ListBackgroundTasksResponse {
  tasks: BackgroundTaskDTO[];
  active_count: number;
  total: number;
}

export interface GetBackgroundTaskResponse {
  task: BackgroundTaskDTO;
  events: BackgroundTaskEventDTO[];
}

export interface CancelBackgroundTaskResponse {
  task: BackgroundTaskDTO | null;
}

export interface RetryBackgroundTaskResponse {
  task: BackgroundTaskDTO;
}

export interface DismissBackgroundTaskResponse {
  deleted: boolean;
  task_id: string;
}

export interface ListBackgroundTasksParams {
  userId?: string;
  sessionId?: string;
  statuses?: BackgroundTaskStatus[];
  limit?: number;
  offset?: number;
}

/** Typed REST client for `/api/background-tasks`. */
export const backgroundTasksApi = {
  async list(params: ListBackgroundTasksParams = {}): Promise<ListBackgroundTasksResponse> {
    const search = new URLSearchParams();
    if (params.userId) search.set('user_id', params.userId);
    if (params.sessionId) search.set('session_id', params.sessionId);
    if (params.statuses) {
      for (const status of params.statuses) {
        search.append('status', status);
      }
    }
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    if (params.offset !== undefined) search.set('offset', String(params.offset));
    const query = search.toString();
    const response = await api.get<ListBackgroundTasksResponse>(
      `/background-tasks${query ? `?${query}` : ''}`,
    );
    return unwrapGatewayPayload(response);
  },

  async get(taskId: string): Promise<GetBackgroundTaskResponse> {
    const response = await api.get<GetBackgroundTaskResponse>(
      `/background-tasks/${encodeURIComponent(taskId)}`,
    );
    return unwrapGatewayPayload(response);
  },

  async cancel(taskId: string, reason?: string): Promise<CancelBackgroundTaskResponse> {
    const response = await api.post<CancelBackgroundTaskResponse>(
      `/background-tasks/${encodeURIComponent(taskId)}/cancel`,
      reason ? { reason } : {},
    );
    return unwrapGatewayPayload(response);
  },

  async retry(taskId: string): Promise<RetryBackgroundTaskResponse> {
    const response = await api.post<RetryBackgroundTaskResponse>(
      `/background-tasks/${encodeURIComponent(taskId)}/retry`,
    );
    return unwrapGatewayPayload(response);
  },

  async dismiss(taskId: string): Promise<DismissBackgroundTaskResponse> {
    const response = await api.post<DismissBackgroundTaskResponse>(
      `/background-tasks/${encodeURIComponent(taskId)}/dismiss`,
    );
    return unwrapGatewayPayload(response);
  },
};
