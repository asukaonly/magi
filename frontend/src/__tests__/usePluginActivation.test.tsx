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
});
