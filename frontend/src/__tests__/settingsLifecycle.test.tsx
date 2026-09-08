import { StrictMode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), preflight: vi.fn(), autoStart: vi.fn(), controlGet: vi.fn(), controlUpdate: vi.fn(), toolList: vi.fn(), toolUpdate: vi.fn(), t: (key: string) => key }));
vi.mock('react-i18next', async original => ({ ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t: mocks.t }) }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() } }));
vi.mock('@/api/modules/config', async original => ({ ...await original<typeof import('@/api/modules/config')>(), configApi: { get: mocks.get, update: mocks.update, embeddingPreflight: mocks.preflight } }));
vi.mock('@/api/modules/control', () => ({ getControlSettings: mocks.controlGet, updateControlSettings: mocks.controlUpdate }));
vi.mock('@/api/modules/plugins', () => ({ pluginsApi: { list: async () => ({ plugins: [] }), getRegistry: async () => ({ plugins: [], install_fingerprint: 'audit' }) } }));
vi.mock('@/api/modules/sources', () => ({ sourcesApi: { getStatus: async () => ({ sources: [] }) } }));
vi.mock('@/api/modules/tools', () => ({ toolsApi: { listWithConfig: mocks.toolList, updateToolConfig: mocks.toolUpdate } }));

vi.mock('@/runtime/desktop', async original => ({ ...await original<typeof import('@/runtime/desktop')>(), syncAutoStartPreference: mocks.autoStart }));

import { toast } from 'sonner';
import { useSettingsTools } from '@/hooks/useSettingsTools';
import { useSettingsConfig } from '@/hooks/useSettingsConfig';
import { useDesktopPreferencesStore } from '@/stores/desktop-preferences';
import { useSettings } from '@/hooks/useSettings';
import fixtures from '../../../contracts/api/frontend-config-examples.json';
import { useThemeStore } from '@/stores/theme';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { readDevicePreferences } from '@/runtime/device-preferences';

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  useDesktopPreferencesStore.setState({ autoStartSyncFailed: false });
  useThemeStore.getState().setMode('light');
  mocks.controlGet.mockResolvedValue({ revision: 'a'.repeat(64), permission_mode: 'high_only', plan_approval_required: true });
  mocks.toolList.mockResolvedValue({ tools: [] });
  mocks.get.mockResolvedValue({ success: true, data: structuredClone(DEFAULT_SYSTEM_CONFIG) });
  mocks.preflight.mockResolvedValue({ severity: 'none', warnings: [] });
});

it('keeps control and tool edits while advancing their confirmed baselines', async () => {
  let finishControl: (value: unknown) => void = () => {};
  let finishTool: (value: unknown) => void = () => {};
  mocks.controlUpdate.mockImplementation(() => new Promise(resolve => { finishControl = resolve; }));
  mocks.toolUpdate.mockImplementation(() => new Promise(resolve => { finishTool = resolve; }));
  mocks.toolList.mockResolvedValue({ tools: [fixtures.tool] });
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => {
    result.current.patchDraftControlSettings(draft => { draft.plan_approval_required = false; });
    result.current.handleToolDraftChange('fixture-tool', 'limit', 8);
  });
  let pending = Promise.resolve();
  act(() => { pending = result.current.handleSaveChanges(); });
  await waitFor(() => expect(mocks.controlUpdate).toHaveBeenCalledTimes(1));
  act(() => result.current.patchDraftControlSettings(draft => { draft.plan_approval_required = true; }));
  await act(async () => { finishControl({ revision: 'b'.repeat(64), permission_mode: 'high_only', plan_approval_required: false }); });
  await waitFor(() => expect(mocks.toolUpdate).toHaveBeenCalledTimes(1));
  act(() => result.current.handleToolDraftChange('fixture-tool', 'limit', 12));
  const confirmedTool = { ...fixtures.tool, revision: 'b'.repeat(64), current_values: { limit: 8 } };
  mocks.toolList.mockResolvedValue({ tools: [confirmedTool] });
  await act(async () => { finishTool(confirmedTool); await pending; });
  expect(result.current.draftControlSettings?.plan_approval_required).toBe(true);
  expect(result.current.draftToolDrafts['fixture-tool'].values.limit).toBe(12);
  expect(result.current.draftToolDrafts['fixture-tool'].revision).toBe('b'.repeat(64));
  expect(result.current.dirty).toBe(true);
  await act(() => result.current.handleDiscardChanges());
  expect(result.current.draftControlSettings?.plan_approval_required).toBe(false);
  expect(result.current.draftToolDrafts['fixture-tool'].values.limit).toBe(8);
  expect(result.current.dirty).toBe(false);
});

it('keeps a newer theme preview when an earlier save completes', async () => {
  let finish: (value: unknown) => void = () => {};
  mocks.update.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => {
    result.current.patchDraftConfig(draft => { draft.agent.name = 'Submitted'; });
    result.current.handleThemePreviewChange('dark');
  });
  let pending = Promise.resolve();
  act(() => { pending = result.current.handleSaveChanges(); });
  await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
  act(() => result.current.handleThemePreviewChange('matcha'));
  await act(async () => { finish({ success: true, data: mocks.update.mock.calls[0][0] }); await pending; });
  expect(result.current.draftThemeMode).toBe('matcha');
  expect(useThemeStore.getState().mode).toBe('matcha');
  expect(localStorage.getItem('magi-theme-mode')).toBe('dark');
  expect(result.current.dirty).toBe(true);
});

it('uses canonical values when the submitted draft has not changed', async () => {
  mocks.update.mockImplementation(async config => ({ success: true, data: { ...config, agent: { ...config.agent, name: 'Canonical' } } }));
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'Submitted'; }));
  await act(() => result.current.handleSaveChanges());
  expect(result.current.draftConfig.agent.name).toBe('Canonical');
  expect(result.current.dirty).toBe(false);
});

it('restarts settings loading after StrictMode effect cleanup', async () => {
  const { result } = renderHook(useSettings, { wrapper: StrictMode });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(mocks.get).toHaveBeenCalledTimes(2);
  expect(result.current.pluginsLoading).toBe(false);
  expect(result.current.toolsLoading).toBe(false);
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'Unsaved'; }));
  expect(result.current.draftConfig.agent.name).toBe('Unsaved');
  expect(mocks.get).toHaveBeenCalledTimes(2);
});

it('loads normally outside StrictMode as the control case', async () => {
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
});

it('preserves edits made during save and discards to the confirmed response', async () => {
  let finish: (value: unknown) => void = () => {};
  mocks.update.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'Submitted'; }));
  let pending: Promise<void> = Promise.resolve();
  act(() => { pending = result.current.handleSaveChanges(); });
  await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
  const submitted = structuredClone(mocks.update.mock.calls[0][0]);
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'New unsaved edit'; }));
  expect(result.current.draftConfig.agent.name).toBe('New unsaved edit');
  await act(async () => { finish({ success: true, data: submitted }); await pending; });
  expect(result.current.draftConfig.agent.name).toBe('New unsaved edit');
  expect(result.current.dirty).toBe(true);
  await act(() => result.current.handleDiscardChanges());
  expect(result.current.draftConfig.agent.name).toBe('Submitted');
  expect(result.current.dirty).toBe(false);
});

it('keeps native application failure visible and retries without rewriting confirmed config', async () => {
  mocks.update.mockImplementation(async data => ({ success: true, data }));
  mocks.autoStart.mockImplementationOnce(async () => {
    useDesktopPreferencesStore.setState({ autoStartSyncFailed: true });
    throw new Error('Native failure');
  }).mockImplementationOnce(async () => {
    useDesktopPreferencesStore.setState({ autoStartSyncFailed: false });
  });
  const { result, unmount } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.patchDraftConfig(draft => { draft.preferences.auto_start_enabled = true; }));
  await act(() => result.current.handleSaveChanges());
  expect(result.current.autoStartSyncFailed).toBe(true);
  expect(result.current.dirty).toBe(false);
  expect(toast.success).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith('settings.autoStartSyncFailed');
  unmount();
  expect(mocks.update).not.toHaveBeenCalled();
  expect(mocks.preflight).not.toHaveBeenCalled();
  mocks.get.mockResolvedValue({ success: true, data: { ...DEFAULT_SYSTEM_CONFIG, preferences: { ...DEFAULT_SYSTEM_CONFIG.preferences, ...readDevicePreferences() } } });
  const reopened = renderHook(useSettings);
  await waitFor(() => expect(reopened.result.current.loading).toBe(false));
  expect(reopened.result.current.autoStartSyncFailed).toBe(true);
  await act(() => reopened.result.current.handleSaveChanges());
  expect(mocks.update).not.toHaveBeenCalled();
  expect(mocks.autoStart).toHaveBeenCalledTimes(2);
  expect(reopened.result.current.autoStartSyncFailed).toBe(false);
  expect(toast.success).toHaveBeenCalledWith('settings.saveSuccess');
});

it('preserves the stale draft on conflict and requires an explicit latest snapshot reload', async () => {
  mocks.get.mockResolvedValue({ success: true, data: { ...structuredClone(DEFAULT_SYSTEM_CONFIG), revision: 'base' } });
  mocks.update.mockRejectedValue({ status: 409, message: 'Center configuration changed' });
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'My unsaved changes'; }));
  await act(() => result.current.handleSaveChanges());
  expect(result.current.configConflict).toBe('config');
  expect(result.current.draftConfig.agent.name).toBe('My unsaved changes');
  expect(mocks.update).toHaveBeenCalledTimes(1);
  expect(mocks.update.mock.calls[0][0].revision).toBe('base');
  mocks.get.mockResolvedValue({ success: true, data: { ...structuredClone(DEFAULT_SYSTEM_CONFIG), revision: 'new', agent: { name: 'Other device' } } });
  await act(() => result.current.fetchConfig({ silent: true, discardDraft: true }));
  expect(result.current.configConflict).toBeNull();
  expect(result.current.draftConfig.agent.name).toBe('Other device');
  expect(result.current.draftConfig.revision).toBe('new');
});

it('advances the write baseline while preserving edits made during a successful save', async () => {
  let finish: (value: unknown) => void = () => {};
  mocks.get.mockResolvedValue({ success: true, data: { ...structuredClone(DEFAULT_SYSTEM_CONFIG), revision: 'old' } });
  mocks.update.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'Submitted'; }));
  let pending = Promise.resolve();
  act(() => { pending = result.current.handleSaveChanges(); });
  await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'New edit'; }));
  await act(async () => { finish({ success: true, data: { ...mocks.update.mock.calls[0][0], revision: 'confirmed' } }); await pending; });
  expect(result.current.draftConfig.agent.name).toBe('New edit');
  expect(result.current.draftConfig.revision).toBe('confirmed');
  expect(result.current.dirty).toBe(true);
});

it('retains a rejected control draft and reloads only that resource on request', async () => {
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.patchDraftControlSettings(draft => { draft.plan_approval_required = false; }));
  mocks.controlUpdate.mockRejectedValue({ status: 409, message: 'Changed on center' });
  await act(() => result.current.handleSaveChanges());
  expect(result.current.configConflict).toBe('control');
  expect(result.current.draftControlSettings?.plan_approval_required).toBe(false);
  expect(mocks.controlUpdate).toHaveBeenCalledWith(expect.objectContaining({ revision: 'a'.repeat(64) }));
  act(() => result.current.patchDraftConfig(draft => { draft.agent.name = 'Unrelated local draft'; }));
  mocks.controlGet.mockResolvedValue({ revision: 'b'.repeat(64), permission_mode: 'all', plan_approval_required: true });
  await act(() => result.current.reloadConflictedSettings());
  expect(result.current.configConflict).toBeNull();
  expect(result.current.draftControlSettings?.permission_mode).toBe('all');
  expect(result.current.draftConfig.agent.name).toBe('Unrelated local draft');
  expect(mocks.controlUpdate).toHaveBeenCalledTimes(1);
});

it('retains the original tool revision and reloads only the conflicting draft', async () => {
  mocks.toolList.mockResolvedValue({ tools: [fixtures.tool, { ...fixtures.tool, name: 'second-tool' }] });
  mocks.toolUpdate.mockRejectedValue({ status: 409 });
  const { result } = renderHook(useSettings);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => {
    result.current.handleToolDraftChange('fixture-tool', 'limit', 8);
    result.current.handleToolDraftChange('second-tool', 'limit', 19);
  });
  await act(() => result.current.handleSaveChanges());
  expect(result.current.configConflict).toBe('tool:fixture-tool');
  expect(mocks.toolUpdate).toHaveBeenCalledWith('fixture-tool', expect.objectContaining({ revision: fixtures.tool.revision }));
  expect(result.current.draftToolDrafts['fixture-tool'].values.limit).toBe(8);
  mocks.toolList.mockResolvedValue({ tools: [{ ...fixtures.tool, revision: 'b'.repeat(64), current_values: { limit: 12 } }, { ...fixtures.tool, name: 'second-tool' }] });
  await act(() => result.current.reloadConflictedSettings());
  expect(result.current.configConflict).toBeNull();
  expect(result.current.draftToolDrafts['fixture-tool'].values.limit).toBe(12);
  expect(result.current.draftToolDrafts['fixture-tool'].revision).toBe('b'.repeat(64));
  expect(result.current.draftToolDrafts['second-tool'].values.limit).toBe(19);
  expect(mocks.toolUpdate).toHaveBeenCalledTimes(1);
});

it('does not roll a confirmed tool receipt back with an earlier read', async () => {
  mocks.toolList.mockResolvedValue({ tools: [fixtures.tool] });
  const { result } = renderHook(useSettingsTools);
  await act(() => result.current.loadTools());
  let finish: (value: unknown) => void = () => {};
  mocks.toolList.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  let pending = Promise.resolve();
  act(() => { pending = result.current.loadTools({ silent: true }); });
  const acknowledged = { 'fixture-tool': { revision: 'b'.repeat(64), enabled: true, values: { limit: 8 } } };
  act(() => {
    result.current.setSavedToolDrafts(acknowledged);
    result.current.setDraftToolDrafts(acknowledged);
  });
  await act(async () => { finish({ tools: [fixtures.tool] }); await pending; });
  expect(result.current.savedToolDrafts['fixture-tool']).toEqual(acknowledged['fixture-tool']);
  expect(result.current.draftToolDrafts['fixture-tool']).toEqual(acknowledged['fixture-tool']);
});

it.each(['config', 'control'] as const)('keeps the confirmed %s receipt when an older read arrives', async (resource) => {
  const setTheme = vi.fn();
  const { result } = renderHook(() => useSettingsConfig({ themeMode: 'light', setSavedThemeMode: setTheme, setDraftThemeMode: setTheme }));
  await act(() => result.current.fetchConfig());
  await act(() => result.current.loadControlSettings());
  let finish: (value: unknown) => void = () => {};
  const pendingRead = new Promise(resolve => { finish = resolve; });
  const confirmedConfig = { ...structuredClone(DEFAULT_SYSTEM_CONFIG), revision: 'confirmed', agent: { ...DEFAULT_SYSTEM_CONFIG.agent, name: 'Confirmed' } };
  const confirmedControl = { revision: 'b'.repeat(64), permission_mode: 'all' as const, plan_approval_required: false };
  let pending = Promise.resolve();
  if (resource === 'config') {
    mocks.get.mockReturnValueOnce(pendingRead);
    act(() => { pending = result.current.fetchConfig({ silent: true }); });
    act(() => { result.current.setSavedConfig(confirmedConfig); result.current.setDraftConfig(confirmedConfig); });
    await act(async () => { finish({ success: true, data: DEFAULT_SYSTEM_CONFIG }); await pending; });
    expect(result.current.savedConfig).toEqual(confirmedConfig);
    expect(result.current.draftConfig).toEqual(confirmedConfig);
  } else {
    mocks.controlGet.mockReturnValueOnce(pendingRead);
    act(() => { pending = result.current.loadControlSettings({ silent: true }); });
    act(() => { result.current.setSavedControlSettings(confirmedControl); result.current.setDraftControlSettings(confirmedControl); });
    await act(async () => { finish({ revision: 'a'.repeat(64), permission_mode: 'high_only', plan_approval_required: true }); await pending; });
    expect(result.current.savedControlSettings).toEqual(confirmedControl);
    expect(result.current.draftControlSettings).toEqual(confirmedControl);
  }
});
