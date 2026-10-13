import { createInstance } from 'i18next';
import { describe, expect, it } from 'vitest';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';

describe('memory source labels', () => {
  it.each([['en', 'Summaries'], ['zh-CN', '总结']])('names summary sources in %s', async (language, expected) => {
    const i18n = createInstance();
    await i18n.init({ lng: language, defaultNS: 'app', resources: { en: { app: en }, 'zh-CN': { app: zh } } });
    expect(getMemorySourceLabel(i18n.t.bind(i18n), 'memory_summary')).toBe(expected);
    expect(getMemorySourceLabel(i18n.t.bind(i18n), 'synthetic_validation')).toBe('synthetic_validation');
  });
});
