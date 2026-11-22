import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { memoryApi } from '@/api/modules/memory';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import { profileApi } from '@/api/modules/profile';
import { sourcesApi } from '@/api/modules/sources';
import { MemoryPortraitPage, MemorySourceDetailPage } from '@/pages/memory-pages';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const base = String(opts?.defaultValue ?? key);
      return base.replace(/\{\{(\w+)\}\}/g, (_m, name) =>
        name in (opts ?? {}) ? String(opts?.[name]) : `{{${name}}}`
      );
    },
    i18n: { language: 'en', resolvedLanguage: 'en' },
  }),
}));

vi.mock('@/hooks/useInstallableSources', () => ({
  useInstallableSources: () => ({ items: [], loading: false }),
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    getDashboard: vi.fn(),
    getL1Events: vi.fn(),
    deleteL1Event: vi.fn(),
    forgetSource: vi.fn(),
    getCorrectionHistory: vi.fn(),
    revertCorrection: vi.fn(),
    applyCorrection: vi.fn(),
    getCorrectionContextOptions: vi.fn(),
    submitAssertionFeedback: vi.fn(),
  },
}));

vi.mock('@/api/modules/sources', () => ({
  sourcesApi: {
    getStatus: vi.fn(),
    getTodaySummary: vi.fn(),
    getSyncHistory: vi.fn(),
    triggerSync: vi.fn(),
    requestAuthorization: vi.fn(),
  },
}));

vi.mock('@/api/modules/memoryPortraitSelf', () => ({
  memoryPortraitSelfApi: { get: vi.fn() },
}));

vi.mock('@/api/modules/profile', () => ({
  profileApi: { getMe: vi.fn(), updateMe: vi.fn(), refreshMe: vi.fn() },
}));

describe('P1-D1 source detail forgetting and portrait correction history', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(sourcesApi.getStatus).mockResolvedValue({
      sources: [
        {
          source_name: 'chrome_history',
          source_type: 'chrome_history',
          plugin_id: 'chrome-history',
          connection_id: 'conn-chrome',
          connection_display_name: 'Chrome',
          connection_revision: 1,
          enabled: true,
          available: true,
          status: 'ready',
          sync_mode: 'interval',
          running: false,
          supports_pull_sync: true,
          last_sync_at: 1_760_000_000,
          next_run_at: 1_760_003_600,
          last_error: null,
          last_result_count: 2,
          current_settings: {},
          sync_activity: null,
          activation_flow: null,
        },
      ],
    } as never);
    vi.mocked(sourcesApi.getTodaySummary).mockResolvedValue({
      date: '2026-10-01',
      total_events: 2,
      sources: [{ source: 'chrome_history', count: 2 }],
    } as never);
    vi.mocked(sourcesApi.getSyncHistory).mockResolvedValue({ items: [] } as never);
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      source_counts: [{ source: 'chrome_history', count: 2, last_event_at: 1_760_000_000 }],
      pending_items: [],
    } as never);
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({
      items: [
        {
          event_id: 'evt-chrome-1',
          timestamp: 1_760_000_100,
          source: 'chrome_history',
          event_type: 'SOURCE_EVENT',
          content: 'Visited awkward site',
          metadata_json: {},
        },
        {
          event_id: 'evt-chrome-2',
          timestamp: 1_760_000_200,
          source: 'chrome_history',
          event_type: 'SOURCE_EVENT',
          content: 'Visited rust docs',
          metadata_json: {},
        },
      ],
      total: 2,
    } as never);
    vi.mocked(memoryApi.deleteL1Event).mockResolvedValue({
      event_id: 'evt-chrome-1',
      deleted: true,
      deletion_scope: 'source_event',
    });
    vi.mocked(memoryApi.forgetSource).mockResolvedValue({
      source_name: 'chrome_history',
      connection_id: 'conn-chrome',
      l1_events_deleted: 2,
      archived_events_deleted: 0,
    });
  });

  it('forgets a single source record with confirmation and updates the list immediately', async () => {
    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByText('Visited awkward site');
    const forgetBtns = screen.getAllByLabelText('memory.sourcesPage.detail.forgetEventAria');
    expect(forgetBtns).toHaveLength(2);
    fireEvent.click(forgetBtns[0]);

    await screen.findByText('memory.sourcesPage.detail.forgetEventConfirmTitle');
    fireEvent.click(screen.getByRole('button', { name: 'memory.sourcesPage.detail.forgetEventConfirmAction' }));

    await waitFor(() => {
      expect(memoryApi.deleteL1Event).toHaveBeenCalledWith('evt-chrome-1');
    });
    await waitFor(() => {
      expect(screen.queryByText('Visited awkward site')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Visited rust docs')).toBeInTheDocument();
  });

  it('clears all stored records from a source via the more menu confirmation dialog', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByText('Visited awkward site');
    await user.click(screen.getByLabelText('memory.sourcesPage.actions.more'));
    const clearItem = await screen.findByText('memory.sourcesPage.actions.clearRecords');
    await user.click(clearItem);

    await screen.findByText('memory.sourcesPage.detail.clearRecordsConfirmTitle');
    await user.click(screen.getByRole('button', { name: 'memory.sourcesPage.detail.clearRecordsConfirmAction' }));

    await waitFor(() => {
      expect(memoryApi.forgetSource).toHaveBeenCalledWith('chrome_history', 'conn-chrome');
    });
  });

  it('exposes correction history drawer and revert directly on MemoryPortraitPage without expert mode', async () => {
    vi.mocked(profileApi.getMe).mockResolvedValue({
      user_id: 'user-1',
      entity_id: 'entity-1',
      display_name: 'Asuka',
      preferred_form_of_address: 'Asuka',
      real_name: '',
      birth_date: '',
      birth_year: null,
      age_years: null,
      age_as_of: '',
      home_location: '',
      communication: {},
      identity: {},
      preferences: {},
      state: {},
      field_sources: {},
      field_conflicts: {},
      completeness_score: 0.5,
      refreshed_at: 0,
      created_at: 0,
      updated_at: 0,
    } as never);
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      is_stale: false,
      is_cold_start: false,
      cold_start_line: null,
      cold_start_reason: null,
      self_view: {
        world: {
          total_count: 1,
          groups: [
            { id: 'identity', items: [] },
            { id: 'projects', items: [] },
            {
              id: 'preferences',
              items: [
                {
                  id: 'item-1',
                  text: 'Likes indie rock',
                  source: 'conversation',
                  source_key: 'conversation',
                  assertion_id: 'assert-1',
                  correction_value: 'indie rock',
                  correction_trait_name: 'music_preference',
                  correction_value_options: null,
                  display_status: 'complete',
                  basis_count: 2,
                  basis_refs: [],
                  updated_at: 1_760_000_000,
                },
              ],
            },
            { id: 'work_style', items: [] },
          ],
        },
        review: { items: [] },
        recent: { items: [] },
      },
    } as never);
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      corrections: [
        {
          correction_id: 'corr-1',
          target_kind: 'assertion',
          target_id: 'assert-1',
          correction_kind: 'replace',
          state: 'active',
          can_revert: true,
          created_at: 1_760_000_050,
          before_value: 'pop',
          after_value: 'indie rock',
          reason: 'User corrected genre',
        },
      ],
      versions: [],
      context_labels: {},
    } as never);
    vi.mocked(memoryApi.revertCorrection).mockResolvedValue({
      correction_id: 'corr-1',
      reverted: true,
    } as never);

    render(
      <MemoryRouter>
        <MemoryPortraitPage />
      </MemoryRouter>,
    );

    const historyBtn = await screen.findByLabelText(/查看 Likes indie rock 的修正记录/);
    fireEvent.click(historyBtn);

    await screen.findByText('memory.portrait.world.historyDrawerTitle');
    await waitFor(() => {
      expect(memoryApi.getCorrectionHistory).toHaveBeenCalledWith('assertion', 'assert-1');
    });
    const revertBtn = await screen.findByRole('button', { name: '撤销这次修正' });
    fireEvent.click(revertBtn);
    const confirmRevertBtn = await screen.findByRole('button', { name: '确认撤销' });
    fireEvent.click(confirmRevertBtn);

    await waitFor(() => {
      expect(memoryApi.revertCorrection).toHaveBeenCalledWith('corr-1', expect.any(String), 'assertion');
    });
  });
});
