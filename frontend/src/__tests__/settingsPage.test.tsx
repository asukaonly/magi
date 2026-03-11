import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SettingsPage } from '@/pages/Settings';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { memoryApi } from '@/api/modules/memory';
import { timelineApi } from '@/api/modules/timeline';

vi.mock('@/components/config-forms/LLMForm', () => ({
  default: ({ value, onChange }: { value: any; onChange: (next: any) => void }) => (
    <button type="button" onClick={() => onChange({ ...value, model: 'gpt-5' })}>
      change-llm
    </button>
  ),
}));

vi.mock('@/components/config-forms/DynamicToolConfig', () => ({
  DynamicToolsConfig: () => <div>tools-config</div>,
}));

vi.mock('@/components/settings/LLMUsageSection', () => ({
  LLMUsageSection: () => <div>usage-section</div>,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
      update: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    listModels: vi.fn(),
    downloadModel: vi.fn(),
    getModelStatus: vi.fn(),
    clearAll: vi.fn(),
  },
}));

vi.mock('@/api/modules/timeline', () => ({
  timelineApi: {
    getSourceStatus: vi.fn(),
    requestSync: vi.fn(),
  },
}));

describe('settings page save behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(configApi.get).mockResolvedValue({
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(configApi.update).mockResolvedValue({
      success: true,
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(memoryApi.listModels).mockResolvedValue({
      data: { models: [] },
    } as any);
    vi.mocked(timelineApi.getSourceStatus).mockResolvedValue({
      sources: [
        {
          source_name: 'browser_history',
          enabled: true,
          sync_mode: 'interval',
          sync_interval_minutes: 30,
          default_retention_mode: 'analyze_only',
          storage_mode: 'managed',
          source_path: '/tmp/browser-history',
          fetch_page_content: false,
          edge_whitelist: ['VIEWED', 'VISITED', 'CARES_ABOUT', 'LIKES'],
          last_error: 'Permission denied',
          last_success: null,
          runtime_base_dir: '/tmp/magi-runtime',
        },
      ],
    } as any);
    vi.mocked(timelineApi.requestSync).mockResolvedValue({
      queued: true,
      source_name: 'browser_history',
    } as any);
  });

  it('auto-saves non-llm settings after edits', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.system' }));

    const loopIntervalInput = screen.getAllByRole('spinbutton')[0];
    fireEvent.change(loopIntervalInput, { target: { value: '2' } });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });

    await waitFor(() => expect(configApi.update).toHaveBeenCalledTimes(1));
    expect(configApi.update).toHaveBeenCalledWith(
      expect.objectContaining({
        loop: expect.objectContaining({ interval: 2 }),
      })
    );
  });

  it('keeps llm changes local until the llm save button is clicked', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.llm' }));
    await user.click(screen.getByRole('button', { name: 'change-llm' }));

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });

    expect(configApi.update).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.saveLLM' }));

    await waitFor(() => expect(configApi.update).toHaveBeenCalledTimes(1));
    expect(configApi.update).toHaveBeenCalledWith(
      expect.objectContaining({
        llm: expect.objectContaining({ model: 'gpt-5' }),
      })
    );
  });

  it('auto-saves timeline source edits after changes', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.timeline' }));
    await screen.findByText('settings.timeline.title');

    const browserCard = await screen.findByTestId('timeline-source-browser_history');

    await user.click(within(browserCard).getByRole('switch', { name: 'settings.timeline.fields.enabled' }));

    fireEvent.change(within(browserCard).getByLabelText('settings.timeline.fields.retentionMode'), {
      target: { value: 'retain_raw' },
    });
    fireEvent.change(within(browserCard).getByLabelText('settings.timeline.fields.syncInterval'), {
      target: { value: '45' },
    });
    await user.click(within(browserCard).getByRole('switch', { name: 'settings.timeline.fields.fetchPageContent' }));

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });

    await waitFor(() => expect(configApi.update).toHaveBeenCalled());
    expect(configApi.update).toHaveBeenLastCalledWith(
      expect.objectContaining({
        timeline: expect.objectContaining({
          sources: expect.objectContaining({
            browser_history: expect.objectContaining({
              enabled: false,
              default_retention_mode: 'retain_raw',
              sync_interval_minutes: 45,
              fetch_page_content: true,
            }),
          }),
        }),
      })
    );
  });

  it('shows expert-only edge controls and source status metadata', async () => {
    const user = userEvent.setup();
    const expertConfig = structuredClone(DEFAULT_SYSTEM_CONFIG);
    expertConfig.preferences.user_mode = 'expert';
    vi.mocked(configApi.get).mockResolvedValueOnce({
      data: expertConfig,
    } as any);

    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.timeline' }));

    const browserCard = await screen.findByTestId('timeline-source-browser_history');

    expect(await within(browserCard).findByText('Permission denied')).toBeInTheDocument();
    expect(within(browserCard).getByLabelText('settings.timeline.fields.edgeWhitelist')).toHaveValue(
      'VIEWED, VISITED, CARES_ABOUT, LIKES'
    );
    expect(within(browserCard).getByLabelText('settings.timeline.fields.sourcePath')).toHaveValue(
      '/tmp/browser-history'
    );
  });
});
