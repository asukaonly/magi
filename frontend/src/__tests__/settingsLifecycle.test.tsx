import { StrictMode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), preflight: vi.fn(), autoStart: vi.fn(), controlUpdate: vi.fn(), toolList: vi.fn(), toolUpdate: vi.fn(), t: (key: string) => key }));
vi.mock('react-i18next', async original => ({ ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t: mocks.t }) }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() } }));
vi.mock('@/api/modules/config', async original => ({ ...await original<typeof import('@/api/modules/config')>(), configApi: { get: mocks.get, update: mocks.update, embeddingPreflight: mocks.preflight } }));
vi.mock('@/api/modules/control', () => ({ getControlSettings: async () => ({ permission_mode: 'default', plan_approval_required: true }), updateControlSettings: mocks.controlUpdate }));
vi.mock('@/api/modules/plugins', () => ({ pluginsApi: { list: async () => ({ plugins: [] }), getRegistry: async () => ({ plugins: [], install_fingerprint: 'audit' }) } }));
vi.mock('@/api/modules/sources', () => ({ sourcesApi: { getStatus: async () => ({ sources: [] }) } }));
vi.mock('@/api/modules/tools', () => ({ toolsApi: { listWithConfig: mocks.toolList, updateToolConfig: mocks.toolUpdate } }));

vi.mock('@/runtime/desktop', async original => ({ ...await original<typeof import('@/runtime/desktop')>(), syncAutoStartPreference: mocks.autoStart }));

import { toast } from 'sonner';
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
  await act(async () => { finishControl({ permission_mode: 'default', plan_approval_required: false }); });
  await waitFor(() => expect(mocks.toolUpdate).toHaveBeenCalledTimes(1));
  act(() => result.current.handleToolDraftChange('fixture-tool', 'limit', 12));
  const confirmedTool = { ...fixtures.tool, current_values: { limit: 8 } };
  mocks.toolList.mockResolvedValue({ tools: [confirmedTool] });
  await act(async () => { finishTool(confirmedTool); await pending; });
  expect(result.current.draftControlSettings?.plan_approval_required).toBe(true);
  expect(result.current.draftToolDrafts['fixture-tool'].values.limit).toBe(12);
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
  expect(result.current.configConflict).toBe(true);
  expect(result.current.draftConfig.agent.name).toBe('My unsaved changes');
  expect(mocks.update).toHaveBeenCalledTimes(1);
  expect(mocks.update.mock.calls[0][0].revision).toBe('base');
  mocks.get.mockResolvedValue({ success: true, data: { ...structuredClone(DEFAULT_SYSTEM_CONFIG), revision: 'new', agent: { name: 'Other device' } } });
  await act(() => result.current.fetchConfig({ silent: true, discardDraft: true }));
  expect(result.current.configConflict).toBe(false);
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
