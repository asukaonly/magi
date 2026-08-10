import { api } from '../client';
import type { ApiResponse } from '../client';
import { isSensitiveLogField, registerKnownLogSecrets } from '@/runtime/log-redaction';

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

export interface MCPToolSelection {
  include: string[] | null;
}

export interface MCPAvailableTool {
  name: string;
  description: string;
  enabled: boolean;
  available: boolean;
}

export type MCPToolRisk = 'low' | 'medium' | 'high' | 'destructive';

export interface MCPToolOverride {
  dangerous?: boolean | null;
  risk?: MCPToolRisk | null;
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
  tools: MCPToolSelection;
  available_tools: MCPAvailableTool[];
  tool_overrides: Record<string, MCPToolOverride>;
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
  tools?: MCPToolSelection;
  tool_overrides?: Record<string, MCPToolOverride>;
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

const MCP_SECRET_PLACEHOLDERS = new Set(['', '***', '[REDACTED]']);

const addMcpSecret = (values: string[], rawValue: unknown, force = false): void => {
  const value = String(rawValue ?? '').trim();
  if (MCP_SECRET_PLACEHOLDERS.has(value) || (!force && value.length < 6)) return;
  values.push(value);

  const authMatch = /^(?:bearer|basic)\s+(.+)$/i.exec(value);
  if (authMatch?.[1]) values.push(authMatch[1]);
  if (value.includes(';') && value.includes('=')) {
    value.split(';').forEach((item) => {
      const separator = item.indexOf('=');
      if (separator >= 0) addMcpSecret(values, item.slice(separator + 1), true);
    });
  }
};

const registerMcpLogSecrets = (transport: MCPTransport): void => {
  const values: string[] = [];
  const entries = transport.kind === 'http'
    ? Object.entries(transport.headers)
    : Object.entries(transport.env);
  entries.forEach(([name, value]) => {
    addMcpSecret(values, value, isSensitiveLogField(name));
  });

  if (transport.kind === 'http') {
    try {
      const parsed = new URL(transport.url);
      addMcpSecret(values, decodeURIComponent(parsed.username), true);
      addMcpSecret(values, decodeURIComponent(parsed.password), true);
      parsed.searchParams.forEach((value, name) => {
        if (isSensitiveLogField(name)) addMcpSecret(values, value, true);
      });
    } catch {
      // Invalid URLs are rejected by the backend; other values remain protected.
    }
  }

  if (transport.kind === 'stdio') {
    transport.args.forEach((argument, index) => {
      const [option, inlineValue] = argument.split('=', 2);
      const normalizedOption = option.replace(/^[-/]+/, '');
      const candidate = inlineValue || transport.args[index + 1] || '';
      if (['H', 'header'].includes(normalizedOption)) {
        const separator = candidate.indexOf(':');
        if (separator >= 0) {
          const headerName = candidate.slice(0, separator);
          addMcpSecret(
            values,
            candidate.slice(separator + 1),
            isSensitiveLogField(headerName),
          );
        }
      } else if (['e', 'env'].includes(normalizedOption)) {
        const separator = candidate.indexOf('=');
        if (separator >= 0) {
          const envName = candidate.slice(0, separator);
          addMcpSecret(
            values,
            candidate.slice(separator + 1),
            isSensitiveLogField(envName),
          );
        }
      } else if (isSensitiveLogField(normalizedOption)) {
        addMcpSecret(values, candidate, true);
      }
    });
  }
  registerKnownLogSecrets({ credentials: values });
};

export const mcpApi = {
  listServers: async (): Promise<MCPServerStatus[]> => {
    const response = await api.get<{ data: MCPServerStatus[] }>('/mcp/servers');
    const body = unwrap(response as { data: MCPServerStatus[] } | ApiResponse<{ data: MCPServerStatus[] }>);
    const servers = body?.data ?? [];
    servers.forEach((server) => registerMcpLogSecrets(server.transport));
    return servers;
  },

  createServer: async (payload: MCPServerCreatePayload): Promise<MCPServerStatus> => {
    registerMcpLogSecrets(payload.transport);
    const response = await api.post<MCPServerStatus>('/mcp/servers', payload);
    return unwrap(response as MCPServerStatus | ApiResponse<MCPServerStatus>);
  },

  updateServer: async (
    serverId: string,
    payload: MCPServerCreatePayload,
  ): Promise<MCPServerStatus> => {
    registerMcpLogSecrets(payload.transport);
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
