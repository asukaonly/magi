import { create } from 'zustand';
import { subscribeRuntimeReset } from '@/runtime/config';

type Kind = 'directory' | 'file';
export interface CenterPathRequest {
  id: string;
  kind: Kind;
  defaultPath?: string;
  resolve: (path: string | undefined) => void;
}
export const useCenterPathPickerStore = create<{ request: CenterPathRequest | null }>(() => ({ request: null }));

export function finishCenterPath(id: string, path?: string): void {
  const request = useCenterPathPickerStore.getState().request;
  if (!request || request.id !== id) return;
  useCenterPathPickerStore.setState({ request: null });
  request.resolve(path);
}

export function requestCenterPath(kind: Kind, defaultPath?: string | null): Promise<string | undefined> {
  const previous = useCenterPathPickerStore.getState().request;
  if (previous) finishCenterPath(previous.id);
  return new Promise(resolve => {
    useCenterPathPickerStore.setState({ request: { id: crypto.randomUUID(), kind, defaultPath: defaultPath || undefined, resolve } });
  });
}
subscribeRuntimeReset(() => {
  const request = useCenterPathPickerStore.getState().request;
  if (request) finishCenterPath(request.id);
});
