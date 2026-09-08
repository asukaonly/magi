import { useEffect } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  list: vi.fn(), get: vi.fn(), getActive: vi.fn(), update: vi.fn(), create: vi.fn(),
  refresh: new Set<() => Promise<void>>(), t: (key: string) => key,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t, i18n: { language: 'en' } }) }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() } }));
vi.mock('@/api/modules/personas', async original => ({
  ...await original<typeof import('@/api/modules/personas')>(), personasApi: mocks,
}));
vi.mock('@/hooks/useCenterRefresh', () => ({ useCenterRefresh: (read: () => Promise<void>) => {
  useEffect(() => { mocks.refresh.add(read); return () => { mocks.refresh.delete(read); }; }, [read]);
} }));

import { DEFAULT_PERSONALITY_CONFIG } from '@/api/modules/personas';
import { usePersonality } from '@/hooks/usePersonality';

function snapshot(id: string, revision: number, name = id) {
  const config = structuredClone(DEFAULT_PERSONALITY_CONFIG);
  config.name = name;
  config.identity_core = { identity_statement: 'Identity', values_loved: ['Care'], values_rejected: ['Harm'], attention_biases: [] };
  config.idiolect.sentence_style = 'Brief';
  config.registers.chat = { behavior: 'Listen', description: 'Chat', examples: [] };
  return { data: { persona_id: id, updated_at: revision, config } };
}
async function refresh() { await act(async () => { await Promise.all([...mocks.refresh].map(read => read())); }); }

beforeEach(() => {
  vi.resetAllMocks();
  mocks.refresh.clear();
  mocks.getActive.mockResolvedValue({ persona_id: 'a' });
  mocks.list.mockResolvedValue({ data: [{ persona_id: 'a', name: 'A' }, { persona_id: 'b', name: 'B' }] });
  mocks.get.mockImplementation(async (id: string) => snapshot(id, 1));
});

it('loads the requested persona and rejects a late previous selection', async () => {
  const { result } = renderHook(() => usePersonality({ initialPersonalityId: 'b' }));
  await waitFor(() => expect(result.current.config.name).toBe('b'));
  let finish: (value: unknown) => void = () => {};
  mocks.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  act(() => result.current.selectPersonality('a'));
  act(() => result.current.selectPersonality('b'));
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => { finish(snapshot('a', 3, 'Late A')); });
  expect(result.current.selectedId).toBe('b');
  expect(result.current.config.name).toBe('b');
});

it('preserves a dirty editor and its original revision until explicit reload', async () => {
  const { result } = renderHook(usePersonality);
  await waitFor(() => expect(result.current.config.name).toBe('a'));
  act(() => result.current.patch(draft => { draft.name = 'My draft'; }));
  mocks.get.mockResolvedValue(snapshot('a', 2, 'Other device'));
  await refresh();
  expect(result.current.config.name).toBe('My draft');
  mocks.update.mockRejectedValue({ status: 409 });
  await act(() => result.current.save());
  expect(mocks.update).toHaveBeenCalledWith('a', expect.objectContaining({ expected_updated_at: 1 }));
  expect(result.current.conflict).toBe(true);
  expect(result.current.config.name).toBe('My draft');
  await act(() => result.current.reload());
  expect(result.current.conflict).toBe(false);
  expect(result.current.config.name).toBe('Other device');
});

it('advances only its own receipt while preserving edits made during save', async () => {
  const { result } = renderHook(usePersonality);
  await waitFor(() => expect(result.current.config.name).toBe('a'));
  act(() => result.current.patch(draft => { draft.name = 'Submitted'; }));
  let finish: (value: unknown) => void = () => {};
  mocks.update.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  let pending = Promise.resolve();
  act(() => { pending = result.current.save(); });
  act(() => result.current.patch(draft => { draft.name = 'New edit'; }));
  await act(async () => { finish(snapshot('a', 2, 'Submitted')); await pending; });
  expect(result.current.config.name).toBe('New edit');
  mocks.update.mockResolvedValue(snapshot('a', 3, 'New edit'));
  await act(() => result.current.save());
  expect(mocks.update).toHaveBeenLastCalledWith('a', expect.objectContaining({ expected_updated_at: 2 }));
});

it('does not let an earlier read replace a confirmed receipt', async () => {
  const { result } = renderHook(usePersonality);
  await waitFor(() => expect(result.current.config.name).toBe('a'));
  let finish: (value: unknown) => void = () => {};
  mocks.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  let pending = Promise.resolve();
  act(() => { pending = Promise.all([...mocks.refresh].map(read => read())).then(() => {}); });
  act(() => result.current.patch(draft => { draft.name = 'Saved'; }));
  mocks.update.mockResolvedValue(snapshot('a', 2, 'Saved'));
  await act(() => result.current.save());
  await act(async () => { finish(snapshot('a', 1)); await pending; });
  expect(result.current.config.name).toBe('Saved');
  mocks.list.mockRejectedValue(new Error('Offline'));
  mocks.get.mockRejectedValue(new Error('Offline'));
  await refresh();
  expect(result.current.list).toHaveLength(2);
  expect(result.current.config.name).toBe('Saved');
});

it('keeps the create identity after a lost response', async () => {
  const { result } = renderHook(usePersonality);
  await waitFor(() => expect(result.current.config.name).toBe('a'));
  act(() => { result.current.startNewPersonality(); result.current.patch(draft => Object.assign(draft, snapshot('new', 1).data.config)); });
  mocks.create.mockRejectedValueOnce(new Error('Disconnected'));
  await act(() => result.current.save());
  const submitted = mocks.create.mock.calls[0][0];
  mocks.create.mockResolvedValue(snapshot(submitted.persona_id, 1));
  await act(() => result.current.save());
  expect(mocks.create.mock.calls[1][0].persona_id).toBe(submitted.persona_id);
  expect(result.current.isNewMode).toBe(false);
});
