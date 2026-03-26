import type { TimelineSourceStatusItem } from '@/api/modules/timeline';

type TimelineTranslateFn = (key: string) => string;

const resolveTranslation = (
  t: TimelineTranslateFn,
  key: string
): string | null => {
  const translated = t(key);
  return translated !== key ? translated : null;
};

export const getTimelineSourceDisplayName = (
  t: TimelineTranslateFn,
  source: Pick<TimelineSourceStatusItem, 'source_name' | 'plugin_id' | 'display_name'>
): string =>
  resolveTranslation(t, `settings.tabs.${source.source_name}`)
  || source.display_name
  || resolveTranslation(t, `settings.plugins.${source.plugin_id}.name`)
  || source.source_name;

export const getTimelineSourceDescription = (
  t: TimelineTranslateFn,
  source: Pick<TimelineSourceStatusItem, 'source_name' | 'plugin_id' | 'description'>
): string =>
  resolveTranslation(t, `settings.timeline.sourceDesc.${source.source_name}`)
  || source.description
  || resolveTranslation(t, `settings.plugins.${source.plugin_id}.description`)
  || "";
