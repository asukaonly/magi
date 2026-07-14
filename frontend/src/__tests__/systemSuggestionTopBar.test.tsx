import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SystemSuggestionTopBar } from '../components/chat/SystemSuggestionTopBar';
import type { SuggestionProposal } from '../api/modules/systemSuggestions';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }),
}));

const sampleProposal: SuggestionProposal = {
  dedupe_key: 'browser_history',
  category: 'browser_history',
  plugins: [{
    plugin_id: 'chrome-history',
    name: 'Chrome History',
    name_i18n: {},
    icon: 'brand:googlechrome',
    installed: true,
  }],
  confidence: 0.9,
  rationale: { zh: '想让 magi 看你的浏览器历史？', en: 'Want magi to see your browsing?' },
};

describe('SystemSuggestionTopBar', () => {
  it('renders nothing when there is no proposal', () => {
    const { container } = render(
      <SystemSuggestionTopBar
        proposal={null}
        onOpen={() => {}}
        onDismiss={() => {}}
      />,
    );
    expect(container.textContent).toBe('');
  });

  it('renders the rationale text for the active locale', () => {
    render(
      <SystemSuggestionTopBar
        proposal={sampleProposal}
        onOpen={() => {}}
        onDismiss={() => {}}
      />,
    );
    expect(screen.getByText(/想让 magi 看你的浏览器历史/)).toBeInTheDocument();
  });

  it('invokes onOpen when the bar is clicked', async () => {
    const onOpen = vi.fn();
    render(
      <SystemSuggestionTopBar
        proposal={sampleProposal}
        onOpen={onOpen}
        onDismiss={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /想让/ }));
    expect(onOpen).toHaveBeenCalledWith(sampleProposal);
  });

  it('invokes onDismiss(transient) when × is clicked', async () => {
    const onDismiss = vi.fn();
    render(
      <SystemSuggestionTopBar
        proposal={sampleProposal}
        onOpen={() => {}}
        onDismiss={onDismiss}
      />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: /systemSuggestion.dismiss|dismiss|关闭|×/i }),
    );
    expect(onDismiss).toHaveBeenCalledWith('browser_history', 'transient');
  });
});
