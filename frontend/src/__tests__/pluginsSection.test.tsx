import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { pluginsApi, type PluginPackageState } from '@/api/modules/plugins';
import PluginsSection from '@/components/settings/PluginsSection';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && typeof options.defaultValue === 'string' ? options.defaultValue : key,
  }),
}));

const pluginPackage = (pluginId: string, name: string): PluginPackageState => ({
  manifest: {
        protocol_version: 2 as const, min_sdk_version: '0.2.0', execution_mode: 'restricted_process' as const, settings_fields: [], settings_actions: [], settings_resources: [], settings_ui_blocks: [],
    plugin_id: pluginId,
    name,
    version: '1.0.0',
    description: `${name} package`,
    author: 'Magi Team',
    official: true,
    contribution_types: ['source'],
    source: 'external',
    plugin_dir: `/tmp/${pluginId}`,
    manifest_path: `/tmp/${pluginId}/plugin.toml`,
    capabilities: [],
    display_group: pluginId.includes('history')
      ? {
        id: 'browser_history',
        name: 'Browser History',
        name_i18n: { 'zh-CN': '浏览器历史' },
        description: 'Manage browser history sources from installed browser plugins.',
        description_i18n: { 'zh-CN': '统一管理浏览器历史入口。' },
        icon: 'lucide:globe',
        order: 10,
        member_label: name.replace(/\s*History$/i, ''),
        member_label_i18n: { 'zh-CN': name.replace(/\s*History$/i, '') },
        member_order: pluginId.startsWith('chrome') ? 10 : pluginId.startsWith('safari') ? 20 : 50,
      }
      : undefined,
  },
  enabled: true,
  trusted: true,
  loaded: true,
  healthy: true,
  last_error: null,
  current_settings: {},
  contributions: [
    {
      plugin_id: pluginId,
      contribution_id: `timeline.${pluginId}`,
      contribution_type: 'source',
      display_name: name,
      description: `${name} timeline entry`,
      surface: 'timeline',
      fields: [],
      metadata: {
        capability_id: pluginId.includes('history') ? 'browser_history' : pluginId,
        entry_id: pluginId.replace('-history', ''),
      },
    },
  ],
});

beforeEach(() => vi.spyOn(pluginsApi, 'listConnections').mockResolvedValue([]));
afterEach(() => vi.restoreAllMocks());

describe('PluginsSection', () => {
  it('retains builtin display and reload without a package settings editor', async () => {
    const user = userEvent.setup();
    const builtin = pluginPackage('core-tools', 'Core Tools');
    builtin.manifest.source = 'builtin';
    const reload = vi.fn();
    render(<PluginsSection plugins={[builtin]} onRescan={vi.fn()} onPluginAction={reload} processingIds={{}} />);
    expect(screen.getByTestId('installed-plugin-core-tools')).toHaveTextContent('Core Tools');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'plugins.connections.add' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'settings.pluginPackages.actions.reload' }));
    expect(reload).toHaveBeenCalledWith('core-tools', 'reload');
    expect(pluginsApi.listConnections).not.toHaveBeenCalled();
  });

  it('loads external accounts through the connection panel', async () => {
    render(<PluginsSection plugins={[pluginPackage('calendar', 'Calendar')]} onRescan={vi.fn()} onPluginAction={vi.fn()} processingIds={{}} />);
    await waitFor(() => expect(pluginsApi.listConnections).toHaveBeenCalledWith('calendar'));
    expect(screen.getByRole('button', { name: 'plugins.connections.add' })).toBeInTheDocument();
  });

  it('groups browser implementations under one installed plugin card', () => {
    render(
      <PluginsSection
        plugins={[
          pluginPackage('chrome-history', 'Chrome History'),
          pluginPackage('safari-history', 'Safari History'),
          pluginPackage('brave-history', 'Brave History'),
          pluginPackage('photo-library', 'Photo Library'),
        ]}
        onRescan={vi.fn()}
        onPluginAction={vi.fn()}
        processingIds={{}}
      />
    );

    expect(screen.getByTestId('installed-plugin-browser-history')).toHaveTextContent('浏览器历史');
    expect(screen.getByTestId('installed-plugin-browser-history')).toHaveTextContent('Chrome');
    expect(screen.getByTestId('installed-plugin-browser-history')).toHaveTextContent('Safari');
    expect(screen.getByTestId('installed-plugin-browser-history')).toHaveTextContent('Brave');
    expect(screen.queryByTestId('installed-plugin-chrome-history')).not.toBeInTheDocument();
    expect(screen.queryByTestId('installed-plugin-safari-history')).not.toBeInTheDocument();
    expect(screen.queryByTestId('installed-plugin-brave-history')).not.toBeInTheDocument();
    expect(screen.getByTestId('installed-plugin-photo-library')).toHaveTextContent('Photo Library');
  });
});

it('reviews exact package execution access without enabling a connection', async () => {
  const user = userEvent.setup();
  const pkg = { ...pluginPackage('local-source', 'Local source'), trusted: false, package_sha256: 'a'.repeat(64) };
  pkg.manifest.execution_mode = 'trusted_process';
  const authorize = vi.spyOn(pluginsApi, 'authorizePackage').mockResolvedValue({ ...pkg, trusted: true });
  const enable = vi.spyOn(pluginsApi, 'updateConnection');
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<PluginsSection plugins={[pkg]} onRescan={refresh} onPluginAction={vi.fn()} processingIds={{}} />);
  await user.click(screen.getByRole('button', { name: 'plugins.trust.review' }));
  expect(screen.getByText('plugins.trust.nativeAccess')).toBeVisible();
  expect(authorize).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'plugins.trust.confirm' }));
  await waitFor(() => expect(authorize).toHaveBeenCalledWith('local-source', 'a'.repeat(64)));
  expect(refresh).toHaveBeenCalledOnce();
  expect(enable).not.toHaveBeenCalled();
});
