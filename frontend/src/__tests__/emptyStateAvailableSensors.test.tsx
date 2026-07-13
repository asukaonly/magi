import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { InstallableItem } from '@/api/modules/systemSuggestions';
import { EmptyStateAvailableSensors } from '../components/empty-state/EmptyStateAvailableSensors';
import { usePluginInstallPanelStore } from '../stores/pluginInstallPanel';
import { useChatShellStore } from '../stores/chat-shell';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// The empty-state grid sources its candidate plugins from the backend
// /system-suggestions/installable endpoint (installed ∪ registry-available).
const mockUseInstallableSensors = vi.fn();
vi.mock('@/hooks/useInstallableSensors', () => ({
  useInstallableSensors: () => mockUseInstallableSensors(),
}));

function item(overrides: Partial<InstallableItem>): InstallableItem {
  return {
    plugin_id: 'chrome-history',
    category: 'browser_history',
    installed: false,
    rationale: { zh: '', en: '' },
    setup_time_estimate_seconds: 10,
    data_locality: 'local_only',
    ...overrides,
  };
}

describe('EmptyStateAvailableSensors', () => {
  beforeEach(() => {
    mockUseInstallableSensors.mockReset();
    usePluginInstallPanelStore.getState().closePanel();
    useChatShellStore.setState({ activePanel: 'none', settingsNavigationIntent: null });
  });

  it('renders nothing while the installable list is loading', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: true,
      refresh: vi.fn(),
    });
    const { container } = render(<EmptyStateAvailableSensors />);
    expect(container.textContent ?? '').not.toMatch(/Chrome/);
    // No browse-all exit while still loading (avoid flashing it before cards).
    expect(screen.queryByTestId('empty-state-browse-all')).not.toBeInTheDocument();
  });

  it('renders fallback cards while an embedded surface is still loading', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: true,
      refresh: vi.fn(),
    });
    render(
      <EmptyStateAvailableSensors
        showBrowseAll={false}
        fallbackPluginIds={['chrome-history', 'git-activity']}
      />,
    );
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-git-activity')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-browse-all')).not.toBeInTheDocument();
  });

  it('uses preloaded installable items when provided', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: true,
      refresh: vi.fn(),
    });
    render(
      <EmptyStateAvailableSensors
        installableItems={[item({ plugin_id: 'git-activity', category: 'code_activity', installed: true })]}
        installableLoading={false}
      />,
    );
    expect(screen.getByTestId('empty-state-connect-git-activity')).toBeInTheDocument();
  });

  it('never uses fallback cards in first-context mode', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(
      <EmptyStateAvailableSensors
        variant="first_context"
        showBrowseAll={false}
        fallbackPluginIds={['chrome-history', 'calendar']}
      />,
    );
    expect(screen.queryByTestId(/empty-state-connect-/)).not.toBeInTheDocument();
    expect(screen.getByText('emptyState.noAvailable')).toBeInTheDocument();
  });

  it('shows one featured recommendation and at most two distinct-category alternatives', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'chrome-history', category: 'browser_history' }),
        item({ plugin_id: 'safari-history', category: 'browser_history' }),
        item({ plugin_id: 'calendar', category: 'calendar' }),
        item({ plugin_id: 'coding_agent_history', category: 'code_activity' }),
        item({ plugin_id: 'photo-library', category: 'photos' }),
      ],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors variant="first_context" showBrowseAll={false} />);

    expect(screen.getByTestId('empty-state-featured-chrome-history')).toBeInTheDocument();
    expect(
      screen.getByText('emptyState.plugins.chromeHistory.firstContextValue'),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId(/empty-state-connect-/)).toHaveLength(3);
    expect(screen.queryByTestId('empty-state-connect-safari-history')).not.toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-connect-photo-library')).not.toBeInTheDocument();
  });

  it('prefers an installed sibling within a recommendation category', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'chrome-history', category: 'browser_history', installed: false }),
        item({ plugin_id: 'safari-history', category: 'browser_history', installed: true }),
      ],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors variant="first_context" showBrowseAll={false} />);

    expect(screen.getByTestId('empty-state-featured-safari-history')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-connect-chrome-history')).not.toBeInTheDocument();
  });

  it('does not refill a restored connected category when the connected source is absent from the API', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'safari-history', category: 'browser_history' }),
        item({ plugin_id: 'calendar', category: 'calendar' }),
      ],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(
      <EmptyStateAvailableSensors
        variant="first_context"
        showBrowseAll={false}
        excludePluginIds={['chrome-history']}
      />,
    );

    expect(screen.queryByTestId('empty-state-connect-safari-history')).not.toBeInTheDocument();
    expect(screen.getByTestId('empty-state-featured-calendar')).toBeInTheDocument();
  });

  it('shows a retry action when first-context availability fails', async () => {
    const refresh = vi.fn();
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: false,
      error: new Error('boom'),
      refresh,
    });
    render(<EmptyStateAvailableSensors variant="first_context" showBrowseAll={false} />);

    await userEvent.click(screen.getByTestId('empty-state-retry'));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('can fill a sparse preloaded list with first-context fallback cards', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: true,
      refresh: vi.fn(),
    });
    render(
      <EmptyStateAvailableSensors
        showBrowseAll={false}
        installableItems={[item({ plugin_id: 'chrome-history', installed: false })]}
        installableLoading={false}
        fallbackPluginIds={['chrome-history', 'coding_agent_history', 'calendar', 'git-activity', 'photo-library']}
        fillWithFallback
      />,
    );
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual([
      'empty-state-connect-chrome-history',
      'empty-state-connect-coding_agent_history',
      'empty-state-connect-calendar',
      'empty-state-connect-git-activity',
      'empty-state-connect-photo-library',
    ]);
  });

  it('does not let a browser fallback displace an available non-Chrome browser source', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: true,
      refresh: vi.fn(),
    });
    render(
      <EmptyStateAvailableSensors
        showBrowseAll={false}
        installableItems={[item({ plugin_id: 'safari-history', category: 'browser_history', installed: false })]}
        installableLoading={false}
        fallbackPluginIds={['chrome-history', 'calendar', 'git-activity']}
        fillWithFallback
      />,
    );
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual([
      'empty-state-connect-safari-history',
      'empty-state-connect-calendar',
      'empty-state-connect-git-activity',
    ]);
    expect(screen.queryByTestId('empty-state-connect-chrome-history')).not.toBeInTheDocument();
  });

  it('still renders the browse-all exit when no cards are available', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    // No cards, but the marketplace exit must stay reachable.
    expect(screen.queryByTestId(/empty-state-connect-/)).not.toBeInTheDocument();
    expect(screen.getByTestId('empty-state-browse-all')).toBeInTheDocument();
  });

  it('can hide the browse-all exit for embedded surfaces', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ plugin_id: 'chrome-history', installed: false })],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors showBrowseAll={false} />);
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-browse-all')).not.toBeInTheDocument();
  });

  it('renders fallback cards when an embedded surface has no installable items', async () => {
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: false,
      refresh: vi.fn(),
    });
    render(
      <EmptyStateAvailableSensors
        showBrowseAll={false}
        fallbackPluginIds={['chrome-history', 'git-activity']}
      />,
    );
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-git-activity')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-browse-all')).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId('empty-state-connect-chrome-history'));
    expect(openPanel).toHaveBeenCalledWith('chrome-history', { install: true });
  });

  it('renders a card for each installable item with display metadata', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'chrome-history', installed: false }),
        item({ plugin_id: 'git-activity', category: 'code_activity', installed: true }),
        // No empty-state metadata -> silently skipped.
        item({ plugin_id: 'unknown-plugin', category: 'misc', installed: true }),
      ],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    expect(
      screen.getByText('emptyState.plugins.chromeHistory.title'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('emptyState.plugins.gitActivity.title'),
    ).toBeInTheDocument();
    // The metadata-less plugin produces no card.
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
    expect(
      screen.queryByTestId('empty-state-connect-unknown-plugin'),
    ).not.toBeInTheDocument();
  });

  it('orders cards by the empty-state priority list', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        // Intentionally out of priority order in the input.
        item({ plugin_id: 'git-activity', category: 'code_activity', installed: true }),
        item({ plugin_id: 'chrome-history', installed: false }),
      ],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual([
      'empty-state-connect-chrome-history',
      'empty-state-connect-git-activity',
    ]);
  });

  it('uses another browser history source first when Chrome is unavailable', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'git-activity', category: 'code_activity', installed: true }),
        item({ plugin_id: 'safari-history', category: 'browser_history', installed: false }),
      ],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual([
      'empty-state-connect-safari-history',
      'empty-state-connect-git-activity',
    ]);
  });

  it('renders only one browser history source when multiple browsers are available', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'firefox-history', category: 'browser_history', installed: false }),
        item({ plugin_id: 'safari-history', category: 'browser_history', installed: false }),
        item({ plugin_id: 'chrome-history', category: 'browser_history', installed: false }),
        item({ plugin_id: 'git-activity', category: 'code_activity', installed: true }),
      ],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual([
      'empty-state-connect-chrome-history',
      'empty-state-connect-git-activity',
    ]);
    expect(screen.queryByTestId('empty-state-connect-safari-history')).not.toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-connect-firefox-history')).not.toBeInTheDocument();
  });

  it('keeps incremental screenshot capture out of first-context suggestions', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'calendar', category: 'calendar', installed: false }),
        item({ plugin_id: 'screenshot_timeline', category: 'screen_context', installed: false }),
      ],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual([
      'empty-state-connect-calendar',
    ]);
    expect(screen.queryByTestId('empty-state-connect-screenshot_timeline')).not.toBeInTheDocument();
  });

  it('connects an uninstalled item install-first via the panel ({ install: true })', async () => {
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ plugin_id: 'chrome-history', installed: false })],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    await userEvent.click(
      screen.getByTestId('empty-state-connect-chrome-history'),
    );
    expect(openPanel).toHaveBeenCalledWith('chrome-history', { install: true });
  });

  it('connects an already-installed item without install via the panel ({ install: false })', async () => {
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ plugin_id: 'git-activity', category: 'code_activity', installed: true })],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    await userEvent.click(
      screen.getByTestId('empty-state-connect-git-activity'),
    );
    expect(openPanel).toHaveBeenCalledWith('git-activity', { install: false });
  });

  it('caps the rendered cards at 5', () => {
    // All five first-context sources plus incremental screenshot capture are
    // available -> screenshot capture is filtered out, keeping the historical
    // sources visible.
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({ plugin_id: 'chrome-history', installed: false }),
        item({ plugin_id: 'coding_agent_history', category: 'code_activity', installed: true }),
        item({ plugin_id: 'screenshot_timeline', category: 'screen_context', installed: false }),
        item({ plugin_id: 'calendar', category: 'calendar', installed: false }),
        item({ plugin_id: 'git-activity', category: 'code_activity', installed: true }),
        item({ plugin_id: 'photo-library', category: 'photos', installed: false }),
      ],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons).toHaveLength(5);
    expect(screen.getByTestId('empty-state-connect-photo-library')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-state-connect-screenshot_timeline')).not.toBeInTheDocument();
    // The marketplace exit is still present.
    expect(screen.getByTestId('empty-state-browse-all')).toBeInTheDocument();
  });

  it('deep-links into the settings plugin marketplace from browse-all', async () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ plugin_id: 'chrome-history', installed: false })],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    await userEvent.click(screen.getByTestId('empty-state-browse-all'));
    const state = useChatShellStore.getState();
    expect(state.activePanel).toBe('settings');
    expect(state.settingsNavigationIntent).toEqual({ section: 'pluginsMarketplace' });
  });

  it('hides cards for excludePluginIds', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ plugin_id: 'chrome-history', installed: false })],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors excludePluginIds={['chrome-history']} />);
    expect(
      screen.queryByText('emptyState.plugins.chromeHistory.title'),
    ).not.toBeInTheDocument();
  });
});
