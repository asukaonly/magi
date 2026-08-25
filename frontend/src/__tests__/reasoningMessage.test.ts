import { describe, expect, it } from 'vitest';

import {
  applyReasoningModifier,
  getReasoningModifierDecoration,
  parseReasoningMessage,
} from '@/domain/chat/reasoning';

describe('reasoning message modifiers', () => {
  it('extracts a known leading modifier from the semantic message', () => {
    expect(parseReasoningMessage('/fast Explain HTTPS')).toEqual({
      message: 'Explain HTTPS',
      preference: 'fast',
      explicit: true,
    });
    expect(parseReasoningMessage('  /DEEP\nCompare both designs')).toEqual({
      message: '\nCompare both designs',
      preference: 'deep',
      explicit: true,
    });
  });

  it('keeps unknown and non-leading slash text as ordinary content', () => {
    expect(parseReasoningMessage('/fastest route')).toEqual({
      message: '/fastest route',
      preference: 'auto',
      explicit: false,
    });
    expect(parseReasoningMessage('Explain /fast mode')).toEqual({
      message: 'Explain /fast mode',
      preference: 'auto',
      explicit: false,
    });
  });

  it('preserves the visible text while isolating the recognized modifier', () => {
    expect(getReasoningModifierDecoration('/fast Explain HTTPS')).toEqual({
      leadingText: '',
      modifierText: '/fast',
      trailingText: ' Explain HTTPS',
    });
    expect(getReasoningModifierDecoration('  /DEEP\nCompare both designs')).toEqual({
      leadingText: '  ',
      modifierText: '/DEEP',
      trailingText: '\nCompare both designs',
    });
    expect(getReasoningModifierDecoration('/fastest route')).toBeNull();
    expect(getReasoningModifierDecoration('Explain /fast mode')).toBeNull();
  });

  it('replaces or removes the visible modifier without hidden state', () => {
    expect(applyReasoningModifier('Explain HTTPS', 'fast')).toBe(
      '/fast Explain HTTPS',
    );
    expect(applyReasoningModifier('/fast Explain HTTPS', 'deep')).toBe(
      '/deep Explain HTTPS',
    );
    expect(applyReasoningModifier('/deep Explain HTTPS', 'auto')).toBe(
      'Explain HTTPS',
    );
  });
});
