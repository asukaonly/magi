import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { applyMemoryToggle } from '@/utils/settings-helpers';

vi.mock('@/i18n', () => ({
  default: {
    changeLanguage: vi.fn(),
  },
}));

const createMemoryConfig = () => structuredClone(DEFAULT_SYSTEM_CONFIG.memory);

describe('settings helpers', () => {
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
});