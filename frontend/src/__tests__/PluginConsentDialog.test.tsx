import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PluginConsentDialog } from '@/components/plugins/PluginConsentDialog';
import type { PluginCapability } from '@/api/modules/plugins';

const SVG_ICON = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=';

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
        pluginIcon={SVG_ICON}
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

    expect(screen.getByTestId('plugin-icon-asset')).toHaveAttribute('src', SVG_ICON);
    expect(screen.getByText('~/Library/Application Support/Google/Chrome').tagName).toBe('CODE');
    expect(screen.getByText('%LOCALAPPDATA%\\Google\\Chrome').tagName).toBe('CODE');
    expect(screen.getByText('~/Library/Application Support/Google/Chrome')).toHaveClass('block');
    expect(screen.getByText('%LOCALAPPDATA%\\Google\\Chrome')).toHaveClass('block');
  });

  it('shows the sideload behavior warning', () => {
    render(
      <PluginConsentDialog
        open
        mode="sideload"
        pluginName="Demo"
        version="1.0.0"
        capabilities={[]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole('note')).toHaveTextContent(
      'settings.marketplace.consent.sideloadWarning',
    );
  });
});
