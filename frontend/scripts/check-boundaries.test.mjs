import { describe, expect, it } from 'vitest';
import { findBoundaryViolations } from './check-boundaries.mjs';

const srcRoot = '/repo/frontend/src';

describe('frontend boundary checker', () => {
  it('flags lower layers importing page modules', () => {
    const violations = findBoundaryViolations(
      [
        {
          filePath: `${srcRoot}/hooks/useThing.ts`,
          source: "import { getPanel } from '@/pages/chat-route-helpers';",
        },
      ],
      { srcRoot },
    );

    expect(violations).toEqual([
      expect.objectContaining({
        importerLayer: 'hooks',
        importedLayer: 'pages',
      }),
    ]);
  });

  it('allows pages to compose hooks', () => {
    const violations = findBoundaryViolations(
      [
        {
          filePath: `${srcRoot}/pages/Chat.tsx`,
          source: "import { useThing } from '@/hooks/useThing';",
        },
      ],
      { srcRoot },
    );

    expect(violations).toEqual([]);
  });
});
