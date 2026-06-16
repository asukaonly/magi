import { describe, expect, it } from 'vitest';
import {
  EMPTY_STATE_PRIORITY_PLUGINS,
  getEmptyStatePluginMeta,
  type EmptyStatePluginMeta,
} from '../constants/emptyStatePriorities';

describe('EMPTY_STATE_PRIORITY_PLUGINS', () => {
  it('lists the priority plugin ids in display order', () => {
    // These IDs must match the actual `id` field in each plugin.toml in
    // the magi-plugins registry repo. Mismatches mean the plugin is
    // silently never offered in the empty state. The calendar plugin in
    // particular uses id "calendar" (not "system-calendar"); the
    // git-activity plugin lives in plugins/git_activity/ but its id is
    // "git-activity"; coding_agent_history uses an underscore id.
    expect(EMPTY_STATE_PRIORITY_PLUGINS).toEqual([
      'chrome-history',
      'coding_agent_history',
      'screenshot_timeline',
      'calendar',
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
