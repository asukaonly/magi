import { api, unwrapGatewayPayload } from '../client';

export type ScheduleTargetType =
  | 'sensor_sync'
  | 'memory_l2_maintenance'
  | 'memory_l3_summary'
  | 'user_agent_task'
  | string;

export type ScheduleTriggerType = 'once' | 'interval' | 'cron';

export interface ScheduleTriggerDTO {
  trigger_type: ScheduleTriggerType;
  config: Record<string, unknown>;
}

export interface ScheduleTargetStateDTO {
  target_type: ScheduleTargetType;
  target_key: string;
  running: boolean;
  last_run_at?: number | null;
  last_success_at?: number | null;
  last_error?: string | null;
  last_cursor?: string | null;
  watermark_ts?: number | null;
  next_run_at?: number | null;
  scheduler_job_id?: string | null;
  updated_at?: number | null;
  stats?: Record<string, unknown>;
}

export interface ScheduleSettingsLinkDTO {
  section: 'timeline' | 'memory' | string;
  source_name?: string | null;
}

export interface ScheduleDTO {
  schedule_id: string;
  target_type: ScheduleTargetType;
  target_key: string;
  trigger: ScheduleTriggerDTO;
  target_payload: Record<string, unknown>;
  enabled: boolean;
  metadata: Record<string, unknown>;
  job_id?: string | null;
  editable?: boolean;
  owner_kind?: 'sensor_settings' | 'system' | 'user' | string;
  settings_link?: ScheduleSettingsLinkDTO | null;
  target_state?: ScheduleTargetStateDTO | null;
}

export interface ListSchedulesResponse {
  schedules: ScheduleDTO[];
}

export type ScheduleActivityStatus = 'running' | 'queued' | 'upcoming' | 'cancelled' | string;

export interface ScheduleActivityDTO {
  activity_id: string;
  schedule_id: string;
  title?: string | null;
  target_type: ScheduleTargetType;
  target_key: string;
  status: ScheduleActivityStatus;
  planned_at?: number | null;
  started_at?: number | null;
  duration_ms?: number | null;
  cancellable: boolean;
  cancel_kind?: 'sensor_sync_job' | string | null;
  error?: string | null;
}

export interface ListScheduleActivityResponse {
  activities: ScheduleActivityDTO[];
}

export interface UpdateScheduleRequest {
  trigger?: ScheduleTriggerDTO;
  target_payload?: Record<string, unknown>;
  enabled?: boolean;
  metadata?: Record<string, unknown>;
}

export interface UpdateScheduleResponse {
  schedule: ScheduleDTO;
}

export interface ScheduledExecutionResultDTO {
  success: boolean;
  message?: string;
  next_cursor?: string | null;
  watermark_ts?: number | null;
  stats?: Record<string, unknown>;
}

export interface RunScheduleResponse {
  schedule: ScheduleDTO;
  result: ScheduledExecutionResultDTO;
}

export interface CancelScheduleActivityResponse {
  activity: {
    activity_id: string;
    status: string;
    job_id?: string;
  };
}

export const schedulesApi = {
  async list(params: { enabledOnly?: boolean } = {}): Promise<ListSchedulesResponse> {
    const search = new URLSearchParams();
    if (params.enabledOnly !== undefined) {
      search.set('enabled_only', String(params.enabledOnly));
    }
    const query = search.toString();
    const response = await api.get<ListSchedulesResponse>(`/schedules${query ? `?${query}` : ''}`);
    return unwrapGatewayPayload(response);
  },

  async listActivity(params: { limit?: number } = {}): Promise<ListScheduleActivityResponse> {
    const search = new URLSearchParams();
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    const query = search.toString();
    const response = await api.get<ListScheduleActivityResponse>(`/schedules/activity${query ? `?${query}` : ''}`);
    return unwrapGatewayPayload(response);
  },

  async update(scheduleId: string, body: UpdateScheduleRequest): Promise<UpdateScheduleResponse> {
    const response = await api.patch<UpdateScheduleResponse>(
      `/schedules/${encodeURIComponent(scheduleId)}`,
      body,
    );
    return unwrapGatewayPayload(response);
  },

  async run(scheduleId: string): Promise<RunScheduleResponse> {
    const response = await api.post<RunScheduleResponse>(
      `/schedules/${encodeURIComponent(scheduleId)}/run`,
    );
    return unwrapGatewayPayload(response);
  },

  async cancelActivity(activityId: string, reason?: string): Promise<CancelScheduleActivityResponse> {
    const response = await api.post<CancelScheduleActivityResponse>(
      `/schedules/activity/${encodeURIComponent(activityId)}/cancel`,
      reason ? { reason } : {},
    );
    return unwrapGatewayPayload(response);
  },
};

