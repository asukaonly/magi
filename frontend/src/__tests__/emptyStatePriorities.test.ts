import { describe, expect, it } from 'vitest';
import {
  EMPTY_STATE_PRIORITY_PLUGINS,
  getEmptyStatePluginMeta,
  type EmptyStatePluginMeta,
} from '../constants/emptyStatePriorities';

describe('EMPTY_STATE_PRIORITY_PLUGINS', () => {
  it('lists the 4 Plan 3 priority plugin ids in display order', () => {
    expect(EMPTY_STATE_PRIORITY_PLUGINS).toEqual([
      'chrome-history',
      'system-calendar',
      'git-activity',
      'photo-library',
    ]);
  });

  it('exposes display metadata for every priority plugin', () => {
    for (const pluginId of EMPTY_STATE_PRIORITY_PLUGINS) {
      const meta: EmptyStatePluginMeta | undefined = getEmptyStatePluginMeta(pluginId);
      expect(meta, `meta for ${pluginId}`).toBeDefined();
      expect(meta?.titleKey).toBeTypeOf('string');
      expect(meta?.valueKey).toBeTypeOf('string');
    }
  });

  it('returns undefined for unknown plugins', () => {
    expect(getEmptyStatePluginMeta('not-a-real-plugin')).toBeUndefined();
  });
});
