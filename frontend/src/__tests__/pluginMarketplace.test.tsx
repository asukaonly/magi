import { render, screen } from '@testing-library/react';
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

  it('shows registry-provided plugin icons on marketplace cards', async () => {
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      registry_version: '1',
      plugins: [
        {
          plugin_id: 'chrome-history',
          name: 'Chrome History',
          name_i18n: { 'zh-CN': 'Chrome 浏览历史' },
          version: '0.1.0',
          description: 'Read local Chrome browsing history.',
          description_i18n: { 'zh-CN': '读取本地 Chrome 浏览记录。' },
          author: 'Magi Team',
          icon: 'brand:googlechrome',
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
      ],
    });

    render(<PluginMarketplace installedPlugins={[]} onInstallComplete={vi.fn()} />);

    expect(await screen.findByText('Chrome 浏览历史')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-icon-googlechrome')).toBeInTheDocument();
  });
});
