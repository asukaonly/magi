import { isTauri } from '@tauri-apps/api/core';
import type { TFunction } from 'i18next';
import type { AudioIOError } from './format';

/** Keep device errors consistent across chat recording and the settings test. */
export function audioErrorMessage(t: TFunction<'app'>, error: AudioIOError): string {
  return t(`settings.audio.errors.${error.code}`, { context: isTauri() ? 'desktop' : 'browser' });
}
