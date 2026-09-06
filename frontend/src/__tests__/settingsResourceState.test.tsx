import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSettingsPluginsTimeline } from '@/hooks/useSettingsPluginsTimeline';
import { parsePluginsList } from '@/api/plugin-contract';
import fixtures from '../../../contracts/api/frontend-plugins-examples.json';
import type { PluginsListResponse } from '@/api/modules/plugins';
const { list, getStatus, getRegistry } = vi.hoisted(() => ({
  list: vi.fn<() => Promise<PluginsListResponse>>(),
  getStatus: vi.fn<() => Promise<{ sources: [] }>>(),
  getRegistry: vi.fn(),
}));
vi.mock('@/api/modules/plugins', async importOriginal => ({ ...await importOriginal<typeof import('@/api/modules/plugins')>(), pluginsApi: { list, getRegistry } }));
vi.mock('@/api/modules/sources', () => ({ sourcesApi: { getStatus } }));
vi.mock('react-i18next', async importOriginal => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

beforeEach(() => { list.mockReset(); getStatus.mockReset(); getRegistry.mockReset(); });

describe('settings resource request ownership', () => {
  it('retains loaded packages while exposing refresh failure and clears the error on retry', async () => {
    const packages = parsePluginsList(fixtures.list);
    list.mockResolvedValueOnce(packages).mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce(packages);
    const { result } = renderHook(useSettingsPluginsTimeline);
    await act(() => result.current.loadPlugins());
    await act(() => result.current.loadPlugins());
    expect(result.current.plugins).toEqual(packages.plugins);
    expect(result.current.pluginsError).not.toBeNull();
    await act(() => result.current.loadPlugins());
    expect(result.current.pluginsError).toBeNull();
  });
  it('ignores an older plugin response after a newer request has completed', async () => {
    let finish: ((value: PluginsListResponse) => void) | undefined;
    list.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(useSettingsPluginsTimeline);
    let oldRequest: Promise<void>;
    act(() => { oldRequest = result.current.loadPlugins(); });
    list.mockResolvedValueOnce({ plugins: [], total: 0 });
    await act(() => result.current.loadPlugins());
    await act(async () => { finish?.(parsePluginsList(fixtures.list)); await oldRequest; });
    expect(result.current.plugins).toEqual([]);
    expect(result.current.pluginsError).toBeNull();
  });
  it('does not let a stale source failure overwrite a successful retry', async () => {
    let fail: ((reason: Error) => void) | undefined;
    getStatus.mockImplementationOnce(() => new Promise((_, reject) => { fail = reject; }));
    const { result } = renderHook(useSettingsPluginsTimeline);
    let oldRequest: Promise<void>;
    act(() => { oldRequest = result.current.fetchTimelineStatuses(); });
    getStatus.mockResolvedValueOnce({ sources: [] });
    await act(() => result.current.fetchTimelineStatuses());
    await act(async () => { fail?.(new Error('Old request failed')); await oldRequest; });
    expect(result.current.timelineStatusesError).toBeNull();
    expect(result.current.timelineStatusesLoading).toBe(false);
  });
});
