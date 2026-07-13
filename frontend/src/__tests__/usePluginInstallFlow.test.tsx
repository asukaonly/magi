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
      l2_total_count: 12,
      l2_processed_count: 12,
      l2_remaining_count: 0,
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
    expect(result.current.memoryTotalCount).toBe(12);
    expect(result.current.memoryProcessedCount).toBe(12);
    expect(result.current.memoryRemainingCount).toBe(0);
  });

  it('finishes zero memory input without a background organizing note', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({ sources: [source()] } as any)
      .mockResolvedValue({
        sources: [
          source({
            last_success: '2026-01-01T00:00:01Z',
            last_result_count: 0,
            last_raw_result_count: 7,
          }),
        ],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 's',
      l1_event_count: 0,
      l2_ready: false,
      l2_total_count: 0,
      l2_processed_count: 0,
      l2_remaining_count: 0,
    } as any);

    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(sensorsApi.getMemoryReadiness).toHaveBeenCalledTimes(1);
    expect(result.current.syncedCount).toBe(0);
    expect(result.current.syncedRawCount).toBe(7);
    expect(result.current.memoryReady).toBe(false);
    expect(result.current.memoryTotalCount).toBe(0);
    expect(result.current.memoryProcessedCount).toBe(0);
    expect(result.current.backfillNote).toBe(false);
  });

  it('does not check memory when sync has not completed yet', async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(sensorsApi, 'getStatus')
        .mockResolvedValueOnce({ sources: [source()] } as any)
        .mockResolvedValue({ sources: [source({ last_success: null })] } as any);
      vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
      vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
        queued: true,
        source_name: 's',
      } as any);
      const readinessSpy = vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
        source_name: 's',
        l1_event_count: 0,
        l2_ready: false,
      } as any);

      const { result } = renderHook(() => usePluginInstallFlow('p', false));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(95_000);
      });

      expect(result.current.phase).toBe('done');
      expect(result.current.syncDeferred).toBe(true);
      expect(result.current.backfillNote).toBe(true);
      expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('skipped');
      expect(readinessSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
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
      l2_total_count: 1,
      l2_processed_count: 1,
      l2_remaining_count: 0,
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

  it('uses optional field defaults in first-context mode when a plugin declares no overrides', async () => {
    const chromeFlow = () => ({
      title: 't',
      description: 'd',
      confirm_label: 'c',
      cancel_label: 'x',
      authorize_on_confirm: false,
      enabled_key: 'sensors.chrome_history.enabled',
      configured_key: 'sensors.chrome_history.initial_sync_configured',
      fields: [
        {
          key: 'sensors.chrome_history.initial_sync_policy',
          type: 'select',
          label: 'scope',
          required: false,
          default: 'lookback_days',
        },
        {
          key: 'sensors.chrome_history.initial_sync_lookback_days',
          type: 'number',
          label: 'days',
          required: false,
          default: 7,
        },
      ],
    });
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          source({
            plugin_id: 'chrome-history',
            source_name: 'chrome_history',
            activation_flow: chromeFlow(),
          }),
        ],
      } as any)
      .mockResolvedValue({
        sources: [
          source({
            plugin_id: 'chrome-history',
            source_name: 'chrome_history',
            activation_flow: chromeFlow(),
            last_success: '2026-01-01T00:00:01Z',
            last_result_count: 2,
          }),
        ],
    } as any);
    const upd = vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    const requestSync = vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
      queued: true,
      source_name: 'chrome_history',
    } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 'chrome_history',
      l1_event_count: 2,
      l2_ready: true,
      l2_total_count: 2,
      l2_processed_count: 2,
      l2_remaining_count: 0,
    } as any);

    const { result } = renderHook(() =>
      usePluginInstallFlow('chrome-history', false, 'first_context'),
    );
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(result.current.flow?.fields).toEqual([]);

    expect(upd).toHaveBeenCalledWith(
      'chrome-history',
      expect.objectContaining({
        'sensors.chrome_history.enabled': true,
        'sensors.chrome_history.initial_sync_configured': true,
        'sensors.chrome_history.initial_sync_policy': 'lookback_days',
        'sensors.chrome_history.initial_sync_lookback_days': 7,
        'sensors.chrome_history.max_items_per_sync': 200,
      }),
    );
    expect(requestSync).toHaveBeenCalledWith('chrome_history', { firstContext: true });
  });

  it('skips fields covered by plugin-declared first-context overrides', async () => {
    const firstContextFlow = () => ({
      title: 't',
      description: 'd',
      confirm_label: 'c',
      cancel_label: 'x',
      authorize_on_confirm: false,
      enabled_key: 'sensors.agent_history.enabled',
      configured_key: 'sensors.agent_history.configured',
      first_context: {
        settings_overrides: {
          'sensors.agent_history.initial_sync_policy': 'lookback_days',
          'sensors.agent_history.initial_sync_lookback_days': 14,
          'sensors.agent_history.max_items_per_sync': 200,
        },
      },
      fields: [
        {
          key: 'sensors.agent_history.initial_sync_policy',
          type: 'select',
          label: 'scope',
          required: false,
          default: 'lookback_days',
        },
        {
          key: 'sensors.agent_history.initial_sync_lookback_days',
          type: 'number',
          label: 'days',
          required: false,
          default: 30,
        },
      ],
    });
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          source({
            plugin_id: 'agent-history',
            source_name: 'agent_history',
            activation_flow: firstContextFlow(),
          }),
        ],
      } as any)
      .mockResolvedValue({
        sources: [
          source({
            plugin_id: 'agent-history',
            source_name: 'agent_history',
            activation_flow: firstContextFlow(),
            last_success: '2026-01-01T00:00:01Z',
            last_result_count: 3,
          }),
        ],
      } as any);
    const upd = vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
      queued: true,
      source_name: 'agent_history',
    } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 'agent_history',
      l1_event_count: 3,
      l2_ready: true,
      l2_total_count: 3,
      l2_processed_count: 3,
      l2_remaining_count: 0,
    } as any);

    const { result } = renderHook(() =>
      usePluginInstallFlow('agent-history', false, 'first_context'),
    );
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(result.current.flow?.fields).toEqual([]);

    expect(upd).toHaveBeenCalledWith(
      'agent-history',
      expect.objectContaining({
        'sensors.agent_history.enabled': true,
        'sensors.agent_history.configured': true,
        'sensors.agent_history.initial_sync_policy': 'lookback_days',
        'sensors.agent_history.initial_sync_lookback_days': 14,
        'sensors.agent_history.max_items_per_sync': 200,
      }),
    );
  });

  it('finishes first-context once raw context is available without waiting for full memory organizing', async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(sensorsApi, 'getStatus')
        .mockResolvedValueOnce({
          sources: [
            source({
              plugin_id: 'chrome-history',
              source_name: 'chrome_history',
            }),
          ],
        } as any)
        .mockResolvedValue({
          sources: [
            source({
              plugin_id: 'chrome-history',
              source_name: 'chrome_history',
              last_success: '2026-01-01T00:00:01Z',
              last_result_count: 125,
            }),
          ],
        } as any);
      vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
      vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
        queued: true,
        source_name: 'chrome_history',
      } as any);
      const readinessSpy = vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
        source_name: 'chrome_history',
        l1_event_count: 125,
        l2_ready: false,
        l2_total_count: 125,
        l2_processed_count: 101,
        l2_remaining_count: 24,
      } as any);

      const { result } = renderHook(() =>
        usePluginInstallFlow('chrome-history', false, 'first_context'),
      );

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });

      expect(result.current.phase).toBe('done');
      expect(result.current.memoryReady).toBe(false);
      expect(result.current.backfillNote).toBe(false);
      expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('done');
      expect(readinessSpy).toHaveBeenCalledTimes(1);
      expect(readinessSpy).toHaveBeenCalledWith('chrome_history', { maxWaitMs: 0 });
    } finally {
      vi.useRealTimers();
    }
  });

  it('still asks for first-context fields that are not covered by overrides', async () => {
    const partialOverrideFlow = () => ({
      title: 't',
      description: 'd',
      confirm_label: 'c',
      cancel_label: 'x',
      authorize_on_confirm: false,
      enabled_key: 'sensors.agent_history.enabled',
      configured_key: 'sensors.agent_history.configured',
      first_context: {
        settings_overrides: {
          'sensors.agent_history.initial_sync_lookback_days': 14,
        },
      },
      fields: [
        {
          key: 'sensors.agent_history.source_paths',
          type: 'path',
          label: 'folders',
          required: true,
          default: [],
        },
        {
          key: 'sensors.agent_history.initial_sync_lookback_days',
          type: 'number',
          label: 'days',
          required: false,
          default: 30,
        },
      ],
    });
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          source({
            plugin_id: 'agent-history',
            source_name: 'agent_history',
            activation_flow: partialOverrideFlow(),
          }),
        ],
      } as any)
      .mockResolvedValue({
        sources: [
          source({
            plugin_id: 'agent-history',
            source_name: 'agent_history',
            activation_flow: partialOverrideFlow(),
            last_success: '2026-01-01T00:00:01Z',
            last_result_count: 3,
          }),
        ],
      } as any);
    const upd = vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
      queued: true,
      source_name: 'agent_history',
    } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 'agent_history',
      l1_event_count: 3,
      l2_ready: true,
      l2_total_count: 3,
      l2_processed_count: 3,
      l2_remaining_count: 0,
    } as any);

    const { result } = renderHook(() =>
      usePluginInstallFlow('agent-history', false, 'first_context'),
    );
    await waitFor(() => expect(result.current.phase).toBe('awaiting_fields'));
    expect(result.current.flow?.fields.map((field) => field.key)).toEqual([
      'sensors.agent_history.source_paths',
    ]);
    await act(async () => {
      result.current.submitFields({ 'sensors.agent_history.source_paths': ['/x'] });
    });
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });

    expect(upd).toHaveBeenCalledWith(
      'agent-history',
      expect.objectContaining({
        'sensors.agent_history.enabled': true,
        'sensors.agent_history.configured': true,
        'sensors.agent_history.source_paths': ['/x'],
        'sensors.agent_history.initial_sync_lookback_days': 14,
      }),
    );
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
    vi.spyOn(sensorsApi, 'getMemoryReadiness')
      .mockResolvedValueOnce({
        source_name: 's',
        l1_event_count: 3,
        l2_ready: false,
        l2_total_count: 3,
        l2_processed_count: 1,
        l2_remaining_count: 2,
      } as any)
      .mockResolvedValue({
        source_name: 's',
        l1_event_count: 3,
        l2_ready: true,
        l2_total_count: 3,
        l2_processed_count: 3,
        l2_remaining_count: 0,
      } as any);

    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(sensorsApi.getMemoryReadiness).toHaveBeenCalledTimes(2);
    expect(result.current.memoryReady).toBe(true);
    expect(result.current.memoryTotalCount).toBe(3);
    expect(result.current.memoryProcessedCount).toBe(3);
    expect(result.current.memoryRemainingCount).toBe(0);
    expect(result.current.backfillNote).toBe(false);
    expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('done'); // soft-done, labelled "整理中"
  });

  it('memory not ready by the deadline → done with latest progress and backfill note', async () => {
    vi.useFakeTimers();
    try {
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
        l2_total_count: 3,
        l2_processed_count: 1,
        l2_remaining_count: 2,
      } as any);

      const { result } = renderHook(() => usePluginInstallFlow('p', false));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(result.current.phase).toBe('done');
      expect(result.current.memoryReady).toBe(false);
      expect(result.current.memoryProcessedCount).toBe(1);
      expect(result.current.memoryRemainingCount).toBe(2);
      expect(result.current.backfillNote).toBe(true);
      expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('background');
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps refreshing background memory progress while the panel remains open', async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(sensorsApi, 'getStatus')
        .mockResolvedValueOnce({ sources: [source()] } as any)
        .mockResolvedValue({
          sources: [source({ last_success: '2026-01-01T00:00:01Z', last_result_count: 3 })],
        } as any);
      vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
      vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
      let ready = false;
      vi.spyOn(sensorsApi, 'getMemoryReadiness').mockImplementation(async () => ({
        source_name: 's',
        l1_event_count: 3,
        l2_ready: ready,
        l2_total_count: 3,
        l2_processed_count: ready ? 3 : 1,
        l2_remaining_count: ready ? 0 : 2,
      }) as any);

      const { result } = renderHook(() => usePluginInstallFlow('p', false));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(result.current.phase).toBe('done');
      expect(result.current.memoryReady).toBe(false);
      expect(result.current.backfillNote).toBe(true);
      expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('background');

      ready = true;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });

      expect(result.current.memoryReady).toBe(true);
      expect(result.current.memoryProcessedCount).toBe(3);
      expect(result.current.memoryRemainingCount).toBe(0);
      expect(result.current.backfillNote).toBe(false);
      expect(result.current.steps.find((s) => s.id === 'memory')?.status).toBe('done');
    } finally {
      vi.useRealTimers();
    }
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
      l2_total_count: 4,
      l2_processed_count: 4,
      l2_remaining_count: 0,
    } as any);

    const { result } = renderHook(() => usePluginInstallFlow('p', true));
    await waitFor(() => expect(result.current.phase).toBe('done'), { timeout: 5000 });
    expect(inst).toHaveBeenCalledWith('p', expect.any(Function));
    expect(result.current.steps.find((s) => s.id === 'install')?.status).toBe('done');
  });
});
