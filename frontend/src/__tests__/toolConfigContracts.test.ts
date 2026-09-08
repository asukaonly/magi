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
  it('returns the write receipt without a racy follow-up read', async () => {
    put.mockResolvedValue({ ...fixtures.tool, revision: 'b'.repeat(64), current_values: { limit: 8 } });
    await expect(toolsApi.updateToolConfig('fixture-tool', { revision: fixtures.tool.revision, updates: { limit: 999 } })).resolves.toMatchObject({ revision: 'b'.repeat(64), current_values: { limit: 8 } });
    expect(get).not.toHaveBeenCalled();
  });
  it('does not read or accept a rejected save', async () => {
    put.mockResolvedValue({ success: false, message: 'Rejected' });
    await expect(toolsApi.updateToolConfig('fixture-tool', { revision: fixtures.tool.revision, updates: { limit: 8 } })).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
  });
  it('rejects a receipt with missing revision or a different tool identity', async () => {
    put.mockResolvedValueOnce({ ...fixtures.tool, revision: undefined });
    await expect(toolsApi.updateToolConfig('fixture-tool', { revision: fixtures.tool.revision, updates: {} })).rejects.toThrow();
    put.mockResolvedValueOnce({ ...fixtures.tool, name: 'other-tool' });
    await expect(toolsApi.updateToolConfig('fixture-tool', { revision: fixtures.tool.revision, updates: {} })).rejects.toThrow();
  });
});
