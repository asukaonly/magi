import { api, unwrapGatewayPayload } from '../client';

export type ScheduleTargetType =
  | 'source_sync'
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
  owner_kind?: 'source_settings' | 'system' | 'user' | string;
  settings_link?: ScheduleSettingsLinkDTO | null;
  target_state?: ScheduleTargetStateDTO | null;
}

export interface ListSchedulesResponse {
  schedules: ScheduleDTO[];
}

export type ScheduleActivityStatus =
  | 'running'
  | 'queued'
  | 'upcoming'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | string;

export interface ScheduleActivityDTO {
  activity_id: string;
  schedule_id: string;
  title?: string | null;
  target_type: ScheduleTargetType;
  target_key: string;
  status: ScheduleActivityStatus;
  planned_at?: number | null;
  started_at?: number | null;
  finished_at?: number | null;
  duration_ms?: number | null;
  cancellable: boolean;
  cancel_kind?: 'source_sync_job' | string | null;
  error?: string | null;
  background_task_id?: string | null;
  result_message?: string | null;
  stats?: Record<string, unknown>;
  manual?: boolean;
}

export interface ListScheduleActivityResponse {
  activities: ScheduleActivityDTO[];
  total?: number;
  /**
   * Counts of all activity rows in the requested time window, grouped by
   * raw `target_type`. Independent of any category/status filter applied —
   * intended for driving filter-chip counters that need to remain stable
   * when the user clicks a chip.
   */
  target_type_counts?: Record<string, number>;
  /**
   * Counts of all activity rows in the requested time window, grouped by
   * display status (succeeded / failed / running / queued / cancelled).
   * Same semantics as `target_type_counts`.
   */
  status_counts?: Record<string, number>;
}

export interface ListActivityParams {
  sinceSeconds?: number;
  untilSeconds?: number;
  limit?: number;
  offset?: number;
  targetTypes?: string[];
  statuses?: string[];
}

export interface CreateScheduleRequest {
  schedule_id: string;
  display_name: string;
  prompt: string;
  trigger: ScheduleTriggerDTO;
  enabled: boolean;
}

export interface CreateScheduleResponse {
  schedule: ScheduleDTO;
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

  async listActivity(params: ListActivityParams = {}): Promise<ListScheduleActivityResponse> {
    const search = new URLSearchParams();
    if (params.sinceSeconds !== undefined) search.set('since', String(params.sinceSeconds));
    if (params.untilSeconds !== undefined) search.set('until', String(params.untilSeconds));
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    if (params.offset !== undefined) search.set('offset', String(params.offset));
    (params.targetTypes ?? []).forEach((t) => search.append('target_types', t));
    (params.statuses ?? []).forEach((s) => search.append('statuses', s));
    const query = search.toString();
    const response = await api.get<ListScheduleActivityResponse>(
      `/schedules/activity${query ? `?${query}` : ''}`,
    );
    return unwrapGatewayPayload(response);
  },

  async create(body: CreateScheduleRequest): Promise<CreateScheduleResponse> {
    const wireBody = {
      schedule_id: body.schedule_id,
      target_type: 'user_agent_task' as const,
      target_key: body.schedule_id,
      trigger: body.trigger,
      target_payload: { prompt: body.prompt, kind: 'agent_task' },
      metadata: { display_name: body.display_name, target_kind: 'agent_task' },
      enabled: body.enabled,
    };
    const response = await api.post<CreateScheduleResponse>('/schedules', wireBody);
    return unwrapGatewayPayload(response);
  },

  async update(scheduleId: string, body: UpdateScheduleRequest): Promise<UpdateScheduleResponse> {
    const response = await api.patch<UpdateScheduleResponse>(
      `/schedules/${encodeURIComponent(scheduleId)}`,
      body,
    );
    return unwrapGatewayPayload(response);
  },

  async remove(scheduleId: string): Promise<void> {
    await api.delete(`/schedules/${encodeURIComponent(scheduleId)}`);
  },

  /**
   * Manually trigger a schedule. ``overrideParams``, when provided, is
   * shallow-merged on top of the schedule's stored target_payload for this
   * single execution (the DB row is not mutated). Handlers opt in by
   * reading ``context.schedule.target_payload``.
   *
   * Example: ``run("timeline_diary_narrative", { days: 7 })`` to backfill
   * 7 days of diary narratives in one trigger.
   */
  async run(
    scheduleId: string,
    overrideParams?: Record<string, unknown>,
  ): Promise<RunScheduleResponse> {
    const response = await api.post<RunScheduleResponse>(
      `/schedules/${encodeURIComponent(scheduleId)}/run`,
      overrideParams && Object.keys(overrideParams).length > 0
        ? { override_params: overrideParams }
        : undefined,
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

