import type { SourceStatusItem } from '@/api/modules/sources';

type TimelineTranslateFn = (key: string) => string;

const resolveTranslation = (
  t: TimelineTranslateFn,
  key: string
): string | null => {
  const translated = t(key);
  return translated !== key ? translated : null;
};

/**
 * Resolution order (Phase 4):
 *   1. ``source.display_name_translated`` (API, plugin i18n)
 *   2. shared host i18n at ``settings.timeline.sources.{source_name}``
 *      or ``settings.tabs.{source_name}`` — shared UI infra for built-in
 *      tabs that pre-date the plugin system
 *   3. raw ``source.display_name`` / ``source.source_name``
 */
export const getTimelineSourceDisplayName = (
  t: TimelineTranslateFn,
  source: Pick<
    SourceStatusItem,
    'source_name' | 'plugin_id' | 'display_name' | 'display_name_translated'
  >
): string =>
  source.display_name_translated
  || resolveTranslation(t, `settings.timeline.sources.${source.source_name}`)
  || resolveTranslation(t, `settings.tabs.${source.source_name}`)
  || source.display_name
  || source.source_name;

/**
 * Resolution order (Phase 4):
 *   1. ``source.description_translated`` (API, plugin i18n)
 *   2. shared host i18n at ``settings.timeline.sourceDesc.{source_name}``
 *   3. raw ``source.description``
 */
export const getTimelineSourceDescription = (
  t: TimelineTranslateFn,
  source: Pick<
    SourceStatusItem,
    'source_name' | 'plugin_id' | 'description' | 'description_translated'
  >
): string =>
  source.description_translated
  || resolveTranslation(t, `settings.timeline.sourceDesc.${source.source_name}`)
  || source.description
  || "";
