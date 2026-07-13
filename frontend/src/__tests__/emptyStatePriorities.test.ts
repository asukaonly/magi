import { describe, expect, it } from 'vitest';
import {
  BROWSER_HISTORY_PRIORITY_PLUGINS,
  EMPTY_STATE_PRIORITY_PLUGINS,
  FIRST_CONTEXT_PRIORITY_PLUGINS,
  getEmptyStatePluginMeta,
  type EmptyStatePluginMeta,
} from '../constants/emptyStatePriorities';
import enOnboarding from '../i18n/locales/en/onboarding.json';
import zhOnboarding from '../i18n/locales/zh-CN/onboarding.json';

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
      'calendar',
      'git-activity',
      'photo-library',
    ]);
  });

  it('lists browser history plugin ids in replacement order', () => {
    expect(BROWSER_HISTORY_PRIORITY_PLUGINS).toEqual([
      'chrome-history',
      'safari-history',
      'firefox-history',
      'edge-history',
    ]);
  });

  it('exposes display metadata for every priority plugin', () => {
    const pluginIds = [
      ...BROWSER_HISTORY_PRIORITY_PLUGINS,
      ...EMPTY_STATE_PRIORITY_PLUGINS,
    ];
    for (const pluginId of pluginIds) {
      const meta: EmptyStatePluginMeta | undefined = getEmptyStatePluginMeta(pluginId);
      expect(meta, `meta for ${pluginId}`).toBeDefined();
      expect(meta?.titleKey).toBeTypeOf('string');
      expect(meta?.valueKey).toBeTypeOf('string');
    }
  });

  it('returns undefined for unknown plugins', () => {
    expect(getEmptyStatePluginMeta('not-a-real-plugin')).toBeUndefined();
  });

  it('defines complete metadata for every first-context recommendation', () => {
    expect(FIRST_CONTEXT_PRIORITY_PLUGINS).toEqual([
      'chrome-history',
      'calendar',
      'coding_agent_history',
      'git-activity',
      'github-activity',
      'obsidian-vault',
      'local-documents',
      'photo-library',
    ]);
    for (const pluginId of FIRST_CONTEXT_PRIORITY_PLUGINS) {
      const meta = getEmptyStatePluginMeta(pluginId);
      expect(meta?.scopeKey, `scope for ${pluginId}`).toBeTypeOf('string');
      expect(meta?.firstContextValueKey, `first-context value for ${pluginId}`).toBeTypeOf('string');
      expect(meta?.recommendationCategory, `category for ${pluginId}`).toBeTypeOf('string');
    }
  });

  it('keeps standard empty-state copy separate from first-context copy', () => {
    expect(enOnboarding.emptyState.heading).toBe('Let me see your activity');
    expect(enOnboarding.emptyState.firstContextHeading).toBe('Recommended starting point');
    expect(zhOnboarding.emptyState.heading).toBe('让 magi 看看你的活动');
    expect(zhOnboarding.emptyState.firstContextHeading).toBe('推荐从这里开始');
    expect(enOnboarding.emptyState.plugins.chromeHistory.value).toBe(
      "Lets magi see what you've been reading online",
    );
    expect(zhOnboarding.emptyState.plugins.chromeHistory.value).toBe(
      '让 magi 看到你最近在网上读什么',
    );
  });
});
