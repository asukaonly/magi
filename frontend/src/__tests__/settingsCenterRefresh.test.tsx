import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { useSettingsConfig } from '@/hooks/useSettingsConfig';
import { APP_EVENTS } from '@/constants/events';

vi.mock('@/api/modules/config', async (original) => {
  const actual = await original<typeof import('@/api/modules/config')>();
  return { ...actual, configApi: { ...actual.configApi, get: vi.fn() } };
});
vi.mock('@/api/modules/control', () => ({ getControlSettings: vi.fn().mockResolvedValue({ revision: 'a'.repeat(64), permission_mode: 'high_only', plan_approval_required: false }) }));
const theme = vi.fn();
const options = { themeMode: 'light' as const, setSavedThemeMode: theme, setDraftThemeMode: theme };
const config = (path: string) => ({ ...structuredClone(DEFAULT_SYSTEM_CONFIG), preferences: { ...DEFAULT_SYSTEM_CONFIG.preferences, default_chat_workspace_path: path } });
beforeEach(() => { vi.useFakeTimers(); vi.mocked(configApi.get).mockReset(); theme.mockClear(); });
afterEach(() => { vi.useRealTimers(); });

it('updates a pristine settings snapshot after a center change without resetting theme', async () => {
  vi.mocked(configApi.get).mockResolvedValueOnce({ success: true, message: "OK", data: config('/old') }).mockResolvedValue({ success: true, message: "OK", data: config('/new') });
  const view = renderHook(() => useSettingsConfig(options));
  await act(async () => { await view.result.current.fetchConfig(); });
  theme.mockClear();
  await act(async () => { window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED)); await vi.advanceTimersByTimeAsync(250); });
  expect(view.result.current.draftConfig.preferences.default_chat_workspace_path).toBe('/new');
  expect(view.result.current.savedConfig.preferences.default_chat_workspace_path).toBe('/new');
  expect(theme).not.toHaveBeenCalled();
  view.unmount();
});

it('retains a dirty draft and its original base when a background read finishes', async () => {
  let finish: ((value: Awaited<ReturnType<typeof configApi.get>>) => void) | undefined;
  vi.mocked(configApi.get).mockResolvedValueOnce({ success: true, message: "OK", data: config('/base') }).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const view = renderHook(() => useSettingsConfig(options));
  await act(async () => { await view.result.current.fetchConfig(); });
  await act(async () => { window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED)); await vi.advanceTimersByTimeAsync(250); });
  act(() => { view.result.current.patchDraftConfig((draft) => { draft.preferences.default_chat_workspace_path = '/mine'; }); });
  await act(async () => { finish?.({ success: true, message: "OK", data: config('/other-device') }); });
  expect(view.result.current.savedConfig.preferences.default_chat_workspace_path).toBe('/base');
  expect(view.result.current.draftConfig.preferences.default_chat_workspace_path).toBe('/mine');
  view.unmount();
});

it('does not discard edits made after an explicit reload started', async () => {
  let finish!: (value: Awaited<ReturnType<typeof configApi.get>>) => void;
  vi.mocked(configApi.get).mockResolvedValueOnce({ success: true, message: 'OK', data: config('/base') })
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = renderHook(() => useSettingsConfig(options));
  await act(() => view.result.current.fetchConfig());
  let pending!: Promise<void>;
  act(() => { pending = view.result.current.fetchConfig({ silent: true, discardDraft: true }); });
  act(() => view.result.current.patchDraftConfig(draft => { draft.preferences.default_chat_workspace_path = '/new-edit'; }));
  await act(async () => { finish({ success: true, message: 'OK', data: config('/center') }); await pending; });
  expect(view.result.current.draftConfig.preferences.default_chat_workspace_path).toBe('/new-edit');
  expect(view.result.current.savedConfig.preferences.default_chat_workspace_path).toBe('/base');
});
