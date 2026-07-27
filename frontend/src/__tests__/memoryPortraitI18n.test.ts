import { describe, expect, it } from 'vitest';

import enApp from '@/i18n/locales/en/app.json';
import zhCnApp from '@/i18n/locales/zh-CN/app.json';

type TranslationTree = Record<string, unknown>;

const flatten = (
  value: TranslationTree,
  prefix = '',
  result: Record<string, string> = {}
): Record<string, string> => {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      flatten(child as TranslationTree, path, result);
    } else {
      result[path] = String(child ?? '');
    }
  }
  return result;
};

const interpolationTokens = (value: string): string[] =>
  [...value.matchAll(/\{\{\s*([^},\s]+).*?\}\}/g)]
    .map((match) => match[1])
    .sort();

describe('memory portrait i18n', () => {
  it('keeps every portrait key and interpolation token aligned in Chinese and English', () => {
    const zh = flatten(zhCnApp.memory.portrait as TranslationTree);
    const en = flatten(enApp.memory.portrait as TranslationTree);

    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
    for (const key of Object.keys(zh)) {
      expect(zh[key], `zh-CN memory.portrait.${key} is empty`).not.toBe('');
      expect(en[key], `en memory.portrait.${key} is empty`).not.toBe('');
      expect(
        interpolationTokens(en[key]),
        `memory.portrait.${key} interpolation tokens differ`
      ).toEqual(interpolationTokens(zh[key]));
    }
  });

  it('keeps the personal-profile settings keys removed after moving identity editing to the portrait page', () => {
    for (const resource of [zhCnApp, enApp]) {
      const settings = resource.settings as TranslationTree;
      expect('personalProfile' in settings).toBe(false);
      expect('personalProfileDesc' in settings).toBe(false);
      expect('personalProfile' in (settings.tabs as TranslationTree)).toBe(false);
    }
  });
});
