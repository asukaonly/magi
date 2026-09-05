import { api } from '../client';
import { z } from 'zod';
import type { components } from '../generated/events-types';
import { validateBackgroundTask, validateBackgroundTaskEvent } from '../generated/events-validators';
import { parseBackgroundTask } from '../event-contract';

/** Lifecycle status for a single background task. */
export type BackgroundTaskStatus = components['schemas']['BackgroundTaskStatus'];

/** Which upstream signal caused a task to be spawned in the background. */
export type BackgroundTaskTriggerSource = components['schemas']['BackgroundTaskTriggerSource'];

/** Fields the task view consumes; the full wire record is checked at the API boundary. */
export type BackgroundTaskSpecDTO = Pick<components['schemas']['BackgroundTaskSpec'],
  'user_id' | 'session_id' | 'origin_turn_id' | 'title' | 'goal' | 'selected_tools' |
  'workspace_path' | 'trigger_source' | 'priority' | 'max_iterations' | 'timeout_seconds'>;
export type BackgroundTaskDTO = Omit<components['schemas']['BackgroundTask'], 'spec'> & { spec: BackgroundTaskSpecDTO };
export type BackgroundTaskEventDTO = components['schemas']['BackgroundTaskEvent'];

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

const taskSchema = z.custom<components['schemas']['BackgroundTask']>(validateBackgroundTask).transform(parseBackgroundTask);
const eventSchema = z.custom<components['schemas']['BackgroundTaskEvent']>(validateBackgroundTaskEvent);
const listTasksSchema = z.object({ tasks: z.array(taskSchema), active_count: z.number().int().nonnegative(), total: z.number().int().nonnegative() });
const getTaskSchema = z.object({ task: taskSchema, events: z.array(eventSchema) });

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
    const response = await api.get<unknown>(
      `/background-tasks${query ? `?${query}` : ''}`,
    );
    return listTasksSchema.parse(response);
  },

  async get(taskId: string): Promise<GetBackgroundTaskResponse> {
    const response = await api.get<unknown>(
      `/background-tasks/${encodeURIComponent(taskId)}`,
    );
    return getTaskSchema.parse(response);
  },

  async cancel(taskId: string, reason?: string): Promise<CancelBackgroundTaskResponse> {
    const response = await api.post<unknown>(
      `/background-tasks/${encodeURIComponent(taskId)}/cancel`,
      reason ? { reason } : {},
    );
    return z.object({ task: taskSchema.nullable() }).parse(response);
  },

  async retry(taskId: string): Promise<RetryBackgroundTaskResponse> {
    const response = await api.post<unknown>(
      `/background-tasks/${encodeURIComponent(taskId)}/retry`,
    );
    return z.object({ task: taskSchema }).parse(response);
  },

  async dismiss(taskId: string): Promise<DismissBackgroundTaskResponse> {
    const response = await api.post<unknown>(
      `/background-tasks/${encodeURIComponent(taskId)}/dismiss`,
    );
    return z.object({ deleted: z.boolean(), task_id: z.string() }).parse(response);
  },
};
