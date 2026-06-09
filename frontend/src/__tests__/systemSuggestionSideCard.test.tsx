import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { SystemSuggestionSideCard } from '../components/chat/SystemSuggestionSideCard';
import { usePluginInstallPanelStore } from '../stores/pluginInstallPanel';
import type { SuggestionProposal } from '../api/modules/systemSuggestions';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }),
}));

const singleProposal: SuggestionProposal = {
  dedupe_key: 'browser_history',
  category: 'browser_history',
  plugin_ids: ['chrome-history'],
  installable_plugin_ids: [],
  confidence: 0.9,
  rationale: { zh: '连接 Chrome 历史', en: 'Connect Chrome history' },
};

const multiProposal: SuggestionProposal = {
  dedupe_key: 'browser_history',
  category: 'browser_history',
  plugin_ids: ['chrome-history', 'safari-history', 'arc-history'],
  installable_plugin_ids: [],
  confidence: 0.85,
  rationale: { zh: '连接浏览器历史', en: 'Connect browser history' },
};

describe('SystemSuggestionSideCard', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    usePluginInstallPanelStore.getState().closePanel();
  });

  it('renders rationale text and a row for the single installable plugin', () => {
    render(
      <SystemSuggestionSideCard
        proposal={singleProposal}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );
    expect(screen.getByText(/连接 Chrome 历史/)).toBeInTheDocument();
    expect(screen.getAllByTestId('system-suggestion-side-card-row')).toHaveLength(1);
  });

  it('renders one row per plugin in the proposal (backend already availability-filtered)', () => {
    render(
      <SystemSuggestionSideCard
        proposal={multiProposal}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );
    expect(screen.getAllByTestId('system-suggestion-side-card-row')).toHaveLength(
      multiProposal.plugin_ids.length,
    );
  });

  it('invokes onDecline when "先不用" is clicked', async () => {
    const onDecline = vi.fn();
    render(
      <SystemSuggestionSideCard
        proposal={singleProposal}
        onClose={() => {}}
        onDecline={onDecline}
        onActivated={() => {}}
      />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: /systemSuggestion.decline|decline|先不用|not now/i }),
    );
    expect(onDecline).toHaveBeenCalledWith('browser_history');
  });

  it('invokes onClose when × header button clicked', async () => {
    const onClose = vi.fn();
    render(
      <SystemSuggestionSideCard
        proposal={singleProposal}
        onClose={onClose}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /systemSuggestion.dismiss|close|关闭|×/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('opens the install panel when connect is clicked (no longer a no-op)', async () => {
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');
    render(
      <SystemSuggestionSideCard
        proposal={singleProposal}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );

    await userEvent.click(await screen.findByTestId('empty-state-connect-chrome-history'));
    expect(openPanel).toHaveBeenCalledWith('chrome-history', { install: false });
  });

  it('opens the panel in install-mode for a not-yet-installed plugin', async () => {
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');
    render(
      <SystemSuggestionSideCard
        proposal={{ ...singleProposal, installable_plugin_ids: ['chrome-history'] }}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );

    await userEvent.click(await screen.findByTestId('empty-state-connect-chrome-history'));
    expect(openPanel).toHaveBeenCalledWith('chrome-history', { install: true });
  });
});
