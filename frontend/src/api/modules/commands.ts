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
  kind?: 'client' | 'control' | 'tool' | 'skill';
  execution_owner?: 'client' | 'command_runner' | 'agent_run' | 'background_driver';
  description: string;
  description_key?: string | null;
  category: string;
  visibility?: string;
  dangerous: boolean;
  parameters: CommandParameter[];
  context_mode?: 'inline' | 'fork' | null;
  reasoning_preference?: 'auto' | 'fast' | 'deep' | null;
  argument_hint?: string | null;
  tags?: string[];
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
  description_key?: string | null;
  kind?: 'skill';
  execution_owner?: 'agent_run' | 'background_driver';
  category?: string | null;
  dangerous?: false;
  parameters?: CommandParameter[];
  visibility?: string;
  context_mode?: 'inline' | 'fork' | null;
  argument_hint?: string | null;
  tags: string[];
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
  pending_message_id: string;
}

export default commandsApi;
