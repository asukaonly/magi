import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { pluginsApi } from '@/api/modules/plugins';
import { PluginMarketplace } from '@/components/settings/PluginMarketplace';

const SVG_ICON = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=';

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
      registry_version: '4',
      install_fingerprint: 'fingerprint-1',
      plugins: [
        {
          plugin_id: 'photo-library',
          name: 'Photo Library',
          name_i18n: { 'zh-CN': '照片库' },
          version: '0.1.0',
          description: 'Read local photo libraries.',
          description_i18n: { 'zh-CN': '读取本地照片库。' },
          author: 'Magi Team',
          icon: SVG_ICON,
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
    expect(screen.getByTestId('plugin-icon-asset')).toHaveAttribute('src', SVG_ICON);
  });

  it('refreshes stale marketplace details and requires a new confirmation', async () => {
    const user = userEvent.setup();
    const registryEntry = (version: string) => ({
      plugin_id: 'photo-library',
      name: 'Photo Library',
      name_i18n: { 'zh-CN': '照片库' },
      version,
      description: 'Read local photo libraries.',
      description_i18n: { 'zh-CN': '读取本地照片库。' },
      author: 'Magi Team',
      icon: SVG_ICON,
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
    });
    const getRegistry = vi
      .spyOn(pluginsApi, 'getRegistry')
      .mockResolvedValueOnce({
        registry_version: '4',
        install_fingerprint: 'fingerprint-old',
        plugins: [registryEntry('0.1.0')],
      })
      .mockResolvedValueOnce({
        registry_version: '4',
        install_fingerprint: 'fingerprint-new',
        plugins: [registryEntry('0.2.0')],
      });
    const install = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockRejectedValue({
        status: 409,
        code: 'PLUGIN_REGISTRY_CHANGED',
        message: 'Registry changed',
      });
    const onInstallComplete = vi.fn().mockResolvedValue(undefined);

    render(
      <PluginMarketplace
        installedPlugins={[]}
        onInstallComplete={onInstallComplete}
      />,
    );

    const card = await screen.findByTestId('marketplace-plugin-photo-library');
    await user.click(
      within(card).getByRole('button', { name: 'settings.marketplace.actions.install' }),
    );
    await user.click(
      await screen.findByText('settings.marketplace.consent.confirm.install'),
    );

    await waitFor(() => {
      expect(install).toHaveBeenCalledWith(
        'photo-library',
        'fingerprint-old',
        expect.any(Function),
      );
      expect(getRegistry).toHaveBeenLastCalledWith({ force: true });
      expect(card).toHaveTextContent('v0.2.0');
    });
    expect(install).toHaveBeenCalledTimes(1);
    expect(onInstallComplete).not.toHaveBeenCalled();
  });

  it('updates with the fingerprint from the details the user confirmed', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'update-fingerprint',
      plugins: [
        {
          plugin_id: 'photo-library',
          name: 'Photo Library',
          name_i18n: { 'zh-CN': '照片库' },
          version: '0.2.0',
          description: 'Read local photo libraries.',
          description_i18n: { 'zh-CN': '读取本地照片库。' },
          author: 'Magi Team',
          icon: SVG_ICON,
          official: true,
          data_locality: 'local_only',
          contribution_types: ['sensor'],
          platforms: [],
          min_sdk_version: '0.1.0',
          homepage: '',
          repository: '',
          path: 'photo-library',
          installed: true,
          installed_version: '0.1.0',
          update_available: true,
          capabilities: [
            {
              capability: 'photos',
              scope: [],
              optional: false,
              reason: 'Read photos',
              reason_i18n: {},
            },
          ],
        },
      ],
    });
    const update = vi
      .spyOn(pluginsApi, 'updatePluginWithProgress')
      .mockResolvedValue({} as any);

    render(
      <PluginMarketplace
        installedPlugins={[
          {
            manifest: {
              plugin_id: 'photo-library',
              consented_capabilities: [],
            },
          } as any,
        ]}
        onInstallComplete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const card = await screen.findByTestId('marketplace-plugin-photo-library');
    await user.click(
      within(card).getAllByRole('button', {
        name: /settings\.marketplace\.actions\.update/,
      })[0],
    );
    await user.click(
      await screen.findByRole('button', {
        name: 'settings.marketplace.consent.confirm.update',
      }),
    );

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith(
        'photo-library',
        'update-fingerprint',
        expect.any(Function),
      );
    });
  });

  it('checks new permissions against each grouped entry own consent', async () => {
    const user = userEvent.setup();
    const networkCapability = {
      capability: 'network',
      scope: ['history.example.com'],
      optional: false,
      reason: 'Read browser history',
      reason_i18n: {},
    };
    const groupedEntry = (
      pluginId: string,
      memberLabel: string,
      updateAvailable: boolean,
    ) => ({
      plugin_id: pluginId,
      name: memberLabel,
      name_i18n: {},
      version: updateAvailable ? '0.2.0' : '0.1.0',
      description: `${memberLabel} history`,
      description_i18n: {},
      author: 'Magi Team',
      icon: 'lucide:globe',
      display_group: browserDisplayGroup(memberLabel, updateAvailable ? 20 : 10),
      official: true,
      data_locality: 'local_only',
      contribution_types: ['sensor'],
      platforms: [],
      min_sdk_version: '0.1.0',
      homepage: '',
      repository: '',
      path: pluginId,
      installed: true,
      installed_version: '0.1.0',
      update_available: updateAvailable,
      capabilities: [networkCapability],
    });
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'group-update-fingerprint',
      plugins: [
        groupedEntry('chrome-history', 'Chrome', false),
        groupedEntry('safari-history', 'Safari', true),
      ],
    });
    const update = vi
      .spyOn(pluginsApi, 'updatePluginWithProgress')
      .mockResolvedValue({} as any);

    render(
      <PluginMarketplace
        installedPlugins={[
          {
            manifest: {
              plugin_id: 'chrome-history',
              consented_capabilities: [networkCapability],
            },
          } as any,
          {
            manifest: {
              plugin_id: 'safari-history',
              consented_capabilities: [],
            },
          } as any,
        ]}
        onInstallComplete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const card = await screen.findByTestId('marketplace-plugin-browser-history');
    await user.click(
      within(card).getAllByRole('button', {
        name: /settings\.marketplace\.actions\.update/,
      })[0],
    );

    expect(update).not.toHaveBeenCalled();
    await user.click(
      await screen.findByRole('button', {
        name: 'settings.marketplace.consent.confirm.update',
      }),
    );

    await waitFor(() => {
      expect(update).toHaveBeenCalledTimes(1);
      expect(update).toHaveBeenCalledWith(
        'safari-history',
        'group-update-fingerprint',
        expect.any(Function),
      );
    });
  });

  it('groups browser history implementations and lets users choose entries before installing', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'fingerprint-1',
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
      expect(install).toHaveBeenCalledWith(
        'chrome-history',
        'fingerprint-1',
        expect.any(Function),
      );
      expect(install).toHaveBeenCalledWith(
        'safari-history',
        'fingerprint-1',
        expect.any(Function),
      );
      expect(install).not.toHaveBeenCalledWith(
        'brave-history',
        'fingerprint-1',
        expect.any(Function),
      );
    });
  });

  it('shows partially installed grouped entries and installs only missing selections', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'fingerprint-1',
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
      expect(install).toHaveBeenCalledWith(
        'safari-history',
        'fingerprint-1',
        expect.any(Function),
      );
      expect(install).toHaveBeenCalledWith(
        'firefox-history',
        'fingerprint-1',
        expect.any(Function),
      );
      expect(install).not.toHaveBeenCalledWith(
        'chrome-history',
        'fingerprint-1',
        expect.any(Function),
      );
    });
  });

  it('shows one grouped progress panel while installing grouped browser entries', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'fingerprint-1',
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
      async (pluginId, _expectedFingerprint, onProgress) => {
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

  it('uploads a sideload package once and installs the inspected candidate', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'fingerprint-1',
      plugins: [],
    });
    const candidate = {
      candidate_id: 'candidate-1',
      archive_sha256: 'a'.repeat(64),
      package_sha256: 'c'.repeat(64),
      expires_at_ms: Date.now() + 60_000,
      manifest: {
        plugin_id: 'demo-plugin',
        name: 'Demo Plugin',
        version: '1.0.0',
        description: '',
        author: 'Demo',
        official: false,
        contribution_types: [],
        source: 'external',
        plugin_dir: '',
        manifest_path: '',
        capabilities: [],
      },
    };
    const createCandidate = vi
      .spyOn(pluginsApi, 'createInstallCandidate')
      .mockResolvedValue(candidate);
    const installCandidate = vi
      .spyOn(pluginsApi, 'installCandidateWithProgress')
      .mockResolvedValue({} as any);
    const onInstallComplete = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <PluginMarketplace installedPlugins={[]} onInstallComplete={onInstallComplete} />,
    );
    const file = new File(['archive'], 'demo.zip', { type: 'application/zip' });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;

    await user.upload(input, file);
    await user.click(
      await screen.findByText('settings.marketplace.consent.confirm.install'),
    );

    await waitFor(() => {
      expect(createCandidate).toHaveBeenCalledOnce();
      expect(createCandidate).toHaveBeenCalledWith(file);
      expect(installCandidate).toHaveBeenCalledWith(
        'candidate-1',
        'a'.repeat(64),
        expect.any(Function),
      );
      expect(onInstallComplete).toHaveBeenCalledOnce();
    });
  });

  it('discards an inspected sideload candidate when the user cancels', async () => {
    const user = userEvent.setup();
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'fingerprint-1',
      plugins: [],
    });
    vi.spyOn(pluginsApi, 'createInstallCandidate').mockResolvedValue({
      candidate_id: 'candidate-2',
      archive_sha256: 'b'.repeat(64),
      package_sha256: 'd'.repeat(64),
      expires_at_ms: Date.now() + 60_000,
      manifest: {
        plugin_id: 'demo-plugin',
        name: 'Demo Plugin',
        version: '1.0.0',
        description: '',
        author: 'Demo',
        official: false,
        contribution_types: [],
        source: 'external',
        plugin_dir: '',
        manifest_path: '',
        capabilities: [],
      },
    });
    const discard = vi
      .spyOn(pluginsApi, 'discardInstallCandidate')
      .mockResolvedValue(undefined);
    const { container } = render(
      <PluginMarketplace installedPlugins={[]} onInstallComplete={vi.fn()} />,
    );
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;

    await user.upload(
      input,
      new File(['archive'], 'demo.zip', { type: 'application/zip' }),
    );
    await user.click(await screen.findByText('settings.marketplace.consent.cancel'));

    await waitFor(() => {
      expect(discard).toHaveBeenCalledWith('candidate-2');
    });
  });
});
