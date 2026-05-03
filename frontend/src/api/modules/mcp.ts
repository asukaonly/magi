import { api } from '../client';
import type { ApiResponse } from '../client';

export type MCPTransportKind = 'stdio' | 'http';

export interface MCPStdioTransport {
  kind: 'stdio';
  command: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
}

export interface MCPHttpTransport {
  kind: 'http';
  url: string;
  headers: Record<string, string>;
}

export type MCPTransport = MCPStdioTransport | MCPHttpTransport;

export interface MCPRuntime {
  call_timeout_ms: number;
  init_timeout_ms: number;
  max_restart_attempts: number;
}

export type MCPServerState =
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'disabled'
  | 'error';

export interface MCPServerStatus {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  autostart: boolean;
  transport: MCPTransport;
  runtime: MCPRuntime;
  state: MCPServerState;
  tool_count: number;
  resource_count: number;
  last_error: string | null;
}

export interface MCPServerCreatePayload {
  server: {
    id: string;
    name: string;
    description?: string;
    enabled?: boolean;
    autostart?: boolean;
  };
  transport: MCPTransport;
  runtime?: Partial<MCPRuntime>;
  tool_overrides?: Record<string, { dangerous?: boolean | null }>;
}

export interface MCPResource {
  server_id: string;
  uri: string;
  name?: string;
  description?: string;
  mimeType?: string;
  [key: string]: unknown;
}

export interface MCPServerLogs {
  server_id: string;
  stderr: string[];
  last_error: string | null;
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

export const mcpApi = {
  listServers: async (): Promise<MCPServerStatus[]> => {
    const response = await api.get<{ data: MCPServerStatus[] }>('/mcp/servers');
    const body = unwrap(response as { data: MCPServerStatus[] } | ApiResponse<{ data: MCPServerStatus[] }>);
    return body?.data ?? [];
  },

  createServer: async (payload: MCPServerCreatePayload): Promise<MCPServerStatus> => {
    const response = await api.post<MCPServerStatus>('/mcp/servers', payload);
    return unwrap(response as MCPServerStatus | ApiResponse<MCPServerStatus>);
  },

  updateServer: async (
    serverId: string,
    payload: MCPServerCreatePayload,
  ): Promise<MCPServerStatus> => {
    const response = await api.patch<MCPServerStatus>(`/mcp/servers/${serverId}`, payload);
    return unwrap(response as MCPServerStatus | ApiResponse<MCPServerStatus>);
  },

  deleteServer: async (serverId: string): Promise<void> => {
    await api.delete(`/mcp/servers/${serverId}`);
  },

  startServer: async (serverId: string): Promise<MCPServerStatus> => {
    const response = await api.post<MCPServerStatus>(`/mcp/servers/${serverId}/start`, {});
    return unwrap(response as MCPServerStatus | ApiResponse<MCPServerStatus>);
  },

  stopServer: async (serverId: string): Promise<MCPServerStatus> => {
    const response = await api.post<MCPServerStatus>(`/mcp/servers/${serverId}/stop`, {});
    return unwrap(response as MCPServerStatus | ApiResponse<MCPServerStatus>);
  },

  serverLogs: async (serverId: string): Promise<MCPServerLogs> => {
    const response = await api.get<MCPServerLogs>(`/mcp/servers/${serverId}/logs`);
    return unwrap(response as MCPServerLogs | ApiResponse<MCPServerLogs>);
  },

  listResources: async (): Promise<MCPResource[]> => {
    const response = await api.get<{ data: MCPResource[] }>('/mcp/resources');
    const body = unwrap(response as { data: MCPResource[] } | ApiResponse<{ data: MCPResource[] }>);
    return body?.data ?? [];
  },

  readResource: async (serverId: string, uri: string): Promise<unknown> => {
    const response = await api.post<unknown>('/mcp/resources/read', {
      server_id: serverId,
      uri,
    });
    return unwrap(response as unknown | ApiResponse<unknown>);
  },
};

export default mcpApi;
