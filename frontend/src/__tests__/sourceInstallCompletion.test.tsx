import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { pluginsApi, type PluginRegistryEntry } from '@/api/modules/plugins';
import { parsePluginPackage } from '@/api/plugin-contract';
import { PluginMarketplace } from '@/components/settings/PluginMarketplace';
import { useChatShellStore } from '@/stores/chat-shell';
import { planFor } from './fixtures/pluginInstallPlan';
import examples from '../../../contracts/api/frontend-plugins-examples.json';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
const entry = (id: string, update = false): PluginRegistryEntry => ({
  ...planFor(id).changes[0].entry, installed: update, installed_version: update ? '1.0.0' : null,
  update_available: update, contribution_types: ['source'],
});

beforeEach(() => {
  vi.restoreAllMocks();
  useChatShellStore.setState({ activePanel: 'settings', settingsNavigationIntent: null });
  vi.spyOn(pluginsApi, 'getInstallPlan').mockImplementation(async (id, update) => {
    const plan = planFor(id, update);
    plan.changes[0].entry.contribution_types = ['source'];
    return plan;
  });
  vi.spyOn(pluginsApi, 'installFromRegistryWithProgress').mockResolvedValue(parsePluginPackage(examples.package));
  vi.spyOn(pluginsApi, 'updatePluginWithProgress').mockResolvedValue(parsePluginPackage(examples.package));
  vi.spyOn(pluginsApi, 'createConnection');
  vi.spyOn(pluginsApi, 'updateConnection');
});

async function installSource() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'settings.marketplace.actions.install' }));
  await user.click(await screen.findByRole('button', { name: 'settings.marketplace.plan.confirm' }));
  return user;
}

it.each(['configure', 'later'])('offers optional setup after installation: %s', async (choice) => {
  vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
    registry_version: '4', install_fingerprint: 'registry', plugins: [entry('netease-music')],
  });
  const configure = vi.fn();
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<PluginMarketplace installedPlugins={[]} onInstallComplete={refresh} onConfigureSource={configure} />);
  const user = await installSource();
  const dialog = await screen.findByTestId('source-install-complete-dialog');
  expect(dialog).toHaveTextContent('netease-music');
  expect(refresh).toHaveBeenCalledOnce();
  expect(configure).not.toHaveBeenCalled();
  await user.click(within(dialog).getByRole('button', { name: `settings.marketplace.sourceSetup.${choice}` }));
  if (choice === 'configure') expect(configure).toHaveBeenCalledExactlyOnceWith('netease-music');
  else expect(configure).not.toHaveBeenCalled();
  expect(screen.queryByTestId('source-install-complete-dialog')).not.toBeInTheDocument();
  expect(pluginsApi.createConnection).not.toHaveBeenCalled();
  expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
});

it('does not prompt for setup when updating an existing source', async () => {
  vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
    registry_version: '4', install_fingerprint: 'registry', plugins: [entry('netease-music', true)],
  });
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<PluginMarketplace installedPlugins={[]} onInstallComplete={refresh} onConfigureSource={vi.fn()} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: /settings.marketplace.actions.update/ }));
  await user.click(await screen.findByRole('button', { name: 'settings.marketplace.plan.confirmUpdate' }));
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  expect(screen.queryByTestId('source-install-complete-dialog')).not.toBeInTheDocument();
});

it('does not report success or offer setup after a failed install', async () => {
  vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
    registry_version: '4', install_fingerprint: 'registry', plugins: [entry('netease-music')],
  });
  vi.mocked(pluginsApi.installFromRegistryWithProgress).mockRejectedValue(new Error('Download failed'));
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<PluginMarketplace installedPlugins={[]} onInstallComplete={refresh} onConfigureSource={vi.fn()} />);
  await installSource();
  await waitFor(() => expect(pluginsApi.installFromRegistryWithProgress).toHaveBeenCalledOnce());
  expect(refresh).not.toHaveBeenCalled();
  expect(screen.queryByTestId('source-install-complete-dialog')).not.toBeInTheDocument();
});

it('offers each source once after a grouped installation finishes', async () => {
  const group = { id: 'photo_library', name: 'Photos', name_i18n: {}, description: '', description_i18n: {}, icon: '', order: 1, member_order: 1, member_label: '', member_label_i18n: {} };
  vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
    registry_version: '4', install_fingerprint: 'registry',
    plugins: ['apple-photos', 'photo-folder'].map((id) => ({ ...entry(id), display_group: group })),
  });
  const configure = vi.fn();
  render(<PluginMarketplace installedPlugins={[]} onInstallComplete={vi.fn().mockResolvedValue(undefined)} onConfigureSource={configure} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'settings.marketplace.actions.chooseEntries' }));
  for (const id of ['apple-photos', 'photo-folder']) await user.click(screen.getByTestId(`marketplace-entry-checkbox-${id}`));
  await user.click(screen.getByRole('button', { name: 'settings.marketplace.entryPicker.confirm' }));
  await user.click(await screen.findByRole('button', { name: 'settings.marketplace.plan.confirm' }));
  await screen.findByRole('region', { name: 'photo-folder' });
  expect(screen.queryByTestId('source-install-complete-dialog')).not.toBeInTheDocument();
  await user.click(await screen.findByRole('button', { name: 'settings.marketplace.plan.confirm' }));
  const dialog = await screen.findByTestId('source-install-complete-dialog');
  expect(within(dialog).getAllByRole('listitem')).toHaveLength(2);
  await user.click(within(within(dialog).getAllByRole('listitem')[1]).getByRole('button'));
  expect(configure).toHaveBeenCalledExactlyOnceWith('photo-folder');
});
