import { z } from 'zod';
import { api } from '@/api/client';
import { assertRuntimeGeneration, getRuntimeConfig, getRuntimeGeneration, subscribeRuntimeReset } from './config';

const CHUNK_BYTES = 1024 * 1024;
const uploadSchema = z.object({
  resource_id: z.string().uuid(), name: z.string().min(1), purpose: z.enum(['history', 'restore']),
  source_name: z.string().min(1), last_modified_ms: z.number().int().nonnegative(),
  size: z.number().int().nonnegative().max(2 * 1024 ** 3), received: z.number().int().nonnegative(), expires_at: z.number(),
});
export type UploadedResource = Pick<z.infer<typeof uploadSchema>, 'resource_id' | 'name' | 'size'>;

function selectFiles(accept: string, multiple: boolean, directory = false): Promise<File[]> {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = accept; input.multiple = multiple;
    if (directory) input.setAttribute('webkitdirectory', '');
    input.hidden = true;
    let finished = false;
    let unsubscribe = () => {};
    const finish = (files: File[]) => {
      if (finished) return;
      finished = true; unsubscribe(); input.remove(); resolve(files);
    };
    input.addEventListener('change', () => finish(Array.from(input.files ?? [])), { once: true });
    input.addEventListener('cancel', () => finish([]), { once: true });
    unsubscribe = subscribeRuntimeReset(() => finish([]));
    document.body.append(input); input.click();
  });
}

async function hash(bytes: ArrayBuffer): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
}

/** Retry only this idempotent transfer protocol, never arbitrary API mutations. */
async function transferRequest<T>(operation: () => Promise<T>, owner: number): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    assertRuntimeGeneration(owner);
    try { return await operation(); }
    catch (error) {
      assertRuntimeGeneration(owner);
      const failure = z.object({ kind: z.string().optional(), status: z.number().optional() }).safeParse(error);
      const retryable = failure.success && (failure.data.kind === 'network' || [408, 429, 502, 503, 504].includes(failure.data.status ?? 0));
      if (!retryable || attempt >= 4) throw error;
      await new Promise<void>(resolve => window.setTimeout(resolve, 250 * 2 ** attempt));
    }
  }
}

export async function uploadFile(file: File, purpose: 'history' | 'restore', owner = getRuntimeGeneration()): Promise<UploadedResource> {
  assertRuntimeGeneration(owner);
  if (file.size > (purpose === 'history' ? 256 * 1024 ** 2 : 2 * 1024 ** 3)) throw new Error('resource_too_large');
  const metadata = { name: file.name, size: file.size, purpose, source_name: file.webkitRelativePath || file.name, last_modified_ms: file.lastModified };
  const runtime = getRuntimeConfig();
  if (!runtime.serverId || !runtime.profileId || !runtime.dataEpoch) throw new Error('Upload requires an established connection');
  // Hash one chunk at a time: bounded memory even for a multi-gigabyte restore.
  // The complete manifest binds resumed bytes to the exact file across app restarts.
  const hashes: string[] = [];
  for (let offset = 0; offset < file.size; offset += CHUNK_BYTES) {
    assertRuntimeGeneration(owner);
    hashes.push(await hash(await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer()));
  }
  const identity = await hash(new TextEncoder().encode(JSON.stringify([runtime.serverId, runtime.profileId, runtime.dataEpoch, metadata, hashes])).buffer);
  const resourceId = `${identity.slice(0, 8)}-${identity.slice(8, 12)}-5${identity.slice(13, 16)}-a${identity.slice(17, 20)}-${identity.slice(20, 32)}`;
  const spec = { resource_id: resourceId, ...metadata };
  let state = uploadSchema.parse(await transferRequest(() => api.post<unknown>('/files/uploads', spec), owner));
  const validate = () => {
    assertRuntimeGeneration(owner);
    if (state.resource_id !== spec.resource_id || state.name !== spec.name || state.size !== spec.size || state.purpose !== purpose || state.source_name !== spec.source_name || state.last_modified_ms !== spec.last_modified_ms || state.received > file.size || (state.received !== file.size && state.received % CHUNK_BYTES !== 0)) {
      throw new Error('Upload identity does not match the selected file');
    }
  };
  validate();
  while (state.received < file.size) {
    const offset = state.received;
    const bytes = await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer();
    const sha256 = hashes[offset / CHUNK_BYTES];
    if (await hash(bytes) !== sha256) throw new Error('Selected file changed during upload');
    assertRuntimeGeneration(owner);
    state = uploadSchema.parse(await transferRequest(() => api.put<unknown>(`/files/uploads/${spec.resource_id}`, bytes, {
      params: { offset, sha256 }, headers: { 'Content-Type': 'application/octet-stream' },
    }), owner));
    validate();
    if (state.received < offset + bytes.byteLength) throw new Error('Upload chunk was not acknowledged');
  }
  return { resource_id: state.resource_id, name: state.name, size: state.size };
}

async function uploadSelection(extensions: string[], directory: boolean, limit: number): Promise<string[]> {
  const owner = getRuntimeGeneration();
  const normalized = extensions.map(extension => extension.replace(/^\./, '').toLowerCase());
  let files = await selectFiles(normalized.map(extension => `.${extension}`).join(','), true, directory);
  assertRuntimeGeneration(owner);
  if (directory) files = files.filter(file => normalized.some(extension => file.name.toLowerCase().endsWith(`.${extension}`)));
  if (files.length > limit) throw new Error(`Select at most ${limit} files per import`);
  const result: string[] = [];
  for (const file of files) result.push((await uploadFile(file, 'history', owner)).resource_id);
  return result;
}

export function uploadMarkdownFiles(): Promise<string[]> { return uploadSelection(['md', 'markdown'], false, 50); }
export function uploadMarkdownFolder(): Promise<string[]> { return uploadSelection(['md', 'markdown'], true, 50); }
export function uploadHistoryFiles(extensions: string[]): Promise<string[]> { return uploadSelection(extensions, false, 10); }
export async function uploadMemoryBackup(): Promise<UploadedResource | undefined> {
  const owner = getRuntimeGeneration();
  const files = await selectFiles('.magibackup', false);
  assertRuntimeGeneration(owner);
  return files[0] ? uploadFile(files[0], 'restore', owner) : undefined;
}
