import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('react-i18next', async () => {
  const actual: any = await vi.importActual('react-i18next');
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, opts?: any) => {
        if (opts && typeof opts === 'object') {
          return `${key} ${JSON.stringify(opts)}`;
        }
        return key;
      },
    }),
  };
});

import { api } from '@/api/client';
import { mcpApi } from '@/api/modules/mcp';
import { MCPServersSection } from '@/components/settings/MCPServersSection';
import { redactLogText } from '@/runtime/log-redaction';

afterEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
  vi.mocked(api.delete).mockReset();
});

describe('MCPServersSection', () => {
  it('registers arbitrary MCP header and environment values for log redaction', async () => {
    vi.mocked(api.post).mockResolvedValue({} as any);
    vi.mocked(api.patch).mockResolvedValue({} as any);

    await mcpApi.createServer({
      server: { id: 'http-demo', name: 'HTTP Demo' },
      transport: {
        kind: 'http',
        url: 'https://user:url-password-secret@example.test/mcp?signature=query-secret-value',
        headers: { 'X-Company-Header': 'custom-header-secret' },
      },
    });
    await mcpApi.updateServer('stdio-demo', {
      server: { id: 'stdio-demo', name: 'Stdio Demo' },
      transport: {
        kind: 'stdio',
        command: 'demo',
        args: [],
        cwd: '',
        env: { UNUSUAL_SETTING: 'custom-env-secret' },
      },
    });

    expect(redactLogText(
      'custom-header-secret custom-env-secret url-password-secret query-secret-value',
    )).toBe(
      '[REDACTED] [REDACTED] [REDACTED] [REDACTED]',
    );
  });

  it('ignores masked placeholders returned by the server list', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: [{
        id: 'http-demo',
        name: 'HTTP Demo',
        description: '',
        enabled: true,
        autostart: false,
        transport: {
          kind: 'http',
          url: 'https://example.test/mcp',
          headers: { Authorization: '***' },
        },
        runtime: { call_timeout_ms: 60000, init_timeout_ms: 15000, max_restart_attempts: 5 },
        state: 'disconnected',
        tool_count: 0,
        resource_count: 0,
        last_error: null,
      }],
    } as any);

    await mcpApi.listServers();

    expect(redactLogText('placeholder *** remains readable')).toBe(
      'placeholder *** remains readable',
    );
  });

  it('renders an empty state when the list is empty', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any);
    render(<MCPServersSection />);
    await waitFor(() => {
      expect(screen.getByText('settings.mcp.empty')).toBeTruthy();
    });
    expect(api.get).toHaveBeenCalledWith('/mcp/servers');
  });

  it('lists servers with status badge', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: [
        {
          id: 'demo',
          name: 'Demo',
          description: '',
          enabled: true,
          autostart: true,
          transport: { kind: 'stdio', command: 'npx', args: [], cwd: '', env: {} },
          runtime: { call_timeout_ms: 60000, init_timeout_ms: 15000, max_restart_attempts: 5 },
          state: 'connected',
          tool_count: 3,
          resource_count: 2,
          last_error: null,
        },
      ],
    } as any);
    render(<MCPServersSection />);
    await waitFor(() => {
      expect(screen.getByText('Demo')).toBeTruthy();
    });
    expect(screen.getByText('settings.mcp.state.connected')).toBeTruthy();
  });

  it('calls start endpoint when start button clicked', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: 'demo',
          name: 'Demo',
          description: '',
          enabled: true,
          autostart: false,
          transport: { kind: 'stdio', command: 'npx', args: [], cwd: '', env: {} },
          runtime: { call_timeout_ms: 60000, init_timeout_ms: 15000, max_restart_attempts: 5 },
          state: 'disconnected',
          tool_count: 0,
          resource_count: 0,
          last_error: null,
        },
      ],
    } as any);
    vi.mocked(api.post).mockResolvedValueOnce({} as any);
    render(<MCPServersSection />);
    const startButton = await screen.findByRole('button', { name: /settings\.mcp\.actions\.start/ });
    fireEvent.click(startButton);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/mcp/servers/demo/start', {});
    });
  });

  it('exposes a kebab "More actions" menu on each row', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: 'demo',
          name: 'Demo',
          description: '',
          enabled: true,
          autostart: false,
          transport: { kind: 'stdio', command: 'npx', args: [], cwd: '', env: {} },
          runtime: { call_timeout_ms: 60000, init_timeout_ms: 15000, max_restart_attempts: 5 },
          state: 'connected',
          tool_count: 0,
          resource_count: 0,
          last_error: null,
        },
      ],
    } as any);
    render(<MCPServersSection />);
    await screen.findByText('Demo');
    const moreBtn = screen.getByRole('button', { name: /settings\.mcp\.actions\.more/ });
    expect(moreBtn).toBeTruthy();
  });

  it('shows an Import button that triggers a file picker', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] } as any);
    render(<MCPServersSection />);
    const importBtn = await screen.findByRole('button', {
      name: /settings\.mcp\.actions\.import/,
    });
    expect(importBtn).toBeTruthy();
  });
});
