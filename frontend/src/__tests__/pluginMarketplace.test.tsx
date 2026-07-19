import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { pluginsApi } from '@/api/modules/plugins';
import { PluginMarketplace } from '@/components/settings/PluginMarketplace';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

describe('PluginMarketplace', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  const browserDisplayGroup = (memberLabel: string, memberOrder: number) => ({
    id: 'browser_history',
    name: 'Browser History',
    name_i18n: { 'zh-CN': '浏览器历史' },
    description: 'Manage browser history sources from installed browser plugins.',
    description_i18n: { 'zh-CN': '统一管理浏览器历史入口。' },
    icon: 'lucide:globe',
    order: 10,
    member_label: memberLabel,
    member_label_i18n: { 'zh-CN': memberLabel },
    member_order: memberOrder,
  });

  it('shows registry-provided plugin icons on standalone marketplace cards', async () => {
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '1',
      plugins: [
        {
          plugin_id: 'photo-library',
          name: 'Photo Library',
          name_i18n: { 'zh-CN': '照片库' },
          version: '0.1.0',
          description: 'Read local photo libraries.',
          description_i18n: { 'zh-CN': '读取本地照片库。' },
          author: 'Magi Team',
          icon: 'custom:apple-photos',
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'photo-library',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
      ],
    });

    render(<PluginMarketplace installedPlugins={[]} onInstallComplete={vi.fn()} />);

    expect(await screen.findByText('照片库')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-icon-apple-photos')).toBeInTheDocument();
  });

  it('groups browser history implementations and lets users choose entries before installing', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '1',
      plugins: [
        {
          plugin_id: 'chrome-history',
          name: 'Chrome History',
          name_i18n: { 'zh-CN': 'Chrome 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Chrome browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Chrome 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:googlechrome',
          display_group: browserDisplayGroup('Chrome', 10),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'chrome-history',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
        {
          plugin_id: 'safari-history',
          name: 'Safari History',
          name_i18n: { 'zh-CN': 'Safari 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Safari browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Safari 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:safari',
          display_group: browserDisplayGroup('Safari', 20),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'safari-history',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
        {
          plugin_id: 'brave-history',
          name: 'Brave History',
          name_i18n: { 'zh-CN': 'Brave 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Brave browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Brave 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:brave',
          display_group: browserDisplayGroup('Brave', 50),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'brave-history',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
        {
          plugin_id: 'photo-library',
          name: 'Photo Library',
          name_i18n: { 'zh-CN': '照片库' },
          version: '0.1.0',
          description: 'Read local photo libraries.',
          description_i18n: { 'zh-CN': '读取本地照片库。' },
          author: 'Magi Team',
          icon: 'lucide:image',
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'photo-library',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
      ],
    });
    const install = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);
    const onInstallComplete = vi.fn().mockResolvedValue(undefined);

    render(<PluginMarketplace installedPlugins={[]} onInstallComplete={onInstallComplete} />);

    const browserCard = await screen.findByTestId('marketplace-plugin-browser-history');
    expect(browserCard).toHaveTextContent('浏览器历史');
    expect(browserCard).toHaveTextContent('v0.1.0');
    expect(browserCard).toHaveTextContent('Chrome');
    expect(browserCard).toHaveTextContent('Safari');
    expect(browserCard).toHaveTextContent('Brave');
    expect(screen.queryByTestId('marketplace-plugin-chrome-history')).not.toBeInTheDocument();
    expect(screen.queryByTestId('marketplace-plugin-safari-history')).not.toBeInTheDocument();
    expect(screen.queryByTestId('marketplace-plugin-brave-history')).not.toBeInTheDocument();
    expect(await screen.findByTestId('marketplace-plugin-photo-library')).toHaveTextContent('照片库');

    await user.click(within(browserCard).getByRole('button', { name: 'settings.marketplace.actions.chooseEntries' }));
    const picker = await screen.findByTestId('marketplace-entry-picker-browser-history');
    expect(within(picker).getByTestId('marketplace-entry-option-chrome-history')).toHaveTextContent('Chrome');
    expect(within(picker).getByTestId('marketplace-entry-option-safari-history')).toHaveTextContent('Safari');
    expect(within(picker).getByTestId('marketplace-entry-option-brave-history')).toHaveTextContent('Brave');
    await user.click(within(picker).getByTestId('marketplace-entry-checkbox-brave-history'));
    await user.click(within(picker).getByRole('button', { name: 'settings.marketplace.entryPicker.confirm' }));
    await user.click(await screen.findByText('settings.marketplace.consent.confirm.install'));

    await waitFor(() => {
      expect(install).toHaveBeenCalledWith('chrome-history', expect.any(Function));
      expect(install).toHaveBeenCalledWith('safari-history', expect.any(Function));
      expect(install).not.toHaveBeenCalledWith('brave-history', expect.any(Function));
    });
  });

  it('shows partially installed grouped entries and installs only missing selections', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '1',
      plugins: [
        {
          plugin_id: 'chrome-history',
          name: 'Chrome History',
          name_i18n: { 'zh-CN': 'Chrome 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Chrome browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Chrome 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:googlechrome',
          display_group: browserDisplayGroup('Chrome', 10),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'chrome-history',
          installed: true,
          installed_version: '0.1.0',
          update_available: false,
          capabilities: [],
        },
        {
          plugin_id: 'safari-history',
          name: 'Safari History',
          name_i18n: { 'zh-CN': 'Safari 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Safari browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Safari 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:safari',
          display_group: browserDisplayGroup('Safari', 20),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'safari-history',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
        {
          plugin_id: 'firefox-history',
          name: 'Firefox History',
          name_i18n: { 'zh-CN': 'Firefox 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Firefox browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Firefox 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:firefox',
          display_group: browserDisplayGroup('Firefox', 30),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'firefox-history',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
      ],
    });
    const install = vi.spyOn(pluginsApi, 'installFromRegistryWithProgress').mockResolvedValue({} as any);

    render(<PluginMarketplace installedPlugins={[]} onInstallComplete={vi.fn()} />);

    const browserCard = await screen.findByTestId('marketplace-plugin-browser-history');
    expect(browserCard).toHaveTextContent('settings.marketplace.badge.installedPartial');
    expect(within(browserCard).getByTestId('marketplace-entry-chip-chrome-history')).toHaveTextContent('settings.marketplace.entryStatus.installed');
    expect(within(browserCard).getByTestId('marketplace-entry-chip-safari-history')).toHaveTextContent('settings.marketplace.entryStatus.available');

    await user.click(within(browserCard).getByRole('button', { name: 'settings.marketplace.actions.addEntries' }));
    const picker = await screen.findByTestId('marketplace-entry-picker-browser-history');
    expect(within(picker).getByTestId('marketplace-entry-checkbox-chrome-history')).toBeDisabled();
    await user.click(within(picker).getByRole('button', { name: 'settings.marketplace.entryPicker.confirm' }));
    await user.click(await screen.findByText('settings.marketplace.consent.confirm.install'));

    await waitFor(() => {
      expect(install).toHaveBeenCalledWith('safari-history', expect.any(Function));
      expect(install).toHaveBeenCalledWith('firefox-history', expect.any(Function));
      expect(install).not.toHaveBeenCalledWith('chrome-history', expect.any(Function));
    });
  });

  it('shows one grouped progress panel while installing grouped browser entries', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '1',
      plugins: [
        {
          plugin_id: 'chrome-history',
          name: 'Chrome History',
          name_i18n: { 'zh-CN': 'Chrome 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Chrome browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Chrome 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:googlechrome',
          display_group: browserDisplayGroup('Chrome', 10),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'chrome-history',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
        {
          plugin_id: 'safari-history',
          name: 'Safari History',
          name_i18n: { 'zh-CN': 'Safari 浏览器历史' },
          version: '0.1.0',
          description: 'Read local Safari browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Safari 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:safari',
          display_group: browserDisplayGroup('Safari', 20),
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'safari-history',
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
      ],
    });
    vi.spyOn(pluginsApi, 'installFromRegistryWithProgress').mockImplementation(
      async (pluginId, onProgress) => {
        onProgress?.({
          job_id: `job-${pluginId}`,
          operation: 'install',
          plugin_id: pluginId,
          filename: null,
          status: 'running',
          stage: 'install',
          progress_pct: pluginId === 'chrome-history' ? 35 : 70,
          message: `Installing ${pluginId}`,
          logs: [],
          result: null,
          created_at_ms: 1,
          updated_at_ms: 1,
          finished_at_ms: null,
        });
        return {} as any;
      }
    );

    render(<PluginMarketplace installedPlugins={[]} onInstallComplete={vi.fn()} />);

    const browserCard = await screen.findByTestId('marketplace-plugin-browser-history');
    await user.click(within(browserCard).getByRole('button', { name: 'settings.marketplace.actions.chooseEntries' }));
    const picker = await screen.findByTestId('marketplace-entry-picker-browser-history');
    await user.click(within(picker).getByRole('button', { name: 'settings.marketplace.entryPicker.confirm' }));
    await user.click(await screen.findByText('settings.marketplace.consent.confirm.install'));

    await waitFor(() => {
      expect(within(browserCard).getByText('settings.marketplace.installProgress.groupTitle')).toBeInTheDocument();
    });
    expect(within(browserCard).queryByText(/Chrome 浏览器历史/)).not.toBeInTheDocument();
    expect(within(browserCard).queryByText(/Safari 浏览器历史/)).not.toBeInTheDocument();
  });
});
