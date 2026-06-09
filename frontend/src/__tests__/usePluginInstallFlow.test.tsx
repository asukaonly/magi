import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { sensorsApi } from '@/api/modules/sensors';
import { pluginsApi } from '@/api/modules/plugins';
import { usePluginInstallFlow } from '@/hooks/usePluginInstallFlow';

const FLOW = (fields: any[] = []) => ({
  title: 't',
  description: 'd',
  confirm_label: 'c',
  cancel_label: 'x',
  authorize_on_confirm: false,
  enabled_key: 'sensors.s.enabled',
  configured_key: 'sensors.s.configured',
  fields,
});

const source = (over: any = {}) => ({
  source_name: 's',
  plugin_id: 'p',
  activation_flow: FLOW(),
  enabled: false,
  running: false,
  last_result_count: 0,
  last_success: null,
  ...over,
});

describe('usePluginInstallFlow', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('zero-config installed: enable → sync → memory → done', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({ sources: [source()] } as any) // initial flow fetch
      .mockResolvedValue({
        sources: [source({ last_success: '2026-01-01T00:00:01Z', last_result_count: 12 })],
      } as any); // sync poll: advanced
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 's',
      l1_event_count: 12,
      l2_ready: true,
    } as any);

    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(pluginsApi.updateSettings).toHaveBeenCalledWith(
      'p',
      expect.objectContaining({
        'sensors.s.enabled': true,
        'sensors.s.configured': true,
      }),
    );
    expect(result.current.syncedCount).toBe(12);
    expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('done');
    expect(result.current.memoryReady).toBe(true);
  });

  it('with fields: waits for submit before enabling', async () => {
    const withFields = (over: any = {}) =>
      source({
        activation_flow: FLOW([
          { key: 'sensors.s.source_paths', type: 'path', label: 'dirs', required: true, default: [] },
        ]),
        ...over,
      });
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({ sources: [withFields()] } as any) // initial flow fetch (last_success: null)
      .mockResolvedValue({
        sources: [withFields({ last_success: '2026-01-01T00:00:01Z', last_result_count: 1 })],
      } as any); // sync poll: advanced
    const upd = vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 's',
      l1_event_count: 1,
      l2_ready: true,
    } as any);

    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await waitFor(() => expect(result.current.phase).toBe('awaiting_fields'));
    expect(upd).not.toHaveBeenCalled();
    await act(async () => {
      result.current.submitFields({ 'sensors.s.source_paths': ['/x'] });
    });
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(upd).toHaveBeenCalledWith('p', expect.objectContaining({ 'sensors.s.source_paths': ['/x'] }));
  });

  it('no activation_flow → unsupported (no silent no-op)', async () => {
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({
      sources: [source({ activation_flow: null })],
    } as any);
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await waitFor(() => expect(result.current.phase).toBe('unsupported'));
  });

  it('memory not ready in bounded time → done with backfill note (no fake ✓)', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({ sources: [source()] } as any)
      .mockResolvedValue({
        sources: [source({ last_success: '2026-01-01T00:00:01Z', last_result_count: 3 })],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 's',
      l1_event_count: 3,
      l2_ready: false,
    } as any);

    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(result.current.memoryReady).toBe(false);
    expect(result.current.backfillNote).toBe(true);
    expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('done'); // soft-done, labelled "整理中"
  });

  it('install-mode runs install first, then fetches the flow', async () => {
    const inst = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockImplementation(async (_id, onP) => {
        onP?.({
          stage: 'downloading',
          progress_pct: 50,
          status: 'running',
          message: '',
          job_id: 'j',
          operation: 'install',
        } as any);
        return {} as any;
      });
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({ sources: [source()] } as any)
      .mockResolvedValue({
        sources: [source({ last_success: '2026-01-01T00:00:01Z', last_result_count: 4 })],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 's',
      l1_event_count: 4,
      l2_ready: true,
    } as any);

    const { result } = renderHook(() => usePluginInstallFlow('p', true));
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(inst).toHaveBeenCalledWith('p', expect.any(Function));
    expect(result.current.steps.find((s) => s.id === 'install')?.status).toBe('done');
  });
});
