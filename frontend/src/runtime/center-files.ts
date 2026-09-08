import { requestCenterPath } from '@/stores/center-path-picker';

/** Select an existing path on the active center, including in local mode. */
export function pickCenterDirectory(defaultPath?: string | null): Promise<string | undefined> {
  return requestCenterPath('directory', defaultPath);
}
export function pickCenterFile(defaultPath?: string | null): Promise<string | undefined> {
  return requestCenterPath('file', defaultPath);
}
