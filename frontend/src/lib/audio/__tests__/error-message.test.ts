import { createInstance } from 'i18next';
import { afterEach, describe, expect, it, vi } from 'vitest';
import zh from '@/i18n/locales/zh-CN/app.json';
import en from '@/i18n/locales/en/app.json';
import { audioErrorMessage } from '../error-message';
import { AudioIOError, type AudioErrorCode } from '../format';

const i18n = createInstance();
await i18n.init({ resources: { 'zh-CN': { app: zh }, en: { app: en } }, defaultNS: 'app', lng: 'zh-CN' });
afterEach(() => vi.unstubAllGlobals());

const errors: AudioErrorCode[] = [
  'insecure_context', 'capture_unavailable', 'processing_unavailable',
  'sample_rate_unsupported', 'permission_denied', 'unsupported',
];

describe.each(['zh-CN', 'en'])('audio feedback in %s', (language) => {
  it.each(errors)('gives desktop guidance for %s without suggesting another desktop app', (code) => {
    vi.stubGlobal('isTauri', true);
    const message = audioErrorMessage(i18n.getFixedT(language, 'app'), new AudioIOError(code, 'Diagnostic only'));
    expect(message).not.toMatch(/浏览器|browser|settings\.audio|Diagnostic only/i);
  });
  it('keeps browser guidance for microphone access outside the desktop app', () => {
    vi.stubGlobal('isTauri', false);
    const message = audioErrorMessage(i18n.getFixedT(language, 'app'), new AudioIOError('capture_unavailable', 'Diagnostic only'));
    expect(message).toMatch(/浏览器|browser/i);
  });
});
