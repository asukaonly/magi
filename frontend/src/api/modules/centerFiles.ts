import { z } from 'zod';
import { api } from '../client';

const entrySchema = z.object({ name: z.string().min(1), path: z.string().min(1), kind: z.enum(['directory', 'file']) });
const directorySchema = z.object({
  path: z.string().min(1), parent: z.string().nullable(),
  selected_file: z.string().nullable(),
  entries: z.array(entrySchema).max(500), next_after: z.string().nullable(),
});
export type CenterDirectory = z.infer<typeof directorySchema>;
export const centerFilesApi = {
  async browse(options: { path?: string; directoriesOnly?: boolean; after?: string; prefix?: string; showHidden?: boolean; resolveFile?: boolean }): Promise<CenterDirectory> {
    return directorySchema.parse(await api.get<unknown>('/files/browse', {
      path: options.path, resolve_file: options.resolveFile ?? false, directories_only: options.directoriesOnly ?? false,
      after: options.after, prefix: options.prefix ?? '', show_hidden: options.showHidden ?? false,
    }));
  },
  async createDirectory(parent: string, name: string): Promise<CenterDirectory> {
    return directorySchema.parse(await api.post<unknown>('/files/directories', { parent, name }));
  },
};
