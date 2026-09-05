import { beforeEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/api/frontend-config-examples.json';
import { toolsApi } from '@/api/modules/tools';

const { get, put } = vi.hoisted(() => ({ get: vi.fn<() => Promise<unknown>>(), put: vi.fn<() => Promise<unknown>>() }));
vi.mock('@/api/client', () => ({ api: { get, put } }));
beforeEach(() => { get.mockReset(); put.mockReset(); });

describe('tool configuration confirmation', () => {
  it('reads production serialized tool specifications', async () => {
    get.mockResolvedValue({ tools: [fixtures.tool], total: 1 });
    expect((await toolsApi.listWithConfig()).tools[0].config_specs[0]).toMatchObject({ path: 'limit', type: 'integer' });
  });
  it.each([{}, { success: false, data: { tools: [], total: 0 } }, { tools: 'invalid', total: 0 }])('rejects malformed list data', async value => {
    get.mockResolvedValue(value);
    await expect(toolsApi.listWithConfig()).rejects.toThrow();
  });
  it('returns the canonical persisted value instead of echoing the submitted draft', async () => {
    put.mockResolvedValue({ success: true, message: 'Saved' });
    get.mockResolvedValue({ ...fixtures.tool, current_values: { limit: 8 } });
    await expect(toolsApi.updateToolConfig('fixture-tool', { updates: { limit: 999 } })).resolves.toMatchObject({ current_values: { limit: 8 } });
  });
  it('does not read or accept a rejected save', async () => {
    put.mockResolvedValue({ success: false, message: 'Rejected' });
    await expect(toolsApi.updateToolConfig('fixture-tool', { updates: { limit: 8 } })).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
  });
  it('does not confirm a write when readback fails or belongs to another tool', async () => {
    put.mockResolvedValue({ success: true, message: 'Saved' });
    get.mockRejectedValueOnce(new Error('Unavailable'));
    await expect(toolsApi.updateToolConfig('fixture-tool', { updates: {} })).rejects.toThrow('Unavailable');
    get.mockResolvedValueOnce({ ...fixtures.tool, name: 'other-tool' });
    await expect(toolsApi.updateToolConfig('fixture-tool', { updates: {} })).rejects.toThrow();
  });
});
