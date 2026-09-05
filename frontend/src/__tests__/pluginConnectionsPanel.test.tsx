import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  listConnections: vi.fn(), createConnection: vi.fn(), updateConnection: vi.fn(),
  clearConnectionContent: vi.fn(), disconnectConnection: vi.fn(),
}));
vi.mock('@/api/modules/plugins', () => ({ pluginsApi: mocks }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { PluginConnectionsPanel } from '@/components/plugins/PluginConnectionsPanel';
import type { ExtensionFieldSpec, PluginConnection } from '@/api/modules/plugins';

const connection = (id: string, displayName: string): PluginConnection => ({
  connection_id: id, plugin_id: 'example', display_name: displayName, enabled: false,
  settings: { directory: `/${displayName}` }, credential_refs: { token: 'opaque-ref' }, revision: 4,
  readiness: [{ capability_id: 'source', connection_id: id, status: 'disabled' }],
});
const fields: ExtensionFieldSpec[] = [
  { key: 'directory', type: 'input', label: 'Directory', description: '', required: true, options: [], section: 'general', surface: 'extensions', order: 1 },
  { key: 'token', type: 'secret', label: 'Token', description: '', required: false, options: [], section: 'general', surface: 'extensions', order: 2 },
];

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listConnections.mockResolvedValue([connection('work', 'Work'), connection('home', 'Home')]);
  mocks.createConnection.mockResolvedValue(connection('new', 'New'));
  mocks.updateConnection.mockResolvedValue({ ...connection('home', 'Home'), revision: 5 });
  mocks.disconnectConnection.mockResolvedValue(undefined);
  mocks.clearConnectionContent.mockResolvedValue(connection('home', 'Home'));
});

describe('PluginConnectionsPanel', () => {
  it('edits the selected instance with its revision and write-only credentials', async () => {
    const user = userEvent.setup();
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    const row = (await screen.findByText('Home')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'plugins.connections.edit' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText(/Directory/)).toHaveValue('/Home');
    expect(within(dialog).getByLabelText('Token')).toHaveValue('');
    await user.clear(within(dialog).getByLabelText(/Directory/));
    await user.type(within(dialog).getByLabelText(/Directory/), '/personal');
    await user.type(within(dialog).getByLabelText('Token'), 'new-secret');
    await user.click(within(dialog).getByRole('button', { name: 'plugins.connections.save' }));
    await waitFor(() => expect(mocks.updateConnection).toHaveBeenCalledWith('example', 'home', {
      expected_revision: 4, display_name: 'Home', settings: { directory: '/personal' }, credentials: { token: 'new-secret' },
    }));
  });

  it('creates a disabled explicit connection without reusing a package identifier', async () => {
    const user = userEvent.setup();
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    await screen.findByText('Work');
    await user.click(screen.getByRole('button', { name: 'plugins.connections.add' }));
    const dialog = screen.getByRole('dialog');
    await user.type(within(dialog).getByLabelText('plugins.connections.name'), 'Personal');
    await user.type(within(dialog).getByLabelText(/Directory/), '/personal');
    await user.click(within(dialog).getByRole('button', { name: 'plugins.connections.save' }));
    expect(mocks.createConnection).toHaveBeenCalledWith('example', {
      display_name: 'Personal', settings: { directory: '/personal' }, credentials: {}, enabled: false,
    });
  });

  it('preserves a conflicted draft until an explicit reload', async () => {
    const user = userEvent.setup();
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    const row = (await screen.findByText('Home')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'plugins.connections.edit' }));
    const dialog = screen.getByRole('dialog');
    await user.clear(within(dialog).getByLabelText(/Directory/));
    await user.type(within(dialog).getByLabelText(/Directory/), '/draft');
    mocks.updateConnection.mockRejectedValueOnce({ response: { status: 409 } });
    mocks.listConnections.mockResolvedValueOnce([{ ...connection('home', 'Home'), revision: 5, settings: { directory: '/saved' } }]);
    await user.click(within(dialog).getByRole('button', { name: 'plugins.connections.save' }));
    await screen.findByText('plugins.connections.conflict');
    expect(within(dialog).getByLabelText(/Directory/)).toHaveValue('/draft');
    expect(within(dialog).getByRole('button', { name: 'plugins.connections.save' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'plugins.connections.reloadEditor' }));
    expect(within(dialog).getByLabelText(/Directory/)).toHaveValue('/saved');
  });

  it('confirms disconnect scope and submits only the chosen connection revision', async () => {
    const user = userEvent.setup();
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    const row = (await screen.findByText('Home')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'plugins.connections.disconnect' }));
    expect(mocks.disconnectConnection).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('plugins.connections.disconnectScope')).toBeVisible();
    await user.click(within(dialog).getByRole('button', { name: 'plugins.connections.disconnect' }));
    expect(mocks.disconnectConnection).toHaveBeenCalledWith('example', 'home', 4);
  });

  it('disables an enabled connection when removing a required credential', async () => {
    const user = userEvent.setup();
    mocks.listConnections.mockResolvedValueOnce([{ ...connection('home', 'Home'), enabled: true,
      readiness: [{ capability_id: 'source', connection_id: 'home', status: 'ready' }] }]);
    render(<PluginConnectionsPanel pluginId="example" fields={fields.map((field) => field.type === 'secret' ? { ...field, required: true } : field)} canEnable />);
    const row = (await screen.findByText('Home')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'plugins.connections.edit' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'plugins.connections.removeCredential' }));
    expect(within(dialog).getByText('plugins.connections.removalDisables')).toBeVisible();
    await user.click(within(dialog).getByRole('button', { name: 'plugins.connections.save' }));
    expect(mocks.updateConnection).toHaveBeenCalledWith('example', 'home', {
      display_name: 'Home', settings: { directory: '/Home' }, credentials: { token: null },
      expected_revision: 4, enabled: false,
    });
  });

  it('blocks enabling until the package is authorized', async () => {
    render(<PluginConnectionsPanel pluginId="example" fields={fields} />);
    await screen.findByText('Home');
    expect(screen.getAllByRole('button', { name: 'plugins.connections.enable' }).every((button) => button.hasAttribute('disabled'))).toBe(true);
  });

  it('requires explicit selection before rendering account-specific content', async () => {
    const user = userEvent.setup();
    const selected = vi.fn();
    render(<PluginConnectionsPanel pluginId="example" fields={fields} onSelectConnection={selected}
      renderConnection={(item) => <p>{`Status for ${item.display_name}`}</p>} />);
    await screen.findByText('Home');
    expect(screen.queryByText('Status for Work')).not.toBeInTheDocument();
    const row = screen.getByText('Home').closest('li')!;
    await user.click(within(row).getByRole('radio'));
    expect(selected).toHaveBeenCalledWith('home');
    expect(screen.getByText('Status for Home')).toBeVisible();
    expect(screen.queryByText('Status for Work')).not.toBeInTheDocument();
  });

  it('refreshes after errors instead of retaining an apparently healthy list', async () => {
    mocks.listConnections.mockRejectedValueOnce(new Error('Unavailable'));
    const user = userEvent.setup();
    render(<PluginConnectionsPanel pluginId="example" fields={fields} />);
    await screen.findByRole('alert');
    expect(screen.queryByText('Home')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'plugins.connections.refresh' }));
    expect(await screen.findByText('Home')).toBeVisible();
  });
});
