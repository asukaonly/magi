import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'magi.tts.auto.v1';
const listeners = new Set<() => void>();

function readAutomaticSpeech(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key === null) listener();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

export function setAutomaticSpeech(enabled: boolean): void {
  localStorage.setItem(STORAGE_KEY, String(enabled));
  listeners.forEach((listener) => listener());
}

export function useAutomaticSpeech(): boolean {
  return useSyncExternalStore(subscribe, readAutomaticSpeech);
}
