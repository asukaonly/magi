import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PluginConsentDialog } from '@/components/plugins/PluginConsentDialog';
import type { PluginCapability } from '@/api/modules/plugins';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, o?: any) => o?.name ?? k, i18n: { language: 'en' } }),
}));

const cap = (capability: string): PluginCapability => ({
  capability, scope: [], optional: false, reason: '', reason_i18n: {},
});

describe('PluginConsentDialog', () => {
  it('renders declared capabilities and confirms', () => {
    const onConfirm = vi.fn();
    render(
      <PluginConsentDialog open mode="install" pluginName="Demo" version="1.0.0"
        capabilities={[cap('calendar'), cap('network')]} onConfirm={onConfirm} onCancel={vi.fn()} />,
    );
    expect(screen.getByText('settings.marketplace.capability.calendar.label')).toBeTruthy();
    fireEvent.click(screen.getByText('settings.marketplace.consent.confirm.install'));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('shows the empty-declaration message but still requires confirm', () => {
    render(
      <PluginConsentDialog open mode="install" pluginName="Demo" version="1.0.0"
        capabilities={[]} onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText('settings.marketplace.consent.ledeEmpty')).toBeTruthy();
    expect(screen.getByText('settings.marketplace.consent.confirm.install')).toBeTruthy();
  });

  it('shows the plugin icon and renders each declared scope on its own line', () => {
    render(
      <PluginConsentDialog
        open
        mode="install"
        pluginName="Chrome History"
        pluginId="chrome-history"
        pluginIcon="brand:googlechrome"
        version="1.0.0"
        capabilities={[{
          ...cap('filesystem_read'),
          scope: [
            '~/Library/Application Support/Google/Chrome',
            '%LOCALAPPDATA%\\Google\\Chrome',
          ],
          reason: 'Read the local Chrome history database',
        }]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByTestId('plugin-icon-googlechrome')).toBeTruthy();
    expect(screen.getByText('~/Library/Application Support/Google/Chrome').tagName).toBe('CODE');
    expect(screen.getByText('%LOCALAPPDATA%\\Google\\Chrome').tagName).toBe('CODE');
    expect(screen.getByText('~/Library/Application Support/Google/Chrome')).toHaveClass('block');
    expect(screen.getByText('%LOCALAPPDATA%\\Google\\Chrome')).toHaveClass('block');
  });
});
