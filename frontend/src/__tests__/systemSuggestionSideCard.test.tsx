import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { SystemSuggestionSideCard } from '../components/chat/SystemSuggestionSideCard';
import { sensorsApi } from '../api/modules/sensors';
import { pluginsApi } from '../api/modules/plugins';
import type { SuggestionProposal } from '../api/modules/systemSuggestions';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }),
}));

const mockUseAvailability = vi.fn();
vi.mock('../hooks/useAvailability', () => ({
  useAvailability: (...args: any[]) => mockUseAvailability(...args),
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
    mockUseAvailability.mockReset();
    vi.restoreAllMocks();
  });

  it('renders rationale text and a row for the single installable plugin', () => {
    mockUseAvailability.mockReturnValue({
      entries: [{ plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' }],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });
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

  it('renders multi-sibling layout with one row per installable plugin (unavailable hidden)', () => {
    mockUseAvailability.mockReturnValue({
      entries: [
        { plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' },
        { plugin_id: 'safari-history', available: true, reason: 'available', detail: null, checked_at: 'now' },
        { plugin_id: 'arc-history', available: false, reason: 'app_not_installed', detail: null, checked_at: 'now' },
      ],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });
    render(
      <SystemSuggestionSideCard
        proposal={multiProposal}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );
    expect(screen.getAllByTestId('system-suggestion-side-card-row')).toHaveLength(2);
  });

  it('invokes onDecline when "先不用" is clicked', async () => {
    mockUseAvailability.mockReturnValue({
      entries: [{ plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' }],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });
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
    mockUseAvailability.mockReturnValue({
      entries: [{ plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' }],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });
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

  it('opens the activation dialog when connect is clicked (no longer a no-op)', async () => {
    mockUseAvailability.mockReturnValue({
      entries: [{ plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' }],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({
      sources: [
        {
          plugin_id: 'chrome-history',
          source_name: 'chrome',
          activation_flow: {
            enabled_key: 'enabled',
            configured_key: 'configured',
            authorize_on_confirm: false,
            fields: [],
          },
        },
      ],
    } as any);

    render(
      <SystemSuggestionSideCard
        proposal={singleProposal}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );

    await userEvent.click(await screen.findByTestId('empty-state-connect-chrome-history'));
    await waitFor(() => expect(sensorsApi.getStatus).toHaveBeenCalled());
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('installs a not-yet-installed plugin before activating', async () => {
    mockUseAvailability.mockReturnValue({
      entries: [{ plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' }],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({ sources: [] } as any);
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);

    render(
      <SystemSuggestionSideCard
        proposal={{ ...singleProposal, installable_plugin_ids: ['chrome-history'] }}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );

    await userEvent.click(await screen.findByTestId('empty-state-connect-chrome-history'));
    await waitFor(() => expect(installSpy).toHaveBeenCalledWith('chrome-history'));
  });

  it('does not install an already-installed plugin', async () => {
    mockUseAvailability.mockReturnValue({
      entries: [{ plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' }],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({ sources: [] } as any);
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);

    render(
      <SystemSuggestionSideCard
        proposal={{ ...singleProposal, installable_plugin_ids: [] }}
        onClose={() => {}}
        onDecline={() => {}}
        onActivated={() => {}}
      />,
    );

    await userEvent.click(await screen.findByTestId('empty-state-connect-chrome-history'));
    await waitFor(() => expect(sensorsApi.getStatus).toHaveBeenCalled());
    expect(installSpy).not.toHaveBeenCalled();
  });
});
