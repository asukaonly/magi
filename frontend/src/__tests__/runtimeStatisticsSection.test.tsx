import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RuntimeStatisticsSection } from '@/components/settings/RuntimeStatisticsSection';

const { getRuntimeOverviewMock } = vi.hoisted(() => ({
  getRuntimeOverviewMock: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) {
        return key;
      }
      const serialized = Object.entries(options)
        .filter(([, value]) => value !== undefined)
        .map(([name, value]) => `${name}=${String(value)}`)
        .join(',');
      return serialized ? `${key}:${serialized}` : key;
    },
  }),
}));

vi.mock('@/api/modules/metrics', () => ({
  metricsApi: {
    getRuntimeOverview: getRuntimeOverviewMock,
  },
}));

const overviewFixture = {
  captured_at_ms: 1711261800000,
  system: {
    cpu_percent: 26,
    memory_percent: 48,
    memory_used_gb: 5,
    memory_total_gb: 16,
  },
  runtime: {
    status: 'ready',
    runtime_ready: true,
    runtime_status: 'ready',
    runtime_heartbeat_age_ms: 1200,
    queue_backlog_healthy: true,
    pending_commands: 3,
  },
  model_execution: {
    avg_ttft_ms: 420,
    ttft_available: true,
    core_model_success_rate: 91.4,
    core_model_success_rate_available: true,
    intent_success_rate: null,
    intent_success_rate_available: false,
  },
  memory: {
    total_pending: 7,
    l2: {
      is_running: true,
      extract_pending: 1,
      reconcile_pending: 1,
      snapshot_pending: 2,
      total_pending: 4,
    },
    embeddings: {
      total_pending: 3,
      l1: { pending: 2, worker_running: true, vector_enabled: true, async_embeddings: true },
      l3: { pending: 1, worker_running: true, vector_enabled: true, async_embeddings: true },
      l4: { pending: 0, worker_running: false, vector_enabled: true, async_embeddings: true },
    },
  },
  scheduler: {
    enabled_schedule_count: 4,
    running_target_count: 1,
    errored_target_count: 1,
    upcoming_target_count: 3,
    recent_targets: [
      {
        target_type: 'sensor_sync',
        target_key: 'core:history',
        running: true,
        last_error: null,
        next_run_at: 1711261860,
        updated_at: 1711261800,
      },
    ],
  },
};

beforeEach(() => {
  getRuntimeOverviewMock.mockReset();
  getRuntimeOverviewMock.mockResolvedValue({ data: overviewFixture });
  vi.stubGlobal(
    'ResizeObserver',
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

describe('RuntimeStatisticsSection', () => {
  it('renders the shared statistics frame and runtime signals', async () => {
    render(<RuntimeStatisticsSection />);

    await waitFor(() => {
      expect(getRuntimeOverviewMock).toHaveBeenCalledTimes(1);
    });

    expect(screen.queryByRole('heading', { name: 'settings.tabs.statisticsRuntime' })).not.toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-signal-ribbon')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-main-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-summary-rail')).toBeInTheDocument();
    expect(screen.getByText('26%')).toBeInTheDocument();
    expect(screen.getByText('48%')).toBeInTheDocument();
    expect(screen.getByText('420ms')).toBeInTheDocument();
    expect(screen.getByText('91%')).toBeInTheDocument();
    expect(screen.getAllByText('7').length).toBeGreaterThan(0);
  });

  it('shows explicit unavailable copy for metrics that are not connected yet', async () => {
    render(<RuntimeStatisticsSection />);

    await waitFor(() => {
      expect(getRuntimeOverviewMock).toHaveBeenCalledTimes(1);
    });

    expect(screen.getAllByText('settings.statistics.shared.unavailable').length).toBeGreaterThan(0);
  });

  it('supports manual refresh from the toolbar', async () => {
    const user = userEvent.setup();
    getRuntimeOverviewMock
      .mockResolvedValueOnce({ data: overviewFixture })
      .mockResolvedValueOnce({
        data: {
          ...overviewFixture,
          captured_at_ms: overviewFixture.captured_at_ms + 15000,
          system: {
            ...overviewFixture.system,
            cpu_percent: 31,
          },
        },
      });

    render(<RuntimeStatisticsSection />);

    await waitFor(() => {
      expect(getRuntimeOverviewMock).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByRole('button', { name: 'settings.statistics.runtime.refreshAction' }));

    await waitFor(() => {
      expect(getRuntimeOverviewMock).toHaveBeenCalledTimes(2);
    });

    expect(screen.getByText('31%')).toBeInTheDocument();
  });

  it('formats runtime timestamps with a 24-hour clock', async () => {
    const dateTimeFormatSpy = vi.spyOn(Intl, 'DateTimeFormat');

    render(<RuntimeStatisticsSection />);

    await waitFor(() => {
      expect(getRuntimeOverviewMock).toHaveBeenCalledTimes(1);
    });

    expect(dateTimeFormatSpy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    );
    expect(dateTimeFormatSpy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    );
  });
});
