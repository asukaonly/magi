import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { InstallableItem } from '@/api/modules/systemSuggestions';
import { EmptyStateAvailableSensors } from '../components/empty-state/EmptyStateAvailableSensors';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// The empty-state grid sources its candidate plugins from the backend
// /system-suggestions/installable endpoint (installed ∪ registry-available).
const mockUseInstallableSensors = vi.fn();
vi.mock('@/hooks/useInstallableSensors', () => ({
  useInstallableSensors: () => mockUseInstallableSensors(),
}));

// Stub the activation hook so we can observe how Connect wires through to
// openDialog (install-first for registry-only items).
const mockOpenDialog = vi.fn();
const mockUsePluginActivation = vi.fn();
vi.mock('../hooks/usePluginActivation', () => ({
  usePluginActivation: (...args: any[]) => mockUsePluginActivation(...args),
}));

// PluginActivationDialog reaches into React contexts we don't bootstrap here;
// stub it to a no-op so the orchestrator stays under test.
vi.mock('../components/plugins/PluginActivationDialog', () => ({
  PluginActivationDialog: () => null,
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
    mockOpenDialog.mockReset();
    mockOpenDialog.mockResolvedValue(undefined);
    mockUsePluginActivation.mockReset();
    mockUsePluginActivation.mockReturnValue({
      dialogState: null,
      openDialog: mockOpenDialog,
      closeDialog: vi.fn(),
      confirm: vi.fn(),
    });
  });

  it('renders nothing while the installable list is loading', () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: true,
      refresh: vi.fn(),
    });
    const { container } = render(<EmptyStateAvailableSensors />);
    expect(container.textContent ?? '').not.toMatch(/Chrome/);
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

  it('connects an uninstalled item install-first ({ install: true })', async () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ plugin_id: 'chrome-history', installed: false })],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    await userEvent.click(
      screen.getByTestId('empty-state-connect-chrome-history'),
    );
    expect(mockOpenDialog).toHaveBeenCalledWith('chrome-history', { install: true });
  });

  it('connects an already-installed item without install ({ install: false })', async () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ plugin_id: 'git-activity', category: 'code_activity', installed: true })],
      loading: false,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    await userEvent.click(
      screen.getByTestId('empty-state-connect-git-activity'),
    );
    expect(mockOpenDialog).toHaveBeenCalledWith('git-activity', { install: false });
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
