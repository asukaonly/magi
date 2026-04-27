import { describe, expect, it } from 'vitest';
import { normalizeAssistantMarkdownContent } from '@/domain/chat/markdown';

describe('normalizeAssistantMarkdownContent', () => {
  it('unwraps leading markdown document fences for assistant rendering', () => {
    const normalized = normalizeAssistantMarkdownContent(
      '```markdown\n# Report\n\n| A | B |\n|---|---|\n| 1 | 2 |\n```\n\nTail note',
    );

    expect(normalized).toBe('# Report\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nTail note');
  });

  it('keeps non-markdown code fences unchanged', () => {
    const content = '```json\n{"ok": true}\n```';

    expect(normalizeAssistantMarkdownContent(content)).toBe(content);
  });
});