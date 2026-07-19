import { describe, expect, it } from 'vitest';

import { parseSkillArguments } from '@/domain/chat/skill-arguments';

describe('parseSkillArguments', () => {
  it('keeps unquoted multiword text together for one argument', () => {
    expect(parseSkillArguments('review this folder', '<request>')).toEqual({
      ok: true,
      arguments: ['review this folder'],
    });
  });

  it('supports quoted and escaped values for multiple arguments', () => {
    expect(parseSkillArguments(
      '"first value" second\\ value \'third value\'',
      '<first> <second> [third]',
    )).toEqual({
      ok: true,
      arguments: ['first value', 'second value', 'third value'],
    });
  });

  it('removes matching outer quotes for one argument', () => {
    expect(parseSkillArguments('"review this folder"', '<request>')).toEqual({
      ok: true,
      arguments: ['review this folder'],
    });
  });

  it('rejects unmatched quotes and trailing escapes', () => {
    expect(parseSkillArguments('"unfinished', '<request>')).toEqual({
      ok: false,
    });
    expect(parseSkillArguments('unfinished\\', '<first> <second>')).toEqual({
      ok: false,
    });
  });
});
