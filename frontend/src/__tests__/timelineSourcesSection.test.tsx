import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TimelineSourcesSection } from '@/components/settings/TimelineSourcesSection';
import type { UserMode } from '@/api/modules/config';
import type { TimelineSourceStatusItem } from '@/api/modules/timeline';

const translationMap: Record<string, string> = {
  'settings.tabs.browser_history': '浏览记录',
  'settings.timeline.sourceDesc.browser_history': '分析浏览行为，并控制是否继续抓取页面正文。',
  'settings.timeline.fields.enabled': '启用',
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => translationMap[key] ?? key,
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

const userModeFixture: UserMode = 'quick';

describe('TimelineSourcesSection', () => {
  it('removes overview chrome and prefers translated source copy', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[timelineSourceFixture]}
        loadingStatus={false}
        selectedSourceName={null}
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onPluginFieldChange={vi.fn()}
        onPluginFieldsChange={vi.fn()}
      />
    );

    const overview = screen.getByTestId('timeline-overview');

    expect(screen.queryByText('settings.timeline.workspace.directoryTitle')).not.toBeInTheDocument();
    expect(screen.queryByText('settings.timeline.workspace.directoryDesc')).not.toBeInTheDocument();
    expect(screen.queryByText('settings.timeline.fields.timelineEnabled')).not.toBeInTheDocument();
    expect(screen.queryByText('settings.timeline.fields.edgeOverride')).not.toBeInTheDocument();
    expect(screen.queryByText('settings.timeline.workspace.metricsSummary')).not.toBeInTheDocument();
    expect(overview).not.toHaveClass('max-w-5xl');
    expect(screen.getByTestId('timeline-source-launch-browser_history')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.timeline.actions.refresh' })).not.toBeInTheDocument();
    expect(screen.getByText('浏览记录')).toBeInTheDocument();
    expect(screen.getByText('分析浏览行为，并控制是否继续抓取页面正文。')).toBeInTheDocument();
    expect(screen.queryByText('Browser History')).not.toBeInTheDocument();
    expect(screen.queryByText('Visited URLs and optional page content snapshots.')).not.toBeInTheDocument();
  });

  it('removes the detail back link and shortens the enable label', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[timelineSourceFixture]}
        loadingStatus={false}
        selectedSourceName="browser_history"
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onPluginFieldChange={vi.fn()}
        onPluginFieldsChange={vi.fn()}
      />
    );

    const detail = screen.getByTestId('timeline-source-detail-browser_history');

    expect(screen.queryByText('settings.timeline.workspace.backToOverview')).not.toBeInTheDocument();
    expect(screen.getByText('启用')).toBeInTheDocument();
    expect(within(detail).queryByText('来源启用')).not.toBeInTheDocument();
  });
});
