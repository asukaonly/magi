import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TimelineSourcesSection } from '@/components/settings/TimelineSourcesSection';
import type { UserMode } from '@/api/modules/config';
import type { TimelineSourceStatusItem } from '@/api/modules/timeline';

const translationMap: Record<string, string> = {
  'settings.timeline.sources.photo_library': '照片库',
  'settings.timeline.sourceDesc.photo_library': '引用照片库或导出目录，并决定保留多少原始媒体信息。',
  'settings.plugins.chrome-history.name': 'Chrome 历史',
  'settings.plugins.chrome-history.description': '本地 Google Chrome 浏览历史接入时间线',
  'settings.plugins.netease-music.name': '网易云音乐',
  'settings.plugins.netease-music.description': '本地网易云音乐播放历史接入时间线',
  'settings.timeline.fields.enabled': '启用',
  'settings.plugins.photo-library.name': '照片库',
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
  source_name: 'photo_library',
  plugin_id: 'photo-library',
  contribution_id: 'timeline.photo_library',
  display_name: 'Photo Library',
  description: 'Photo assets referenced from a local library path.',
  fields: [
    {
      key: 'sensors.photo_library.enabled',
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
    'sensors.photo_library.enabled': true,
  },
  enabled: true,
  sync_mode: 'interval',
  sync_interval_minutes: 60,
  default_retention_mode: 'retain_raw',
  storage_mode: 'external_reference',
  fetch_page_content: false,
  edge_whitelist: ['CAPTURED', 'RELATED_TO'],
  supports_pull_sync: false,
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
    expect(screen.getByTestId('timeline-source-launch-photo_library')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.timeline.actions.refresh' })).not.toBeInTheDocument();
    expect(screen.getByText('照片库')).toBeInTheDocument();
    expect(screen.getByText('引用照片库或导出目录，并决定保留多少原始媒体信息。')).toBeInTheDocument();
    expect(screen.queryByText('Photo Library')).not.toBeInTheDocument();
    expect(screen.queryByText('Photo assets referenced from a local library path.')).not.toBeInTheDocument();
  });

  it('removes the detail back link and shortens the enable label', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[timelineSourceFixture]}
        loadingStatus={false}
        selectedSourceName="photo_library"
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onPluginFieldChange={vi.fn()}
        onPluginFieldsChange={vi.fn()}
      />
    );

    const detail = screen.getByTestId('timeline-source-detail-photo_library');

    expect(screen.queryByText('settings.timeline.workspace.backToOverview')).not.toBeInTheDocument();
    expect(screen.getByText('启用')).toBeInTheDocument();
    expect(within(detail).queryByText('来源启用')).not.toBeInTheDocument();
  });

  it('prefers the source display name over the plugin name fallback', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[
          {
            ...timelineSourceFixture,
            source_name: 'mystery_source',
            contribution_id: 'timeline.mystery_source',
            display_name: 'Mystery Source',
            description: 'A built-in timeline capability.',
            fields: [
              {
                ...timelineSourceFixture.fields[0],
                key: 'sensors.mystery_source.enabled',
              },
            ],
            current_settings: {
              'sensors.mystery_source.enabled': true,
            },
          },
        ]}
        loadingStatus={false}
        selectedSourceName={null}
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onPluginFieldChange={vi.fn()}
        onPluginFieldsChange={vi.fn()}
      />
    );

    expect(screen.getByText('Mystery Source')).toBeInTheDocument();
    expect(screen.queryByText('核心时间线')).not.toBeInTheDocument();
  });

  it('uses plugin i18n before falling back to backend english labels', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[
          {
            ...timelineSourceFixture,
            source_name: 'chrome_history',
            plugin_id: 'chrome-history',
            contribution_id: 'timeline.chrome_history',
            display_name: 'Chrome History',
            description: 'Local Google Chrome browsing history ingested into the user timeline.',
            fields: [
              {
                ...timelineSourceFixture.fields[0],
                key: 'sensors.chrome_history.enabled',
              },
            ],
            current_settings: {
              'sensors.chrome_history.enabled': false,
            },
            enabled: false,
            supports_pull_sync: false,
          },
          {
            ...timelineSourceFixture,
            source_name: 'netease_music',
            plugin_id: 'netease-music',
            contribution_id: 'timeline.netease_music',
            display_name: 'NetEase Cloud Music',
            description: 'Local NetEase Cloud Music play history ingestion for the timeline.',
            fields: [
              {
                ...timelineSourceFixture.fields[0],
                key: 'sensors.netease_music.enabled',
              },
            ],
            current_settings: {
              'sensors.netease_music.enabled': false,
            },
            enabled: false,
            supports_pull_sync: false,
          },
        ]}
        loadingStatus={false}
        selectedSourceName={null}
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onPluginFieldChange={vi.fn()}
        onPluginFieldsChange={vi.fn()}
      />
    );

    expect(screen.getByText('Chrome 历史')).toBeInTheDocument();
    expect(screen.getByText('本地 Google Chrome 浏览历史接入时间线')).toBeInTheDocument();
    expect(screen.getByText('网易云音乐')).toBeInTheDocument();
    expect(screen.getByText('本地网易云音乐播放历史接入时间线')).toBeInTheDocument();
    expect(screen.queryByText('Chrome History')).not.toBeInTheDocument();
    expect(screen.queryByText('NetEase Cloud Music')).not.toBeInTheDocument();
  });
});
