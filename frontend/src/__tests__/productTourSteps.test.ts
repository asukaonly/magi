import { describe, it, expect } from 'vitest';
import { PRODUCT_TOUR_STEPS, pickZeroConfigSource } from '@/components/onboarding/productTourSteps';
import type { InstallableItem } from '@/api/modules/systemSuggestions';

describe('productTourSteps', () => {
  it('has ordered steps targeting chat/timeline/memory/bell', () => {
    expect(PRODUCT_TOUR_STEPS.map((s) => s.targetTestId)).toEqual([
      'tour-target-conversation',
      'tour-target-timeline',
      'tour-target-memory',
      'tour-target-bell',
    ]);
    // exactly one step offers the connect action
    expect(PRODUCT_TOUR_STEPS.filter((s) => s.connect).length).toBe(1);
  });

  it('picks the highest-priority zero-config, not-installed-active source', () => {
    const items: InstallableItem[] = [
      { plugin_id: 'photo-library', category: 'photo', installed: false, rationale: { zh: '', en: '' } },
      { plugin_id: 'chrome-history', category: 'browser_history', installed: false, rationale: { zh: '', en: '' } },
    ];
    expect(pickZeroConfigSource(items)?.plugin_id).toBe('chrome-history');
    expect(pickZeroConfigSource([])).toBeNull();
    // non-zero-config-only list → null
    expect(pickZeroConfigSource([items[0]])).toBeNull();
  });
});
