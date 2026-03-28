import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';

import { TimelineSourcesSection } from '@/components/settings/TimelineSourcesSection';
import { pluginsApi } from '@/api/modules/plugins';
import type { UserMode } from '@/api/modules/config';
import type { SensorSourceStatusItem } from '@/api/modules/sensors';

const translationMap: Record<string, string> = {
  'settings.timeline.sources.photo_library': '照片库',
  'settings.timeline.sourceDesc.photo_library': '引用照片库或导出目录，并决定保留多少原始媒体信息。',
  'settings.plugins.chrome-history.name': 'Chrome 历史',
  'settings.plugins.chrome-history.description': '本地 Google Chrome 浏览历史接入时间线',
  'settings.plugins.netease-music.name': '网易云音乐',
  'settings.plugins.netease-music.description': '本地网易云音乐播放历史接入时间线',
  'settings.timeline.fields.enabled': '启用',
  'settings.plugins.photo-library.name': '照片库',
  'settings.timeline.workspace.manualTrigger': '手动触发',
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

vi.mock('@/api/modules/plugins', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/plugins')>('@/api/modules/plugins');
  return {
    ...actual,
    pluginsApi: {
      ...actual.pluginsApi,
      getSettingsResource: vi.fn(),
    },
  };
});

const timelineSourceFixture: SensorSourceStatusItem = {
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
    expect(screen.queryByText('interval · 60m · retain_raw')).not.toBeInTheDocument();
  });

  it('removes the detail back link and shortens the enable label', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[
          {
            ...timelineSourceFixture,
            sync_mode: 'manual',
            next_run_at: null,
          },
        ]}
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
    expect(within(detail).queryByText('interval · 60m · retain_raw')).not.toBeInTheDocument();
    expect(within(detail).getByText('手动触发')).toBeInTheDocument();
    expect(within(detail).queryByText('来源配置')).not.toBeInTheDocument();
    expect(within(detail).queryByText('这些声明式字段会回写到插件配置，并由调度器和运行时消费。')).not.toBeInTheDocument();
  });

  it('keeps status badges on the left and actions on the right in the detail header', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[
          {
            ...timelineSourceFixture,
            activation_flow: {
              title: 'Connect Photo Library',
              description: 'Set up first sync.',
              confirm_label: 'Enable source',
              cancel_label: 'Not now',
              authorize_on_confirm: false,
              enabled_key: 'sensors.photo_library.enabled',
              configured_key: 'sensors.photo_library.initial_sync_configured',
              fields: [],
            },
            current_settings: {
              'sensors.photo_library.enabled': true,
              'sensors.photo_library.initial_sync_configured': true,
            },
          },
        ]}
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
    const statusGroup = within(detail).getByTestId('timeline-source-header-status');
    const actionGroup = within(detail).getByTestId('timeline-source-header-actions');

    expect(within(statusGroup).getByText('settings.timeline.statuses.enabled')).toBeInTheDocument();
    expect(within(statusGroup).getByText('settings.timeline.statuses.healthy')).toBeInTheDocument();
    expect(within(actionGroup).getByText('settings.timeline.actions.resetActivation')).toBeInTheDocument();
    expect(within(actionGroup).getByText('启用')).toBeInTheDocument();
    expect(within(statusGroup).queryByText('settings.timeline.actions.resetActivation')).not.toBeInTheDocument();
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

  it('renders a custom calendar picker block from plugin-declared ui blocks', async () => {
    vi.mocked(pluginsApi.getSettingsResource).mockResolvedValue({
      plugin_id: 'calendar',
      resource_name: 'calendar_lists',
      resource_type: 'collection',
      data: {
        groups: [
          {
            group_id: 'icloud',
            label: 'iCloud',
            items: [
              {
                item_id: 'calendar-personal',
                label: '个人',
                description: 'Primary',
                accent_color: '#2F80ED',
              },
              {
                item_id: 'calendar-work',
                label: '工作',
                description: 'Team',
                accent_color: '#D946EF',
              },
            ],
          },
        ],
      },
    });
    const onPluginFieldChange = vi.fn();
    const user = userEvent.setup();

    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[
          {
            ...timelineSourceFixture,
            source_name: 'calendar',
            plugin_id: 'calendar',
            contribution_id: 'timeline.calendar',
            display_name: 'Calendar',
            description: 'Calendar event ingestion for the timeline.',
            fields: [
              {
                ...timelineSourceFixture.fields[0],
                key: 'sensors.calendar.enabled',
              },
            ],
            current_settings: {
              'sensors.calendar.enabled': true,
              'sensors.calendar.authorization_configured': true,
              'sensors.calendar.selected_calendar_ids': ['calendar-personal'],
            },
            settings_ui_blocks: [
              {
                block_id: 'selected_calendars',
                type: 'resource_picker',
                resource_name: 'calendar_lists',
                value_key: 'sensors.calendar.selected_calendar_ids',
                title: 'settings.plugins.calendar.ui_blocks.selected_calendars.title',
                description: 'settings.plugins.calendar.ui_blocks.selected_calendars.description',
                presentation: 'calendar_list',
                depends_on_key: 'sensors.calendar.authorization_configured',
                depends_on_values: ['true'],
              },
            ],
          } as SensorSourceStatusItem,
        ]}
        loadingStatus={false}
        selectedSourceName="calendar"
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onPluginFieldChange={onPluginFieldChange}
        onPluginFieldsChange={vi.fn()}
      />
    );

    await waitFor(() => expect(pluginsApi.getSettingsResource).toHaveBeenCalledWith('calendar', 'calendar_lists'));
    expect(screen.getByText('iCloud')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '个人' })).toBeChecked();

    await user.click(screen.getByRole('checkbox', { name: '工作' }));

    expect(onPluginFieldChange).toHaveBeenCalledWith('calendar', 'sensors.calendar.selected_calendar_ids', [
      'calendar-personal',
      'calendar-work',
    ]);
  });

  it('uses calendar fields without exposing retention mode and only shows interval controls when scheduled', () => {
    render(
      <TimelineSourcesSection
        userMode={userModeFixture}
        statuses={[
          {
            ...timelineSourceFixture,
            source_name: 'calendar',
            plugin_id: 'calendar',
            contribution_id: 'timeline.calendar',
            display_name: 'Calendar',
            description: 'Calendar event ingestion for the timeline.',
            fields: [
              {
                ...timelineSourceFixture.fields[0],
                key: 'sensors.calendar.enabled',
              },
              {
                key: 'sensors.calendar.sync_mode',
                type: 'select',
                label: 'Sync Mode',
                description: 'Choose manual or interval sync.',
                default: 'interval',
                required: false,
                options: [
                  { label: 'Manual', value: 'manual' },
                  { label: 'Interval', value: 'interval' },
                ],
                section: 'sync',
                surface: 'timeline',
                order: 20,
              },
              {
                key: 'sensors.calendar.sync_interval_minutes',
                type: 'select',
                label: 'Sync Interval',
                description: 'How often to sync calendar events.',
                default: '30',
                required: false,
                options: [
                  { label: 'Manual only', value: 'manual' },
                  { label: '30 minutes', value: '30' },
                ],
                section: 'sync',
                surface: 'timeline',
                order: 30,
                depends_on_key: 'sensors.calendar.sync_mode',
                depends_on_values: ['interval'],
              },
            ],
            current_settings: {
              'sensors.calendar.enabled': true,
              'sensors.calendar.sync_mode': 'manual',
              'sensors.calendar.sync_interval_minutes': 30,
            },
            sync_mode: 'manual',
            next_run_at: null,
          },
        ]}
        loadingStatus={false}
        selectedSourceName="calendar"
        pluginDrafts={{}}
        onSelectSource={vi.fn()}
        onRefreshSources={vi.fn().mockResolvedValue(undefined)}
        onPluginFieldChange={vi.fn()}
        onPluginFieldsChange={vi.fn()}
      />
    );

    const detail = screen.getByTestId('timeline-source-detail-calendar');

    expect(within(detail).getByText('Sync Mode')).toBeInTheDocument();
    expect(within(detail).queryByText('Retention Mode')).not.toBeInTheDocument();
    expect(within(detail).queryByText('Sync Interval')).not.toBeInTheDocument();
  });
});
