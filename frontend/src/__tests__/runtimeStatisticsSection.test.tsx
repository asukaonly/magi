import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RuntimeStatisticsSection } from '@/components/settings/RuntimeStatisticsSection';
import { metricsApi } from '@/api/modules/metrics';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/api/modules/metrics', () => ({ metricsApi: { getRuntimeOverview: vi.fn() } }));
vi.mock('recharts', () => ({
  ResponsiveContainer: () => null, LineChart: () => null, Line: () => null,
  CartesianGrid: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null,
}));

beforeEach(() => { vi.clearAllMocks(); });

it('shows unavailable owner data while retaining native metrics', async () => {
  vi.mocked(metricsApi.getRuntimeOverview).mockResolvedValue({ success: true, message: '', data: {
    captured_at_ms: 1000, system: { cpu_percent: 12, memory_percent: 34, memory_used_gb: 2, memory_total_gb: 8 },
    runtime: { status: 'degraded', runtime_ready: false, runtime_status: 'disconnected', pending_commands: null },
    model_execution: null, memory: null, scheduler: null,
  } });
  render(<RuntimeStatisticsSection />);
  expect(await screen.findByText('12%')).toBeInTheDocument();
  expect(screen.getAllByText('settings.statistics.shared.unavailable').length).toBeGreaterThan(5);
  expect(screen.queryByText('settings.statistics.runtime.health.queueHealthy')).not.toBeInTheDocument();
});
