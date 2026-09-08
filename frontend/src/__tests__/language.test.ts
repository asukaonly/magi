import { describe, expect, it } from 'vitest';

import {
  resolveInitialLanguage,
  toI18nLanguage,
} from '@/utils/language';

describe('language defaults', () => {
  it('uses the browser language when no language has been saved', () => {
    expect(resolveInitialLanguage({ storedLanguage: null, browserLanguage: 'zh-CN' })).toBe('zh');
    expect(resolveInitialLanguage({ storedLanguage: null, browserLanguage: 'en-US' })).toBe('en');
    expect(resolveInitialLanguage({ storedLanguage: null, browserLanguage: 'ja-JP' })).toBe('en');
  });

  it('keeps an explicitly saved language ahead of the browser language', () => {
    expect(resolveInitialLanguage({ storedLanguage: 'en', browserLanguage: 'zh-CN' })).toBe('en');
    expect(resolveInitialLanguage({ storedLanguage: 'zh', browserLanguage: 'en-US' })).toBe('zh');
  });

  it('maps app language codes to i18n language tags', () => {
    expect(toI18nLanguage('zh')).toBe('zh-CN');
    expect(toI18nLanguage('en')).toBe('en');
  });

});
