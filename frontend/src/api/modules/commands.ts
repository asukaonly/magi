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
};

export default commandsApi;
