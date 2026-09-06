import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ startSettingsAction: vi.fn(), pollSettingsAction: vi.fn(), cancelSettingsAction: vi.fn() }));
vi.mock('@/api/modules/plugins', () => ({ pluginsApi: api }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), warning: vi.fn(), info: vi.fn(), error: vi.fn() } }));

import { PluginSettingsActions } from '@/components/settings/PluginSettingsActions';
import type { PluginSettingsActionSpec } from '@/api/modules/plugins';

const action: PluginSettingsActionSpec = {
  action_id: 'connect', label: 'Connect account', description: '', button_label: 'Connect', presentation: 'inline',
  surface: 'extensions', contribution_id: 'channel', order: 0, destructive: false, requires_enabled: false,
  poll_interval_ms: 1000, timeout_ms: 1000, persist_settings_on_success: true,
};

beforeEach(() => vi.clearAllMocks());

it('uses only the explicit connection and prevents retries after uncertain effects', async () => {
  const user = userEvent.setup();
  api.startSettingsAction.mockResolvedValue({ connection_id: 'work', plugin_id: 'example', action_id: 'connect',
    session_id: 'run', status: 'uncertain', message: 'Check provider', data: {}, settings_updates: {} });
  render(<PluginSettingsActions pluginId="example" connectionId="work" actions={[action]} values={{ folder: 'Inbox' }} />);
  await user.click(screen.getByRole('button', { name: 'Connect' }));
  expect(api.startSettingsAction).toHaveBeenCalledWith('work', 'connect', { folder: 'Inbox' });
  expect(await screen.findByText('Check provider')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled();
  expect(api.pollSettingsAction).not.toHaveBeenCalled();
});

it('discards a previous account response after the connection changes', async () => {
  let finish!: (value: unknown) => void;
  api.startSettingsAction.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const user = userEvent.setup();
  const props = { pluginId: 'example', actions: [action], values: {} };
  const { rerender } = render(<PluginSettingsActions {...props} connectionId="work" />);
  await user.click(screen.getByRole('button', { name: 'Connect' }));
  rerender(<PluginSettingsActions {...props} connectionId="home" />);
  await act(async () => finish({ connection_id: 'work', plugin_id: 'example', action_id: 'connect', session_id: 'run',
    status: 'succeeded', message: 'Work account connected', data: {}, settings_updates: {} }));
  expect(screen.queryByText('Work account connected')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled();
});
