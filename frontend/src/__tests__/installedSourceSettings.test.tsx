import { renderWithConnectionSettings as render } from './helpers/connectionSettings';
import {  screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { pluginsApi, type PluginPackageState } from '@/api/modules/plugins';
import type { SourceStatusItem } from '@/api/modules/sources';
import { TimelineSourcesSection } from '@/components/settings/TimelineSourcesSection';
import { parsePluginPackage } from '@/api/plugin-contract';
import { buildTimelineCapabilities } from '@/utils/timeline-capabilities';
import examples from '../../../contracts/api/frontend-plugins-examples.json';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

const sourcePlugin = (id: string, groupId?: string): PluginPackageState => {
  const plugin = parsePluginPackage(examples.package);
  return { ...plugin, trusted: true, loaded: false, enabled: false, contributions: [], manifest: {
    ...plugin.manifest, plugin_id: id, name: id, contribution_types: ['source'],
    activation_flow: null, settings_fields: [], settings_actions: [], settings_ui_blocks: [],
    display_group: groupId ? { id: groupId, name: groupId, name_i18n: {}, description: '', description_i18n: {}, icon: '', order: 1, member_order: 1, member_label: id, member_label_i18n: {} } : null,
  } };
};
const activeSource: SourceStatusItem = {
  source_name: 'chrome_history', plugin_id: 'chrome-history', connection_id: 'chrome-personal',
  connection_display_name: 'Personal', connection_revision: 1, contribution_id: 'history',
  display_name: 'Chrome', description: '', capability_id: 'browser_history',
  capability_display_name: 'Browser history', fields: [], current_settings: {}, enabled: true,
  sync_mode: 'manual', sync_interval_minutes: 60, storage_mode: 'sqlite', fetch_page_content: false,
  edge_whitelist: [], supports_pull_sync: false, status: 'idle',
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(pluginsApi, 'listConnections').mockResolvedValue([]);
  vi.spyOn(pluginsApi, 'createConnection');
  vi.spyOn(pluginsApi, 'updateConnection');
});

it('combines installed packages with active sources without duplicating grouped entries', () => {
  const chrome = sourcePlugin('chrome-history', 'browser_history');
  const safari = sourcePlugin('safari-history', 'browser_history');
  const photos = sourcePlugin('apple-photos', 'photo_library');
  const tools = sourcePlugin('tools');
  tools.manifest.contribution_types = ['tool'];
  const groups = buildTimelineCapabilities((key) => key, [activeSource], [chrome, safari, photos, tools]);
  expect(groups).toHaveLength(2);
  expect(groups.find((group) => group.id === 'browser_history')).toMatchObject({
    enabledCount: 1, sources: [activeSource], pendingPlugins: [safari],
  });
  expect(groups.find((group) => group.id === 'photo_library')).toMatchObject({ sources: [], pendingPlugins: [photos] });
});

it('shows installed sources without connections and opens their setup without enabling them', async () => {
  const user = userEvent.setup();
  const plugins = [sourcePlugin('apple-photos', 'photo_library'), sourcePlugin('netease-music', 'listening_history')];
  const select = vi.fn();
  const props = { userMode: 'quick' as const, statuses: [], installedPlugins: plugins, loadingStatus: false,
    onSelectSource: select, onRefreshSources: vi.fn().mockResolvedValue(undefined) };
  const { rerender } = render(<TimelineSourcesSection {...props} selectedSourceName={null} />);
  const photos = screen.getByTestId('timeline-source-launch-photo_library');
  expect(photos).toHaveTextContent('settings.timeline.statuses.installedPending');
  expect(screen.getByTestId('timeline-source-launch-listening_history')).toBeInTheDocument();
  await user.click(photos);
  expect(select).toHaveBeenCalledWith('photo_library');
  rerender(<TimelineSourcesSection {...props} selectedSourceName="photo_library" />);
  const setup = await screen.findByTestId('source-connections-apple-photos');
  expect(await within(setup).findByText('plugins.connections.setupTitle')).toBeInTheDocument();
  await user.click(within(setup).getByRole('button', { name: 'plugins.connections.connect' }));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  expect(pluginsApi.createConnection).not.toHaveBeenCalled();
  expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
});

it('keeps an installed sibling configurable beside an active source', async () => {
  render(<TimelineSourcesSection userMode="quick" statuses={[activeSource]} loadingStatus={false}
    installedPlugins={[sourcePlugin('chrome-history', 'browser_history'), sourcePlugin('safari-history', 'browser_history')]}
    selectedSourceName="browser_history" onSelectSource={vi.fn()} onRefreshSources={vi.fn().mockResolvedValue(undefined)} />);
  expect(await screen.findByTestId('source-connections-safari-history')).toBeInTheDocument();
  expect(screen.getByTestId('timeline-source-detail-chrome_history')).toBeInTheDocument();
  expect(screen.queryByTestId('source-connections-chrome-history')).not.toBeInTheDocument();
});

it('opens the exact plugin from installation even when it belongs to a shared group', async () => {
  render(<TimelineSourcesSection userMode="quick" statuses={[]} loadingStatus={false}
    installedPlugins={[sourcePlugin('apple-photos', 'photo_library'), sourcePlugin('photo-folder', 'photo_library')]}
    selectedSourceName="plugin:apple-photos" onSelectSource={vi.fn()} onRefreshSources={vi.fn().mockResolvedValue(undefined)} />);
  expect(await screen.findByTestId('source-connections-apple-photos')).toBeInTheDocument();
  expect(screen.queryByTestId('source-connections-photo-folder')).not.toBeInTheDocument();
});
