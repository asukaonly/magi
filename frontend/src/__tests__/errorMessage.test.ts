import { describe, expect, it } from 'vitest';
import { getErrorMessage } from '@/utils/error-handler';

describe('rejected value error messages', () => {
  it('accepts native errors and normalized API errors', () => {
    expect(getErrorMessage(new Error('Connection failed'))).toBe('Connection failed');
    expect(getErrorMessage({ code: 'NETWORK_ERROR', message: 'No response' })).toBe('No response');
  });

  it.each([null, undefined, 42, 'plain rejection', {}, { message: {} }, { message: false }])(
    'keeps non-message values out of rendered error text: %j', value => {
      expect(getErrorMessage(value)).toBeUndefined();
    },
  );
});
