/**
 * Priority list for first-context CTA cards on Timeline, Memory, and first-run
 * prompts.
 *
 * Order matters: cards render top-to-bottom (or left-to-right in a grid) in
 * the order declared here. Each plugin's display metadata is consumed by
 * `<EmptyStateSensorCard>` for icon/title/value-statement.
 *
 * Browser history is handled as a single slot: if Chrome is unavailable, the
 * first available browser source from BROWSER_HISTORY_PRIORITY_PLUGINS takes
 * that top position.
 */

export interface EmptyStatePluginMeta {
  /** i18n key for the card title (e.g. "Chrome history"). */
  titleKey: string;
  /** i18n key for the 1-line value statement. */
  valueKey: string;
  /**
   * Optional icon identifier — passed to the card. The mapping from id to
   * actual asset is owned by the card component. Use plain string ids; do
   * not import asset modules here so this module stays loader-free.
   */
  iconId?: string;
}

const META: Record<string, EmptyStatePluginMeta> = {
  'chrome-history': {
    titleKey: 'emptyState.plugins.chromeHistory.title',
    valueKey: 'emptyState.plugins.chromeHistory.value',
    iconId: 'chrome',
  },
  'safari-history': {
    titleKey: 'emptyState.plugins.safariHistory.title',
    valueKey: 'emptyState.plugins.safariHistory.value',
    iconId: 'safari',
  },
  'firefox-history': {
    titleKey: 'emptyState.plugins.firefoxHistory.title',
    valueKey: 'emptyState.plugins.firefoxHistory.value',
    iconId: 'firefoxbrowser',
  },
  'edge-history': {
    titleKey: 'emptyState.plugins.edgeHistory.title',
    valueKey: 'emptyState.plugins.edgeHistory.value',
    iconId: 'browser',
  },
  'screenshot_timeline': {
    titleKey: 'emptyState.plugins.screenshotTimeline.title',
    valueKey: 'emptyState.plugins.screenshotTimeline.value',
    iconId: 'screen',
  },
  'calendar': {
    titleKey: 'emptyState.plugins.calendar.title',
    valueKey: 'emptyState.plugins.calendar.value',
    iconId: 'calendar',
  },
  'git-activity': {
    titleKey: 'emptyState.plugins.gitActivity.title',
    valueKey: 'emptyState.plugins.gitActivity.value',
    iconId: 'git',
  },
  'photo-library': {
    titleKey: 'emptyState.plugins.photoLibrary.title',
    valueKey: 'emptyState.plugins.photoLibrary.value',
    iconId: 'photo',
  },
  // NOTE: this plugin's id is underscore (`coding_agent_history`), unlike the
  // hyphenated ids above — it must match the manifest plugin_id exactly or the
  // empty-state filter drops it.
  'coding_agent_history': {
    titleKey: 'emptyState.plugins.codingAgentHistory.title',
    valueKey: 'emptyState.plugins.codingAgentHistory.value',
    iconId: 'code',
  },
};

export const BROWSER_HISTORY_PRIORITY_PLUGINS = [
  'chrome-history',
  'safari-history',
  'firefox-history',
  'edge-history',
] as const;

export const EMPTY_STATE_PRIORITY_PLUGINS = [
  'chrome-history',
  'coding_agent_history',
  'calendar',
  'git-activity',
  'photo-library',
] as const;

export function getEmptyStatePluginMeta(pluginId: string): EmptyStatePluginMeta | undefined {
  return META[pluginId];
}
