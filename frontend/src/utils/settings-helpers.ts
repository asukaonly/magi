/**
 * Settings page helper functions.
 */

import i18n from '@/i18n';
import type { LanguageCode, SystemConfig } from '@/api/modules/config';
import type { ToolConfig } from '@/api/modules/tools';
import type { MemoryToggleFieldId, ToolDraftMap } from '@/types/settings';
import { LANGUAGE_STORAGE_KEY } from '@/constants/settings';

// ============================================================================
// Serialization
// ============================================================================

export const serialize = (value: unknown): string => JSON.stringify(value);

// ============================================================================
// Language Helpers
// ============================================================================

const toI18nLanguage = (language: LanguageCode): string =>
  language === 'zh' ? 'zh-CN' : 'en';

export const persistLanguageSelection = (language: LanguageCode): void => {
  const nextLanguage = toI18nLanguage(language);
  localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  document.documentElement.lang = nextLanguage;
};

export const previewLanguageSelection = async (language: LanguageCode): Promise<void> => {
  const nextLanguage = toI18nLanguage(language);
  document.documentElement.lang = nextLanguage;
  await i18n.changeLanguage(nextLanguage);
};

// ============================================================================
// Tool Draft Helpers
// ============================================================================

export const buildToolDraftSnapshot = (tools: ToolConfig[]): ToolDraftMap =>
  Object.fromEntries(
    tools.map((tool) => [
      tool.name,
      {
        enabled: tool.enabled,
        values: structuredClone(tool.current_values || {}),
      },
    ])
  );

// ============================================================================
// Memory Draft Helpers
// ============================================================================

export const applyMemoryToggle = (
  memory: SystemConfig['memory'],
  field: MemoryToggleFieldId,
  checked: boolean
): void => {
  if (field === 'l1' && !checked) {
    memory.l1.enabled = false;
    memory.l2.enabled = false;
    memory.l3.enabled = false;
    memory.l4.enabled = false;
    memory.l2.vectors_enabled = false;
    memory.l3.llm_summary_enabled = false;
    return;
  }

  if (field === 'l2' && !checked) {
    memory.l2.enabled = false;
    memory.l2.vectors_enabled = false;
    return;
  }

  if (field === 'l3' && !checked) {
    memory.l3.enabled = false;
    memory.l3.llm_summary_enabled = false;
    return;
  }

  if (field === 'l4' && !checked) {
    memory.l4.enabled = false;
    return;
  }

  memory[field].enabled = checked;
};

// ============================================================================
// Diff Helpers
// ============================================================================

export const diffFlatMaps = (
  saved: Record<string, unknown>,
  draft: Record<string, unknown>
): Record<string, unknown> => {
  const keys = new Set([...Object.keys(saved), ...Object.keys(draft)]);
  const updates: Record<string, unknown> = {};
  for (const key of keys) {
    if (serialize(saved[key] ?? null) !== serialize(draft[key] ?? null)) {
      updates[key] = draft[key];
    }
  }
  return updates;
};
