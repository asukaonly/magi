import { describe, expect, it, beforeEach, vi } from 'vitest';

import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import {
  applyMemoryToggle,
  persistLanguageSelection,
  previewLanguageSelection,
} from '@/utils/settings-helpers';

const { changeLanguageMock } = vi.hoisted(() => ({
  changeLanguageMock: vi.fn(),
}));

vi.mock('@/i18n', () => ({
  default: {
    changeLanguage: changeLanguageMock,
  },
}));

const createMemoryConfig = () => structuredClone(DEFAULT_SYSTEM_CONFIG.memory);

const createStorage = (): Storage => {
  const values = new Map<string, string>();

  return {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key: string) {
      return values.has(key) ? values.get(key)! : null;
    },
    key(index: number) {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key: string) {
      values.delete(key);
    },
    setItem(key: string, value: string) {
      values.set(key, String(value));
    },
  };
};

describe('settings helpers', () => {
  beforeEach(() => {
    changeLanguageMock.mockReset();
    changeLanguageMock.mockResolvedValue(undefined);
    const storage = createStorage();
    vi.stubGlobal('localStorage', storage);
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: storage,
    });
    document.documentElement.lang = 'zh-CN';
  });

  it('disabling L1 cascades off downstream memory layers and dependent features', () => {
    const memory = createMemoryConfig();
    memory.l1.enabled = true;
    memory.l2.enabled = true;
    memory.l3.enabled = true;
    memory.l4.enabled = true;
    memory.l2.vectors_enabled = true;
    memory.l3.llm_summary_enabled = true;

    applyMemoryToggle(memory, 'l1', false);

    expect(memory.l1.enabled).toBe(false);
    expect(memory.l2.enabled).toBe(false);
    expect(memory.l3.enabled).toBe(false);
    expect(memory.l4.enabled).toBe(false);
    expect(memory.l2.vectors_enabled).toBe(false);
    expect(memory.l3.llm_summary_enabled).toBe(false);
  });

  it('disabling L2 keeps lower layer switches intact while clearing vector extraction', () => {
    const memory = createMemoryConfig();
    memory.l1.enabled = true;
    memory.l2.enabled = true;
    memory.l3.enabled = true;
    memory.l4.enabled = true;
    memory.l2.vectors_enabled = true;

    applyMemoryToggle(memory, 'l2', false);

    expect(memory.l1.enabled).toBe(true);
    expect(memory.l2.enabled).toBe(false);
    expect(memory.l2.vectors_enabled).toBe(false);
    expect(memory.l3.enabled).toBe(true);
    expect(memory.l4.enabled).toBe(true);
  });

  it('enabling a memory layer only changes that layer enabled flag', () => {
    const memory = createMemoryConfig();
    memory.l3.enabled = false;
    memory.l3.llm_summary_enabled = false;

    applyMemoryToggle(memory, 'l3', true);

    expect(memory.l3.enabled).toBe(true);
    expect(memory.l3.llm_summary_enabled).toBe(false);
  });

  it('persists the raw language code and updates document language', () => {
    persistLanguageSelection('en');

    expect(localStorage.getItem('magi_language')).toBe('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('previews the selected language in the running app', async () => {
    await previewLanguageSelection('en');

    expect(document.documentElement.lang).toBe('en');
    expect(changeLanguageMock).toHaveBeenCalledWith('en');
  });
});