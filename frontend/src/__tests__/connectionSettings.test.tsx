import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { pluginsApi, type PluginConnection, type ExtensionFieldSpec } from '@/api/modules/plugins';
import { useConnectionSettings, connectionSettingsSeed } from '@/hooks/useConnectionSettings';
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const field: ExtensionFieldSpec = { key: 'source.interval', label: 'Interval', description: '', type: 'number', required: false, options: [], section: 'general', surface: 'timeline', order: 1, minimum: 1 };
const connection = (id: string): PluginConnection => ({ plugin_id: 'test-plugin', connection_id: id, display_name: id, enabled: true, revision: 1, settings: { source: { interval: 30 }, sibling: { enabled: true } }, credential_refs: {}, readiness: [] });
const seed = (id: string) => connectionSettingsSeed(connection(id), [field]);
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(pluginsApi, 'getConnection').mockImplementation(async (_plugin, id) => connection(id));
  vi.spyOn(pluginsApi, 'updateConnection').mockImplementation(async (_plugin, id, input) => ({ ...connection(id), settings: input.settings!, revision: 2 }));
});
it('validates before any write and retains invalid values', async () => {
  const { result } = renderHook(useConnectionSettings);
  act(() => result.current.patch(seed('a'), { [field.key]: '' }));
  await act(async () => { await expect(result.current.save()).rejects.toThrow('fieldInvalid'); });
  expect(pluginsApi.getConnection).not.toHaveBeenCalled();
  expect(result.current.read(seed('a')).values[field.key]).toBe('');
});
it('keeps a failed account dirty while confirming successful accounts and preserving siblings', async () => {
  vi.mocked(pluginsApi.updateConnection).mockRejectedValueOnce({ status: 409 });
  const { result } = renderHook(useConnectionSettings);
  act(() => { result.current.patch(seed('a'), { [field.key]: 45 }); result.current.patch(seed('b'), { [field.key]: 60 }); });
  await act(async () => { await expect(result.current.save()).rejects.toThrow('conflict'); });
  expect(result.current.read(seed('a'))).toMatchObject({ dirty: true, error: 'conflict' });
  expect(result.current.read(seed('b'))).toMatchObject({ dirty: false, values: { [field.key]: 60 } });
  expect(pluginsApi.updateConnection).toHaveBeenLastCalledWith('test-plugin', 'b', expect.objectContaining({ settings: { source: { interval: 60 }, sibling: { enabled: true } } }));
});
it('saves the captured snapshot and retains later edits, then discards to the confirmed value', async () => {
  const { result } = renderHook(useConnectionSettings);
  act(() => result.current.patch(seed('a'), { [field.key]: 45 }));
  const snapshot = result.current.capture();
  act(() => result.current.patch(seed('a'), { [field.key]: 90 }));
  await act(() => result.current.save(snapshot));
  expect(pluginsApi.updateConnection).toHaveBeenCalledWith('test-plugin', 'a', expect.objectContaining({ settings: { source: { interval: 45 }, sibling: { enabled: true } } }));
  expect(result.current.read(seed('a'))).toMatchObject({ dirty: true, values: { [field.key]: 90 } });
  expect(result.current.read(seed('a')).error).toBeUndefined();
  act(() => result.current.discard());
  expect(result.current.read(seed('a'))).toMatchObject({ dirty: false, values: { [field.key]: 45 } });
});
it('rejects remote revisions and response identities without writing', async () => {
  vi.mocked(pluginsApi.getConnection).mockResolvedValueOnce({ ...connection('a'), revision: 2 });
  const { result } = renderHook(useConnectionSettings);
  act(() => result.current.patch(seed('a'), { [field.key]: 45 }));
  await act(async () => { await expect(result.current.save()).rejects.toThrow('conflict'); });
  vi.mocked(pluginsApi.getConnection).mockResolvedValueOnce(connection('wrong-account'));
  await act(async () => { await expect(result.current.save()).rejects.toThrow('saveFailed'); });
  expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
});
it('does not persist a field returned to its saved value', () => {
  const { result } = renderHook(useConnectionSettings);
  act(() => result.current.patch(seed('a'), { [field.key]: 45 }));
  act(() => result.current.patch(seed('a'), { [field.key]: 30 }));
  expect(result.current.dirty).toBe(false);
});
