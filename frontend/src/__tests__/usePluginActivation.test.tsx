import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { usePluginActivation } from '@/hooks/usePluginActivation';
import { sensorsApi } from '@/api/modules/sensors';
import { pluginsApi } from '@/api/modules/plugins';

const FLOW = {
  enabled_key: 'enabled',
  configured_key: 'configured',
  authorize_on_confirm: false,
  fields: [],
} as any;

describe('usePluginActivation', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({
      sources: [
        { plugin_id: 'chrome-history', source_name: 'chrome', activation_flow: FLOW },
      ],
    } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
  });

  it('opens a dialog for a plugin that has an activation flow', async () => {
    const { result } = renderHook(() => usePluginActivation());
    await act(async () => {
      await result.current.openDialog('chrome-history');
    });
    expect(result.current.dialogState).toMatchObject({
      pluginId: 'chrome-history',
      sourceName: 'chrome',
      flow: FLOW,
    });
  });

  it('persists settings and fires onSuccess on confirm', async () => {
    const onSuccess = vi.fn();
    const { result } = renderHook(() => usePluginActivation({ onSuccess }));
    await act(async () => {
      await result.current.openDialog('chrome-history');
    });
    await act(async () => {
      await result.current.confirm({ source_path: '/x' });
    });
    expect(pluginsApi.updateSettings).toHaveBeenCalledWith('chrome-history', {
      source_path: '/x',
      enabled: true,
      configured: true,
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('chrome-history'));
    expect(result.current.dialogState).toBeNull();
  });

  it('installs from registry first when openDialog is called with install: true', async () => {
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);
    const { result } = renderHook(() => usePluginActivation());
    await act(async () => {
      await result.current.openDialog('chrome-history', { install: true });
    });
    expect(installSpy).toHaveBeenCalledWith('chrome-history', expect.any(Function));
    expect(result.current.dialogState?.pluginId).toBe('chrome-history');
  });

  it('does not install when openDialog is called without install', async () => {
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);
    const { result } = renderHook(() => usePluginActivation());
    await act(async () => {
      await result.current.openDialog('chrome-history');
    });
    expect(installSpy).not.toHaveBeenCalled();
    expect(result.current.dialogState?.pluginId).toBe('chrome-history');
  });

  it('forwards onProgress into installProgress during install and clears it after', async () => {
    const snap = {
      job_id: 'j1',
      operation: 'install',
      plugin_id: 'chrome-history',
      filename: null,
      status: 'running',
      stage: 'downloading',
      progress_pct: 42,
      message: 'downloading',
      logs: [],
      created_at_ms: 1,
      updated_at_ms: 2,
    } as any;
    let received: unknown;
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockImplementation(async (_id: string, onProgress?: (s: any) => void) => {
        received = onProgress;
        onProgress?.(snap);
        return {} as any;
      });

    const { result } = renderHook(() => usePluginActivation());
    expect(result.current.installProgress).toBeNull();

    await act(async () => {
      await result.current.openDialog('chrome-history', { install: true });
    });

    // onProgress is no longer dropped: a forwarding callback reached the install job.
    expect(installSpy).toHaveBeenCalledWith('chrome-history', expect.any(Function));
    expect(typeof received).toBe('function');
    // It is reset to null in the finally block once the install settles.
    expect(result.current.installProgress).toBeNull();
  });
});
