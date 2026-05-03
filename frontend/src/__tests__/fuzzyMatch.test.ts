import { describe, expect, it } from 'vitest';
import { fuzzyScore } from '@/lib/fuzzyMatch';

describe('fuzzyScore', () => {
  it('returns 0 for empty target', () => {
    expect(fuzzyScore('foo', '')).toBe(0);
  });

  it('returns 1 for empty query (everything matches)', () => {
    expect(fuzzyScore('', 'foo')).toBe(1);
  });

  it('exact match scores highest', () => {
    expect(fuzzyScore('clear', 'clear')).toBe(1000);
  });

  it('prefix beats substring beats subsequence', () => {
    const prefix = fuzzyScore('cl', 'clear');
    const substring = fuzzyScore('ar', 'clear');
    const subsequence = fuzzyScore('cr', 'clear');
    expect(prefix).toBeGreaterThan(substring);
    expect(substring).toBeGreaterThan(subsequence);
    expect(subsequence).toBeGreaterThan(0);
  });

  it('word-start beats mid-string substring', () => {
    const wordStart = fuzzyScore('iss', 'github_issues'); // after `_`
    const mid = fuzzyScore('hub', 'github_issues');
    expect(wordStart).toBeGreaterThan(mid);
  });

  it('case-insensitive', () => {
    expect(fuzzyScore('READ', 'readme')).toBeGreaterThan(0);
    expect(fuzzyScore('readme', 'README')).toBe(1000);
  });

  it('returns 0 when no subsequence match', () => {
    expect(fuzzyScore('xyz', 'clear')).toBe(0);
  });

  it('subsequence score increases with character count', () => {
    const short = fuzzyScore('ab', 'abcdefghij');
    const long = fuzzyScore('abcdef', 'abcdefghij');
    expect(long).toBeGreaterThan(short);
  });
});
