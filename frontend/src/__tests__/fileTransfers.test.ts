import { beforeEach, describe, expect, it, vi } from 'vitest';
const { post, put, state } = vi.hoisted(() => ({ post: vi.fn(), put: vi.fn(), state: { generation: 1 } }));
vi.mock('@/api/client', () => ({ api: { post, put } }));
vi.mock('@/runtime/config', () => ({
  getRuntimeGeneration: () => state.generation,
  assertRuntimeGeneration: (owner: number) => { if (owner !== state.generation) throw new Error('Connection changed'); },
  subscribeRuntimeReset: () => () => {},
}));
import { uploadFile } from '@/runtime/file-transfers';

function file(bytes: Uint8Array): File {
  return { name: 'note.md', size: bytes.length, lastModified: 1600000000000, webkitRelativePath: 'diary/note.md',
    slice: (start: number, end: number) => ({ arrayBuffer: async () => bytes.slice(start, end).buffer }),
  } as File;
}
beforeEach(() => { vi.clearAllMocks(); state.generation = 1; });
describe('client file upload', () => {
  it('sends bounded chunks with original metadata and returns only the resource reference', async () => {
    let metadata: Record<string, unknown> = {};
    post.mockImplementation(async (_path, spec) => { metadata = spec; return { ...spec, received: 0, expires_at: 9999999999 }; });
    put.mockImplementation(async (_path, bytes, options) => ({ ...metadata, received: options.params.offset + bytes.byteLength, expires_at: 9999999999 }));
    const selected = file(new Uint8Array(1024 * 1024 + 7));
    const resource = await uploadFile(selected, 'history');
    expect(post.mock.calls[0][1]).toMatchObject({ name: 'note.md', source_name: 'diary/note.md', last_modified_ms: 1600000000000 });
    expect(put.mock.calls.map(call => call[1].byteLength)).toEqual([1024 * 1024, 7]);
    expect(put.mock.calls[0][2].params.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(resource).toEqual({ resource_id: metadata.resource_id, name: 'note.md', size: selected.size });
  });
  it('never sends a chunk to a newly selected center', async () => {
    post.mockImplementation(async (_path, spec) => { state.generation += 1; return { ...spec, received: 0, expires_at: 9999999999 }; });
    await expect(uploadFile(file(new Uint8Array(3)), 'restore')).rejects.toThrow('Connection changed');
    expect(put).not.toHaveBeenCalled();
  });
  it('rejects a response identifying another resource before sending content', async () => {
    post.mockImplementation(async (_path, spec) => ({ ...spec, resource_id: crypto.randomUUID(), received: 0, expires_at: 9999999999 }));
    await expect(uploadFile(file(new Uint8Array(3)), 'history')).rejects.toThrow('Upload identity');
    expect(put).not.toHaveBeenCalled();
  });
});
