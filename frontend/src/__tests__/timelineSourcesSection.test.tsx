import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TimelineSourcesSection } from '@/components/settings/TimelineSourcesSection';
import type { TimelineConfig, UserMode } from '@/api/modules/config';
import type { TimelineSourceStatusItem } from '@/api/modules/timeline';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const timelineSourceFixture: TimelineSourceStatusItem = {
  source_name: 'browser_history',
  plugin_id: 'core-timeline',
  contribution_id: 'timeline.browser_history',
  display_name: 'Browser History',
  description: 'Visited URLs and optional page content snapshots.',
  fields: [
    {
      key: 'sensors.browser_history.enabled',
      type: 'switch',
      label: 'Enabled',
      description: 'Whether this source is active.',
      default: true,
      required: false,
      options: [],
      section: 'general',
      surface: 'timeline',
      order: 10,
    },
  ],
  current_settings: {
    'sensors.browser_history.enabled': true,
  },
  enabled: true,
  sync_mode: 'interval',
  sync_interval_minutes: 30,
  default_retention_mode: 'analyze_only',
  storage_mode: 'managed',
  fetch_page_content: false,
  edge_whitelist: ['VIEWED', 'VISITED'],
  supports_pull_sync: true,
  running: false,
  last_run_at: '2026-03-11T08:58:00Z',
  last_result_count: 4,
  last_raw_result_count: 7,
  last_error: null,
  last_success: null,
  last_sync_at: '2026-03-11T09:00:00Z',
  next_run_at: '2026-03-11T09:30:00Z',
  scheduler_job_id: 'timeline-browser-history',
  runtime_base_dir: '/tmp/magi-runtime',
};

const timelineConfigFixture: TimelineConfig = {
  enabled: true,
  expert_mode_edge_override: false,
  sources: {
    chat: {
      enabled: true,
      sync_mode: 'manual',
      sync_interval_minutes: 1,
      default_retention_mode: 'analyze_only',
      storage_mode: 'managed',
      fetch_page_content: false,
      edge_whitelist: [],
    },
    manual_journal: {
      enabled: true,
      sync_mode: 'manual',
      sync_interval_minutes: 1,
      default_retention_mode: 'retain_raw',
      storage_mode: 'managed',
      fetch_page_content: false,
      edge_whitelist: [],
    },
    browser_history: {
      enabled: true,
      sync_mode: 'interval',
      sync_interval_minutes: 30,
      default_retention_mode: 'analyze_only',
      storage_mode: 'managed',
      fetch_page_content: false,
      edge_whitelist: ['VIEWED', 'VISITED'],
    },
    photo_library: {
      enabled: false,
      sync_mode: 'manual',
      sync_interval_minutes: 60,
      default_retention_mode: 'analyze_only',
      storage_mode: 'managed',
      fetch_page_content: false,
      edge_whitelist: [],
    },
  },
};

const userModeFixture: UserMode = 'quick';

describe('TimelineSourcesSection', () => {
  it('does not repeat an overview title block above the source directory', () => {
    render(
      <TimelineSourcesSection
        value={timelineConfigFixture}
        userMode={userModeFixture}
        statuses={[timelineSourceFixture]}
        loadingStatus={false}
        selectedSourceName={null}
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onChange={vi.fn()}
        onPluginFieldChange={vi.fn()}
        onPluginFieldsChange={vi.fn()}
      />
    );

    expect(screen.queryByText('settings.timeline.workspace.directoryTitle')).not.toBeInTheDocument();
    expect(screen.queryByText('settings.timeline.workspace.directoryDesc')).not.toBeInTheDocument();
    expect(screen.getByText('settings.timeline.workspace.metricsSummary')).toBeInTheDocument();
    expect(screen.getByTestId('timeline-source-launch-browser_history')).toBeInTheDocument();
  });
});
