import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { PluginPackageState } from '@/api/modules/plugins';
import PluginsSection from '@/components/settings/PluginsSection';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && typeof options.defaultValue === 'string' ? options.defaultValue : key,
  }),
}));

const pluginPackage = (pluginId: string, name: string): PluginPackageState => ({
  manifest: {
    plugin_id: pluginId,
    name,
    version: '1.0.0',
    description: `${name} package`,
    author: 'Magi Team',
    official: true,
    contribution_types: ['sensor'],
    source: 'external',
    plugin_dir: `/tmp/${pluginId}`,
    manifest_path: `/tmp/${pluginId}/plugin.toml`,
    capabilities: [],
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
      contribution_type: 'sensor',
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

describe('PluginsSection', () => {
  it('groups browser implementations under one installed plugin card', () => {
    render(
      <PluginsSection
        plugins={[
          pluginPackage('chrome-history', 'Chrome History'),
          pluginPackage('safari-history', 'Safari History'),
          pluginPackage('photo-library', 'Photo Library'),
        ]}
        drafts={{}}
        onFieldChange={vi.fn()}
        onRescan={vi.fn()}
        onPluginAction={vi.fn()}
        processingIds={{}}
      />
    );

    expect(screen.getByTestId('installed-plugin-browser-history')).toHaveTextContent('浏览历史');
    expect(screen.getByTestId('installed-plugin-browser-history')).toHaveTextContent('Chrome');
    expect(screen.getByTestId('installed-plugin-browser-history')).toHaveTextContent('Safari');
    expect(screen.queryByTestId('installed-plugin-chrome-history')).not.toBeInTheDocument();
    expect(screen.queryByTestId('installed-plugin-safari-history')).not.toBeInTheDocument();
    expect(screen.getByTestId('installed-plugin-photo-library')).toHaveTextContent('Photo Library');
  });
});
