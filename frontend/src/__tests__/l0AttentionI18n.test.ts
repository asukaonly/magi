import { describe, expect, it } from 'vitest';

import enApp from '@/i18n/locales/en/app.json';
import zhCnApp from '@/i18n/locales/zh-CN/app.json';

const REQUIRED_L0_KEYS = [
  'memory.l0.totalAttentionItems',
  'memory.l0.attentionItems',
  'memory.l0.attentionCount',
  'memory.l0.workbenchItemCount',
  'memory.l0.kinds.focus',
  'memory.l0.kinds.situation',
  'memory.l0.kinds.open_loop',
  'memory.l0.kinds.active_object',
  'memory.l0.kinds.constraint',
  'memory.l0.kinds.consensus',
  'memory.l0.statuses.active',
  'memory.l0.statuses.background',
  'memory.l0.statuses.resolved',
  'memory.l0.statuses.superseded',
  'memory.l0.evidenceModes.direct',
  'memory.l0.evidenceModes.inferred',
  'memory.l0.salience',
  'memory.l0.confidence',
  'memory.l0.lastReinforced',
  'memory.l0.expiresAt',
  'memory.pages.workbench.subtitle',
  'memory.pages.workbench.shellEmpty',
] as const;

const getValue = (resource: unknown, key: string): unknown =>
  key.split('.').reduce<unknown>((current, part) => {
    if (!current || typeof current !== 'object') {
      return undefined;
    }
    return (current as Record<string, unknown>)[part];
  }, resource);

describe('L0 attention i18n', () => {
  it('keeps every attention kind, status, and evidence label translated', () => {
    for (const [locale, resource] of Object.entries({ en: enApp, 'zh-CN': zhCnApp })) {
      const missingKeys = REQUIRED_L0_KEYS.filter((key) => {
        const value = getValue(resource, key);
        return typeof value !== 'string' || value.length === 0;
      });

      expect(missingKeys, `${locale} missing L0 keys`).toEqual([]);
    }
  });
});
