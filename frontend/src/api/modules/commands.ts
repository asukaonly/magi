import { api } from '../client';
import type { ApiResponse } from '../client';

export type CommandParameterType =
  | 'string'
  | 'integer'
  | 'float'
  | 'boolean'
  | 'array'
  | 'object';

export interface CommandParameter {
  name: string;
  type: CommandParameterType;
  description?: string;
  required?: boolean;
  default?: unknown;
  enum?: unknown[];
  array_item_type?: CommandParameterType;
}

export interface CommandDescriptor {
  name: string;
  description: string;
  category: string;
  dangerous: boolean;
  parameters: CommandParameter[];
}

export interface RunCommandRequest {
  user_id?: string;
  session_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  invocation_text: string;
  workspace_path?: string | null;
}

export interface RunCommandResponse {
  success: boolean;
  message_id: string;
  invocation_message_id: string;
  output: string;
  error: string | null;
  error_code: string | null;
  execution_time_ms: number;
}

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

export const commandsApi = {
  list: async (): Promise<CommandDescriptor[]> => {
    const response = await api.get<{ data: CommandDescriptor[] }>('/commands/');
    const body = unwrap(response as { data: CommandDescriptor[] } | ApiResponse<{ data: CommandDescriptor[] }>);
    return body?.data ?? [];
  },

  run: async (request: RunCommandRequest): Promise<RunCommandResponse> => {
    const response = await api.post<RunCommandResponse>('/commands/run', request);
    return unwrap(response as RunCommandResponse | ApiResponse<RunCommandResponse>);
  },

  listSkills: async (): Promise<SkillCommandDescriptor[]> => {
    const response = await api.get<{ data: SkillCommandDescriptor[] }>(
      '/commands/skills',
    );
    const body = unwrap(
      response as { data: SkillCommandDescriptor[] } | ApiResponse<{ data: SkillCommandDescriptor[] }>,
    );
    return body?.data ?? [];
  },

  expandSkill: async (request: ExpandSkillRequest): Promise<ExpandSkillResponse> => {
    const response = await api.post<ExpandSkillResponse>(
      '/commands/expand-skill',
      request,
    );
    return unwrap(response as ExpandSkillResponse | ApiResponse<ExpandSkillResponse>);
  },

  runSkillAsBackground: async (
    request: RunSkillAsBackgroundRequest,
  ): Promise<RunSkillAsBackgroundResponse> => {
    const response = await api.post<RunSkillAsBackgroundResponse>(
      '/commands/run-skill-as-background',
      request,
    );
    return unwrap(
      response as RunSkillAsBackgroundResponse | ApiResponse<RunSkillAsBackgroundResponse>,
    );
  },
};

export interface SkillCommandDescriptor {
  name: string;
  description: string;
  argument_hint?: string | null;
  category?: string | null;
  tags: string[];
  context_mode?: string | null;
}

export interface ExpandSkillRequest {
  user_id?: string;
  session_id: string;
  skill_name: string;
  arguments?: string[];
  workspace_path?: string | null;
}

export interface ExpandSkillResponse {
  name: string;
  rendered_prompt: string;
  invocation_text: string;
  description: string;
  argument_hint?: string | null;
  allowed_tools?: string[] | null;
  context_mode?: string | null;
}

export interface RunSkillAsBackgroundRequest {
  user_id?: string;
  session_id: string;
  skill_name: string;
  arguments?: string[];
  workspace_path?: string | null;
  origin_turn_id?: string | null;
  timeout_seconds?: number | null;
  max_iterations?: number;
}

export interface RunSkillAsBackgroundResponse {
  task_id: string;
  title: string;
  invocation_text: string;
  selected_tools: string[];
}

export default commandsApi;
