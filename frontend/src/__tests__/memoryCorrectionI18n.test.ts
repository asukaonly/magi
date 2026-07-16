import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';

import {
  correctionLocale,
  formatCorrectionScope,
} from '@/components/memory/correction/memoryCorrectionPresentation';
import enApp from '@/i18n/locales/en/app.json';
import zhCnApp from '@/i18n/locales/zh-CN/app.json';

type TranslationTree = Record<string, unknown>;
const MAGI_CONTEXT_ID = `ctx_project_${'a'.repeat(64)}`;

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

describe('memory correction i18n', () => {
  it('keeps every correction key and interpolation token aligned in Chinese and English', () => {
    const zh = flatten(zhCnApp.memory.correction as TranslationTree);
    const en = flatten(enApp.memory.correction as TranslationTree);

    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
    for (const key of Object.keys(zh)) {
      expect(zh[key], `zh-CN memory.correction.${key} is empty`).not.toBe('');
      expect(en[key], `en memory.correction.${key} is empty`).not.toBe('');
      expect(
        interpolationTokens(en[key]),
        `memory.correction.${key} interpolation tokens differ`
      ).toEqual(interpolationTokens(zh[key]));
    }
  });

  it('keeps the correction entry points translated in both locales', () => {
    const resources = [zhCnApp, enApp];

    for (const resource of resources) {
      expect(resource.memory.portrait.world.inspectItems).not.toBe('');
      expect(resource.memory.portrait.world.correct).not.toBe('');
      expect(resource.memory.portrait.world.correctItem).not.toBe('');
      expect(resource.memory.governance.drawer.actions.correctMemory).not.toBe('');
    }
  });

  it('formats English scope text without Chinese punctuation and follows the app language', () => {
    const translations: Record<string, string> = {
      'memory.correction.scopes.project': 'Project',
      'memory.correction.scopes.person': 'Person',
      'memory.correction.history.scopeEntry': '{{label}}: {{value}}',
      'memory.correction.history.scopeNameUnavailable': 'Name unavailable',
      'memory.correction.history.scopeSeparator': ', ',
    };
    const t = ((key: string, options?: Record<string, unknown>) => {
      const template = translations[key] ?? String(options?.defaultValue ?? key);
      return template.replace(/\{\{(\w+)\}\}/g, (_match, name) => String(options?.[name] ?? ''));
    }) as TFunction<'app'>;

    expect(formatCorrectionScope({
      all_of: [
        { dimension: 'project', context_id: MAGI_CONTEXT_ID },
        { dimension: 'person', context_id: `ctx_person_${'b'.repeat(64)}` },
      ],
    }, t, {
      [MAGI_CONTEXT_ID]: 'Magi',
    })).toBe(
      'Project: Magi, Person: Name unavailable'
    );
    expect(correctionLocale('zh')).toBe('zh-CN');
    expect(correctionLocale('en-US')).toBe('en');
  });
});
