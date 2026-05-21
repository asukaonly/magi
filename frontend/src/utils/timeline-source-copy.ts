import type { SensorSourceStatusItem } from '@/api/modules/sensors';

type TimelineTranslateFn = (key: string) => string;

const normalizeIdentity = (value: string): string => value.replace(/[_-]/g, '').toLowerCase();

const resolveTranslation = (
  t: TimelineTranslateFn,
  key: string
): string | null => {
  const translated = t(key);
  return translated !== key ? translated : null;
};

const resolveSourceTranslation = (
  t: TimelineTranslateFn,
  sourceName: string
): string | null =>
  resolveTranslation(t, `settings.timeline.sources.${sourceName}`)
  || resolveTranslation(t, `settings.tabs.${sourceName}`);

const shouldUsePluginCopy = (
  source: Pick<SensorSourceStatusItem, 'source_name' | 'plugin_id'>
): boolean => normalizeIdentity(source.source_name) === normalizeIdentity(source.plugin_id);

export const getTimelineSourceDisplayName = (
  t: TimelineTranslateFn,
  source: Pick<
    SensorSourceStatusItem,
    'source_name' | 'plugin_id' | 'display_name' | 'display_name_translated'
  >
): string =>
  source.display_name_translated
  || resolveSourceTranslation(t, source.source_name)
  || (shouldUsePluginCopy(source) ? resolveTranslation(t, `settings.plugins.${source.plugin_id}.name`) : null)
  || source.display_name
  || source.source_name;

export const getTimelineSourceDescription = (
  t: TimelineTranslateFn,
  source: Pick<
    SensorSourceStatusItem,
    'source_name' | 'plugin_id' | 'description' | 'description_translated'
  >
): string =>
  source.description_translated
  || resolveTranslation(t, `settings.timeline.sourceDesc.${source.source_name}`)
  || (shouldUsePluginCopy(source) ? resolveTranslation(t, `settings.plugins.${source.plugin_id}.description`) : null)
  || source.description
  || "";
