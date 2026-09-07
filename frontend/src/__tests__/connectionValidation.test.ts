import { describe, expect, it } from 'vitest';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';
import { validateConnectionField } from '@/components/plugins/connection-validation';

const field: ExtensionFieldSpec = {
  key: 'limit', label: 'Limit', type: 'number', description: '', required: true,
  default: null, minimum: 1, maximum: 10, options: [], section: 'general', surface: 'extensions', order: 0,
};

describe('connection field admission', () => {
  it('distinguishes omitted setup from explicit malformed values', () => {
    expect(validateConnectionField(field, undefined, {}, false)).toBeNull();
    expect(validateConnectionField(field, undefined, {}, true)).toBe('required');
    for (const value of [null, '', NaN, Infinity, 0, 11, '5']) {
      expect(validateConnectionField(field, value, {}, false)).toBe('number');
    }
    expect(validateConnectionField(field, 5, {}, true)).toBeNull();
  });
  it('only requires active fields but still validates provided hidden values', () => {
    const conditional = { ...field, depends_on_key: 'mode', depends_on_values: ['custom'] };
    expect(validateConnectionField(conditional, undefined, { mode: 'auto' }, true)).toBeNull();
    expect(validateConnectionField(conditional, undefined, { mode: 'custom' }, true)).toBe('required');
    expect(validateConnectionField(conditional, 'bad', { mode: 'auto' }, true)).toBe('number');
  });
  it('allows declared defaults and enforces selector membership on disabled drafts', () => {
    expect(validateConnectionField({ ...field, default: 5 }, undefined, {}, true)).toBeNull();
    const selector = { ...field, type: 'select' as const, options: [{ label: 'Daily', value: 'daily' }] };
    expect(validateConnectionField(selector, 'daily', {}, false)).toBeNull();
    expect(validateConnectionField(selector, '', {}, false)).not.toBeNull();
    expect(validateConnectionField(selector, 'other', {}, false)).toBe('selection');
  });
});
