import { z } from 'zod';
import { api } from '@/api/client';
import { assertRuntimeGeneration, getRuntimeGeneration, subscribeRuntimeReset } from './config';

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

export async function uploadFile(file: File, purpose: 'history' | 'restore', owner = getRuntimeGeneration()): Promise<UploadedResource> {
  assertRuntimeGeneration(owner);
  const spec = { resource_id: crypto.randomUUID(), name: file.name, size: file.size, purpose, source_name: file.webkitRelativePath || file.name, last_modified_ms: file.lastModified };
  let state = uploadSchema.parse(await api.post<unknown>('/files/uploads', spec));
  const validate = () => {
    assertRuntimeGeneration(owner);
    if (state.resource_id !== spec.resource_id || state.name !== spec.name || state.size !== spec.size || state.purpose !== purpose || state.received > file.size) {
      throw new Error('Upload identity does not match the selected file');
    }
  };
  validate();
  while (state.received < file.size) {
    const offset = state.received;
    const bytes = await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    assertRuntimeGeneration(owner);
    state = uploadSchema.parse(await api.put<unknown>(`/files/uploads/${spec.resource_id}`, bytes, {
      params: { offset, sha256 }, headers: { 'Content-Type': 'application/octet-stream' },
    }));
    validate();
    if (state.received !== offset + bytes.byteLength) throw new Error('Upload chunk was not acknowledged');
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
