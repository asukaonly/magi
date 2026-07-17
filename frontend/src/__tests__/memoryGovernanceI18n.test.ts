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

describe('memory governance i18n', () => {
  it('keeps object-category and assertion copy complete in both locales', () => {
    const zh = flatten({
      categories: zhCnApp.memory.governance.categories,
      assertions: zhCnApp.memory.governance.assertions,
    });
    const en = flatten({
      categories: enApp.memory.governance.categories,
      assertions: enApp.memory.governance.assertions,
    });

    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
    for (const key of Object.keys(zh)) {
      expect(zh[key], `zh-CN memory.governance.${key} is empty`).not.toBe('');
      expect(en[key], `en memory.governance.${key} is empty`).not.toBe('');
      expect(
        interpolationTokens(en[key]),
        `memory.governance.${key} interpolation tokens differ`
      ).toEqual(interpolationTokens(zh[key]));
    }
  });

  it('does not fall back to Chinese labels on the English governance page', () => {
    const en = flatten({
      categories: enApp.memory.governance.categories,
      assertions: enApp.memory.governance.assertions,
    });

    expect(Object.values(en).filter((value) => /[\u3400-\u9fff]/u.test(value))).toEqual([]);
  });
});
