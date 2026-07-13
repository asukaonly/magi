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
  /** i18n key describing the exact data scope shown during first context. */
  scopeKey?: string;
  /** i18n key for first-context-specific value copy. */
  firstContextValueKey?: string;
  /** Stable recommendation category used even after an active sibling is hidden by the backend. */
  recommendationCategory?: string;
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
    firstContextValueKey: 'emptyState.plugins.chromeHistory.firstContextValue',
    scopeKey: 'emptyState.plugins.chromeHistory.scope',
    recommendationCategory: 'browser_history',
    iconId: 'chrome',
  },
  'safari-history': {
    titleKey: 'emptyState.plugins.safariHistory.title',
    valueKey: 'emptyState.plugins.safariHistory.value',
    firstContextValueKey: 'emptyState.plugins.safariHistory.firstContextValue',
    scopeKey: 'emptyState.plugins.safariHistory.scope',
    recommendationCategory: 'browser_history',
    iconId: 'safari',
  },
  'firefox-history': {
    titleKey: 'emptyState.plugins.firefoxHistory.title',
    valueKey: 'emptyState.plugins.firefoxHistory.value',
    firstContextValueKey: 'emptyState.plugins.firefoxHistory.firstContextValue',
    scopeKey: 'emptyState.plugins.firefoxHistory.scope',
    recommendationCategory: 'browser_history',
    iconId: 'firefoxbrowser',
  },
  'edge-history': {
    titleKey: 'emptyState.plugins.edgeHistory.title',
    valueKey: 'emptyState.plugins.edgeHistory.value',
    firstContextValueKey: 'emptyState.plugins.edgeHistory.firstContextValue',
    scopeKey: 'emptyState.plugins.edgeHistory.scope',
    recommendationCategory: 'browser_history',
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
    firstContextValueKey: 'emptyState.plugins.calendar.firstContextValue',
    scopeKey: 'emptyState.plugins.calendar.scope',
    recommendationCategory: 'calendar',
    iconId: 'calendar',
  },
  'git-activity': {
    titleKey: 'emptyState.plugins.gitActivity.title',
    valueKey: 'emptyState.plugins.gitActivity.value',
    firstContextValueKey: 'emptyState.plugins.gitActivity.firstContextValue',
    scopeKey: 'emptyState.plugins.gitActivity.scope',
    recommendationCategory: 'code_activity',
    iconId: 'git',
  },
  'photo-library': {
    titleKey: 'emptyState.plugins.photoLibrary.title',
    valueKey: 'emptyState.plugins.photoLibrary.value',
    firstContextValueKey: 'emptyState.plugins.photoLibrary.firstContextValue',
    scopeKey: 'emptyState.plugins.photoLibrary.scope',
    recommendationCategory: 'photos',
    iconId: 'photo',
  },
  // NOTE: this plugin's id is underscore (`coding_agent_history`), unlike the
  // hyphenated ids above — it must match the manifest plugin_id exactly or the
  // empty-state filter drops it.
  'coding_agent_history': {
    titleKey: 'emptyState.plugins.codingAgentHistory.title',
    valueKey: 'emptyState.plugins.codingAgentHistory.value',
    firstContextValueKey: 'emptyState.plugins.codingAgentHistory.firstContextValue',
    scopeKey: 'emptyState.plugins.codingAgentHistory.scope',
    recommendationCategory: 'code_activity',
    iconId: 'code',
  },
  'github-activity': {
    titleKey: 'emptyState.plugins.githubActivity.title',
    valueKey: 'emptyState.plugins.githubActivity.value',
    firstContextValueKey: 'emptyState.plugins.githubActivity.firstContextValue',
    scopeKey: 'emptyState.plugins.githubActivity.scope',
    recommendationCategory: 'code_activity',
    iconId: 'github',
  },
  'obsidian-vault': {
    titleKey: 'emptyState.plugins.obsidianVault.title',
    valueKey: 'emptyState.plugins.obsidianVault.value',
    firstContextValueKey: 'emptyState.plugins.obsidianVault.firstContextValue',
    scopeKey: 'emptyState.plugins.obsidianVault.scope',
    recommendationCategory: 'notes',
    iconId: 'obsidian',
  },
  'local-documents': {
    titleKey: 'emptyState.plugins.localDocuments.title',
    valueKey: 'emptyState.plugins.localDocuments.value',
    firstContextValueKey: 'emptyState.plugins.localDocuments.firstContextValue',
    scopeKey: 'emptyState.plugins.localDocuments.scope',
    recommendationCategory: 'notes',
    iconId: 'file-text',
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

/**
 * First-run sources that can backfill useful history immediately. This list is
 * broader than the legacy empty-state list, while still excluding purely
 * forward-looking capture sources.
 */
export const FIRST_CONTEXT_PRIORITY_PLUGINS = [
  'chrome-history',
  'calendar',
  'coding_agent_history',
  'git-activity',
  'github-activity',
  'obsidian-vault',
  'local-documents',
  'photo-library',
] as const;

export function getEmptyStatePluginMeta(pluginId: string): EmptyStatePluginMeta | undefined {
  return META[pluginId];
}
