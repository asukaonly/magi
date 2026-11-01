import { describe, expect, it } from 'vitest';
import { findBoundaryViolations } from './check-boundaries.mjs';

const srcRoot = '/repo/frontend/src';

describe('frontend boundary checker', () => {
  it('keeps portable client code independent of the desktop and view state', () => {
    const violations = findBoundaryViolations([{
      filePath: `${srcRoot}/client/http.ts`,
      source: "import { invoke } from '@tauri-apps/api/core';\nimport { getRuntimeConfig } from '@/runtime/config';",
    }], { srcRoot });
    expect(violations.map((item) => item.importedLayer)).toEqual(['desktop host', 'runtime']);
  });
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
