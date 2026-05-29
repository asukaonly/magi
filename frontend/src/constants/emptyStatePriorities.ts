/**
 * Plan 3 priority list for empty-state CTA cards on Timeline and Memory pages.
 *
 * Order matters: cards render top-to-bottom (or left-to-right in a grid) in
 * the order declared here. Each plugin's display metadata is consumed by
 * `<EmptyStateSensorCard>` for icon/title/value-statement.
 *
 * Plan 4 will replace this hardcoded list with a category-driven assembly
 * driven by `suggestion_descriptor.category` from each plugin manifest, but
 * for Plan 3 a simple priority order keeps the surface small.
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
};

export const EMPTY_STATE_PRIORITY_PLUGINS = [
  'chrome-history',
  'calendar',
  'git-activity',
  'photo-library',
] as const;

export function getEmptyStatePluginMeta(pluginId: string): EmptyStatePluginMeta | undefined {
  return META[pluginId];
}
