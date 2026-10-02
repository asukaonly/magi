import { renderWithConnectionSettings as render } from './helpers/connectionSettings';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ listConnections: vi.fn(), getConnection: vi.fn(), createConnection: vi.fn(), updateConnection: vi.fn(), clearConnectionContent: vi.fn(), disconnectConnection: vi.fn() }));
vi.mock('@/api/modules/plugins', () => ({ pluginsApi: mocks }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
import { APP_EVENTS } from '@/constants/events';
import { PluginConnectionsPanel } from '@/components/plugins/PluginConnectionsPanel';
import type { ExtensionFieldSpec, PluginConnection } from '@/api/modules/plugins';
const connection = (id = 'home', displayName = 'Home'): PluginConnection => ({
  connection_id: id, plugin_id: 'example', display_name: displayName, enabled: false,
  settings: { directory: `/${displayName}` }, credential_refs: { token: 'opaque-ref' }, revision: 4,
  readiness: [{ capability_id: 'source', connection_id: id, status: 'disabled' }],
});
const fields: ExtensionFieldSpec[] = [
  { key: 'directory', type: 'input', label: 'Directory', description: '', required: true, options: [], section: 'general', surface: 'extensions', order: 1 },
  { key: 'token', type: 'secret', label: 'Token', description: '', required: false, options: [], section: 'general', surface: 'extensions', order: 2 },
];
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.clearAllMocks();
  mocks.listConnections.mockResolvedValue([connection()]);
  mocks.getConnection.mockResolvedValue(connection());
  mocks.createConnection.mockResolvedValue(connection('new', 'New'));
  mocks.updateConnection.mockImplementation(async (_plugin, _id, input) => ({ ...connection(), ...input, revision: 5 }));
  mocks.disconnectConnection.mockResolvedValue(undefined);
  mocks.clearConnectionContent.mockResolvedValue(connection());
});
afterEach(() => vi.unstubAllGlobals());
const startSetup = async (customFields = fields) => {
  mocks.listConnections.mockResolvedValue([]);
  render(<PluginConnectionsPanel pluginId="example" fields={customFields} canEnable />);
  await userEvent.click(await screen.findByRole('button', { name: 'plugins.connections.connect' }));
  return within(screen.getByRole('dialog'));
};
describe('PluginConnectionsPanel', () => {
  it('blocks invalid numeric setup and permits correction', async () => {
    const dialog = await startSetup([{ ...fields[0], key: 'count', label: 'Count', type: 'number', default: 5 }]);
    const input = dialog.getByRole('spinbutton');
    await userEvent.clear(input);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(dialog.getByRole('button', { name: 'plugins.connections.continue' })).toBeDisabled();
    fireEvent.submit(input.closest('form')!);
    expect(mocks.createConnection).not.toHaveBeenCalled();
    await userEvent.type(input, '8');
    await userEvent.click(dialog.getByRole('button', { name: 'plugins.connections.continue' }));
    expect(mocks.createConnection).toHaveBeenCalledWith('example', expect.objectContaining({ settings: { count: 8 } }));
  });
  it('allows disabled setup to omit required fields and null defaults', async () => {
    const dialog = await startSetup([{ ...fields[0], type: 'number', default: null }]);
    expect(dialog.queryByRole('alert')).not.toBeInTheDocument();
    await userEvent.click(dialog.getByRole('button', { name: 'plugins.connections.continue' }));
    expect(mocks.createConnection).toHaveBeenCalledWith('example', expect.objectContaining({ enabled: false, settings: {} }));
  });
  it('preserves concrete false and zero defaults', async () => {
    const dialog = await startSetup([
      { ...fields[0], key: 'count', label: 'Count', type: 'number', default: 0 },
      { ...fields[0], key: 'active', label: 'Active', type: 'switch', default: false },
    ]);
    await userEvent.click(dialog.getByRole('button', { name: 'plugins.connections.continue' }));
    expect(mocks.createConnection).toHaveBeenCalledWith('example', expect.objectContaining({ settings: { count: 0, active: false } }));
  });
  it('uses one footer save and write-only credentials for the sole connection', async () => {
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    const directory = await screen.findByLabelText(/Directory/);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Token')).toHaveValue('');
    expect(screen.queryByRole('button', { name: 'plugins.connections.save' })).not.toBeInTheDocument();
    await userEvent.clear(directory); await userEvent.type(directory, '/personal');
    await userEvent.type(screen.getByLabelText('Token'), 'new-secret');
    expect(mocks.updateConnection).not.toHaveBeenCalled();
    expect(screen.getByText('Unsaved changes')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(mocks.updateConnection).toHaveBeenCalledWith('example', 'home', {
      expected_revision: 4, settings: { directory: '/personal' }, credentials: { token: 'new-secret' },
    }));
  });
  it('blocks required enabled values at global save', async () => {
    mocks.listConnections.mockResolvedValue([{ ...connection(), enabled: true }]);
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    await userEvent.clear(await screen.findByLabelText(/Directory/));
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(mocks.updateConnection).not.toHaveBeenCalled();
    expect((await screen.findAllByRole('alert')).some(node => node.textContent?.includes('settings.dynamicValidation.fieldInvalid'))).toBe(true);
  });
  it('preserves local edits on refresh and requires explicit conflict reload', async () => {
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    const directory = await screen.findByLabelText(/Directory/);
    await userEvent.clear(directory); await userEvent.type(directory, '/local-draft');
    mocks.listConnections.mockResolvedValue([{ ...connection(), revision: 5, settings: { directory: '/remote' } }]);
    act(() => window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED)));
    await screen.findByRole('button', { name: 'plugins.connections.reloadEditor' }, { timeout: 3000 });
    expect(directory).toHaveValue('/local-draft');
    await userEvent.click(screen.getByRole('button', { name: 'plugins.connections.reloadEditor' }));
    await waitFor(() => expect(directory).toHaveValue('/remote'));
    expect(mocks.updateConnection).not.toHaveBeenCalled();
  });
  it('stages enablement and discards it through the footer', async () => {
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    await userEvent.click(await screen.findByRole('switch'));
    expect(screen.getByRole('switch')).toBeChecked();
    expect(mocks.updateConnection).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(screen.getByRole('switch')).not.toBeChecked();
  });
  it('confirms disconnect scope and revision', async () => {
    render(<PluginConnectionsPanel pluginId="example" fields={fields} canEnable />);
    await userEvent.click(await screen.findByText('plugins.connections.manage'));
    await userEvent.click(screen.getByRole('button', { name: 'plugins.connections.disconnect' }));
    expect(mocks.disconnectConnection).not.toHaveBeenCalled();
    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.getByText('plugins.connections.disconnectScope')).toBeVisible();
    await userEvent.click(dialog.getByRole('button', { name: 'plugins.connections.disconnect' }));
    expect(mocks.disconnectConnection).toHaveBeenCalledWith('example', 'home', 4);
  });
  it('disables the connection when removing a required credential', async () => {
    mocks.listConnections.mockResolvedValue([{ ...connection(), enabled: true }]);
    mocks.getConnection.mockResolvedValue({ ...connection(), enabled: true });
    render(<PluginConnectionsPanel pluginId="example" fields={fields.map(field => field.type === 'secret' ? { ...field, required: true } : field)} canEnable />);
    await userEvent.click(await screen.findByRole('button', { name: 'plugins.connections.removeCredential' }));
    expect(screen.getByText('plugins.connections.removalDisables')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(mocks.updateConnection).toHaveBeenCalledWith('example', 'home', {
      settings: { directory: '/Home' }, credentials: { token: null }, expected_revision: 4, enabled: false,
    }));
  });
  it('requires trust before enabling or setting up', async () => {
    render(<PluginConnectionsPanel pluginId="example" fields={fields} />);
    expect(await screen.findByRole('switch')).toBeDisabled();
  });
  it('requires selection for multiple accounts and keeps their drafts separate', async () => {
    mocks.listConnections.mockResolvedValue([connection('work', 'Work'), connection()]);
    const selected = vi.fn();
    render(<PluginConnectionsPanel pluginId="example" fields={fields} onSelectConnection={selected} renderConnection={item => <p>Status for {item.display_name}</p>} />);
    const select = await screen.findByRole('combobox');
    expect(screen.queryByLabelText(/Directory/)).not.toBeInTheDocument();
    await userEvent.selectOptions(select, 'home');
    expect(selected).toHaveBeenCalledWith('home');
    expect(screen.getByText('Status for Home')).toBeVisible();
    await userEvent.clear(screen.getByLabelText(/Directory/)); await userEvent.type(screen.getByLabelText(/Directory/), '/draft');
    await userEvent.selectOptions(select, 'work');
    expect(screen.getByLabelText(/Directory/)).toHaveValue('/Work');
    await userEvent.selectOptions(select, 'home');
    expect(screen.getByLabelText(/Directory/)).toHaveValue('/draft');
  });
  it('shows retry only after a load failure', async () => {
    mocks.listConnections.mockRejectedValueOnce(new Error('Unavailable'));
    render(<PluginConnectionsPanel pluginId="example" fields={fields} />);
    await userEvent.click(await screen.findByRole('button', { name: 'plugins.connections.retry' }));
    expect(await screen.findByLabelText(/Directory/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'plugins.connections.retry' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'plugins.connections.refresh' })).not.toBeInTheDocument();
  });
  it('discloses advanced settings without hiding privacy controls or exposing internal fields', async () => {
    render(<PluginConnectionsPanel pluginId="example" fields={[
      { ...fields[0], key: 'excluded', label: 'Excluded sites', section: 'privacy' },
      { ...fields[0], key: 'limit', label: 'Batch limit', section: 'advanced_settings' },
      { ...fields[0], key: 'internal', label: 'Internal flag', section: 'advanced' },
      { ...fields[0], key: 'capture', label: 'Capture scope', section: 'capture' },
      { ...fields[1], key: 'webhook_secret', label: 'Webhook secret', section: 'advanced_settings' },
    ]} />);
    expect(await screen.findByLabelText(/Excluded sites/)).toBeVisible();
    expect(screen.getByLabelText(/Batch limit/)).not.toBeVisible();
    expect(screen.getByLabelText('Webhook secret')).not.toBeVisible();
    expect(screen.getByLabelText(/Capture scope/).compareDocumentPosition(screen.getByText('settings.pluginSections.advanced_settings')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByLabelText(/Internal flag/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('settings.pluginSections.advanced_settings'));
    expect(screen.getByLabelText(/Batch limit/)).toBeVisible();
    expect(screen.getByLabelText('Webhook secret')).toBeVisible();
  });
});
