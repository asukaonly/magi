import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';

import {
  operationErrorMessage,
  operationPhaseLabel,
} from '@/components/settings/memory-data/presentation';
import enApp from '@/i18n/locales/en/app.json';
import zhCnApp from '@/i18n/locales/zh-CN/app.json';

type TranslationTree = Record<string, unknown>;

function flatten(
  value: TranslationTree,
  prefix = '',
  result: Record<string, string> = {},
): Record<string, string> {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      flatten(child as TranslationTree, path, result);
    } else {
      result[path] = String(child ?? '');
    }
  }
  return result;
}

const interpolationTokens = (value: string): string[] =>
  [...value.matchAll(/\{\{\s*([^},\s]+).*?\}\}/g)]
    .map((match) => match[1])
    .sort();

describe('memory portability i18n', () => {
  it('keeps every data-management key and interpolation token aligned', () => {
    const en = flatten(enApp.settings.memory.dataManagement as TranslationTree);
    const zh = flatten(zhCnApp.settings.memory.dataManagement as TranslationTree);

    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
    for (const key of Object.keys(en)) {
      expect(en[key], `en settings.memory.dataManagement.${key} is empty`).not.toBe('');
      expect(zh[key], `zh-CN settings.memory.dataManagement.${key} is empty`).not.toBe('');
      expect(
        interpolationTokens(en[key]),
        `settings.memory.dataManagement.${key} interpolation tokens differ`,
      ).toEqual(interpolationTokens(zh[key]));
    }
  });

  it('does not leak Chinese copy into the English data-management section', () => {
    const en = flatten(enApp.settings.memory.dataManagement as TranslationTree);

    expect(Object.values(en).filter((value) => /[\u3400-\u9fff]/u.test(value))).toEqual([]);
  });

  it('translates every warning emitted by the current backup manifest', () => {
    const warningKeys = [
      'restore_replaces_current_memory',
      'deleted_memories_may_return',
      'l0_runtime_attention_not_restored',
      'chat_records_and_attachments_not_included',
      'source_evidence_may_be_unavailable',
      'raw_history_import_content_redacted',
    ] as const;

    for (const warning of warningKeys) {
      expect(enApp.settings.memory.dataManagement.warnings[warning]).not.toBe('');
      expect(zhCnApp.settings.memory.dataManagement.warnings[warning]).not.toBe('');
    }
  });

  it('maps stable backend codes and phases to product copy', () => {
    const t = ((key: string) => key) as TFunction<'app'>;

    expect(operationErrorMessage(t, 'operation_in_progress', null)).toBe(
      'settings.memory.dataManagement.errors.busy',
    );
    expect(operationErrorMessage(t, 'password_or_integrity_invalid', null)).toBe(
      'settings.memory.dataManagement.errors.wrongPassword',
    );
    expect(operationErrorMessage(t, 'restore_rollback_failed', null)).toBe(
      'settings.memory.dataManagement.errors.rollbackFailed',
    );
    expect(operationPhaseLabel(t, 'shutting_down')).toBe(
      'settings.memory.dataManagement.operation.phases.shuttingDown',
    );
    expect(operationPhaseLabel(t, 'cutover')).toBe(
      'settings.memory.dataManagement.operation.phases.cutover',
    );
  });
});
