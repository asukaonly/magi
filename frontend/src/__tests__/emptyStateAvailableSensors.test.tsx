import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { EmptyStateAvailableSensors } from '../components/empty-state/EmptyStateAvailableSensors';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockUseAvailability = vi.fn();
vi.mock('../hooks/useAvailability', () => ({
  useAvailability: (...args: any[]) => mockUseAvailability(...args),
}));

// Real activation API surface (verified in TimelineSourcesSection):
//   sensorsApi.getStatus()                          -> sources with activation_flow
//   sensorsApi.requestAuthorization(name, fields)   -> only when flow.authorize_on_confirm
//   pluginsApi.updateSettings(pluginId, updates)    -> persists enabled_key + configured_key
const mockGetStatus = vi.fn();
const mockRequestAuthorization = vi.fn();
vi.mock('../api/modules/sensors', () => ({
  sensorsApi: {
    getStatus: (...args: any[]) => mockGetStatus(...args),
    requestAuthorization: (...args: any[]) => mockRequestAuthorization(...args),
  },
}));

const mockUpdateSettings = vi.fn();
vi.mock('../api/modules/plugins', () => ({
  pluginsApi: {
    updateSettings: (...args: any[]) => mockUpdateSettings(...args),
  },
}));

// PluginSettingsFields is mounted inside the activation dialog and reaches into
// React contexts we don't bootstrap in this unit test. Stub it with a minimal
// no-op renderer so the dialog itself stays under test.
vi.mock('@/components/settings/PluginSettingsFields', () => ({
  __esModule: true,
  default: () => null,
}));

describe('EmptyStateAvailableSensors', () => {
  beforeEach(() => {
    mockUseAvailability.mockReset();
    mockGetStatus.mockReset();
    mockRequestAuthorization.mockReset();
    mockUpdateSettings.mockReset();
    mockUpdateSettings.mockResolvedValue({});
  });

  it('renders nothing while availability is loading', () => {
    mockUseAvailability.mockReturnValue({
      entries: [],
      byId: {},
      loading: true,
      error: null,
      refresh: vi.fn(),
    });
    const { container } = render(<EmptyStateAvailableSensors />);
    expect(container.textContent ?? '').not.toMatch(/Chrome/);
  });

  it('renders only plugins whose availability is true', () => {
    mockUseAvailability.mockReturnValue({
      entries: [
        { plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' },
        { plugin_id: 'system-calendar', available: false, reason: 'missing_file', detail: 'no cal', checked_at: 'now' },
        { plugin_id: 'git-activity', available: true, reason: 'available', detail: null, checked_at: 'now' },
        { plugin_id: 'photo-library', available: false, reason: 'unsupported_platform', detail: 'linux', checked_at: 'now' },
      ],
      byId: {} as any,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors />);
    expect(
      screen.getByText('emptyState.plugins.chromeHistory.title'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('emptyState.plugins.calendar.title'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('emptyState.plugins.gitActivity.title'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('emptyState.plugins.photoLibrary.title'),
    ).not.toBeInTheDocument();
  });

  it('opens activation dialog when Connect is clicked', async () => {
    mockUseAvailability.mockReturnValue({
      entries: [
        { plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' },
      ],
      byId: {} as any,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    mockGetStatus.mockResolvedValue({
      sources: [
        {
          source_name: 'chrome-history.events',
          plugin_id: 'chrome-history',
          contribution_id: 'events',
          display_name: 'Chrome History',
          description: '',
          fields: [],
          current_settings: {},
          enabled: false,
          sync_mode: 'manual',
          sync_interval_minutes: 60,
          storage_mode: 'external_reference',
          fetch_page_content: false,
          edge_whitelist: [],
          supports_pull_sync: true,
          activation_flow: {
            title: 'Connect Chrome',
            description: 'Authorize Chrome history sync.',
            confirm_label: 'Enable',
            cancel_label: 'Cancel',
            authorize_on_confirm: false,
            enabled_key: 'sensors.chrome-history.enabled',
            configured_key: 'sensors.chrome-history.configured',
            fields: [],
          },
        },
      ],
    });
    render(<EmptyStateAvailableSensors />);
    await userEvent.click(
      screen.getAllByRole('button', { name: /connect|连接/i })[0],
    );
    await waitFor(() => {
      expect(screen.getByText(/Connect Chrome/)).toBeInTheDocument();
    });
  });

  it('hides cards for excludePluginIds', () => {
    mockUseAvailability.mockReturnValue({
      entries: [
        { plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' },
      ],
      byId: {} as any,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors excludePluginIds={['chrome-history']} />);
    expect(
      screen.queryByText('emptyState.plugins.chromeHistory.title'),
    ).not.toBeInTheDocument();
  });
});
