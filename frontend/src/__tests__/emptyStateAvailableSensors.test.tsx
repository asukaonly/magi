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

  it('orders screenshot_timeline above calendar', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        // Out of priority order in the input; screenshot_timeline ranks above
        // calendar per EMPTY_STATE_PRIORITY_PLUGINS.
        item({ plugin_id: 'calendar', category: 'calendar', installed: false }),
        item({ plugin_id: 'screenshot_timeline', category: 'screen_context', installed: false }),
      ],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual([
      'empty-state-connect-screenshot_timeline',
      'empty-state-connect-calendar',
    ]);
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
    // All six whitelisted plugins available -> only the top 5 render; the rest
    // stays behind the "browse all" marketplace exit.
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
    // photo-library is priority index 5 (6th) -> dropped past the cap.
    expect(
      screen.queryByTestId('empty-state-connect-photo-library'),
    ).not.toBeInTheDocument();
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
