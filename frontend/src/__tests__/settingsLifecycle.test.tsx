import { StrictMode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), preflight: vi.fn(), t: (key: string) => key }));
vi.mock('react-i18next', async original => ({ ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t: mocks.t }) }));
vi.mock('sonner', () => ({ toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() } }));
vi.mock('@/api/modules/config', async original => ({ ...await original<typeof import('@/api/modules/config')>(), configApi: { get: mocks.get, update: mocks.update, embeddingPreflight: mocks.preflight } }));
vi.mock('@/api/modules/control', () => ({ getControlSettings: async () => ({ permission_mode: 'default', plan_approval_required: true }), updateControlSettings: vi.fn() }));
vi.mock('@/api/modules/plugins', () => ({ pluginsApi: { list: async () => ({ plugins: [] }), getRegistry: async () => ({ plugins: [], install_fingerprint: 'audit' }) } }));
vi.mock('@/api/modules/sources', () => ({ sourcesApi: { getStatus: async () => ({ sources: [] }) } }));
vi.mock('@/api/modules/tools', () => ({ toolsApi: { listWithConfig: async () => ({ tools: [] }) } }));

import { useSettings } from '@/hooks/useSettings';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ success: true, data: structuredClone(DEFAULT_SYSTEM_CONFIG) });
  mocks.preflight.mockResolvedValue({ severity: 'none', warnings: [] });
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

