import type { SensorSourceStatusItem } from '@/api/modules/sensors';
import { getTimelineSourceDescription, getTimelineSourceDisplayName } from '@/utils/timeline-source-copy';

type TimelineTranslateFn = (key: string) => string;

export interface TimelineCapability {
  id: string;
  displayName: string;
  description: string;
  sources: SensorSourceStatusItem[];
  enabledCount: number;
  attentionCount: number;
  lastSyncAt: number | string | null | undefined;
}

export const getTimelineCapabilityId = (source: SensorSourceStatusItem): string =>
  source.capability_id || source.source_name;

export const getTimelineCapabilityDisplayName = (
  t: TimelineTranslateFn,
  source: SensorSourceStatusItem
): string =>
  source.capability_display_name_translated
  || source.capability_display_name
  || getTimelineSourceDisplayName(t, source);

export const getTimelineCapabilityDescription = (
  t: TimelineTranslateFn,
  source: SensorSourceStatusItem
): string =>
  source.capability_description_translated
  || source.capability_description
  || getTimelineSourceDescription(t, source);

export const getTimelineEntryDisplayName = (
  t: TimelineTranslateFn,
  source: SensorSourceStatusItem
): string =>
  source.entry_display_name_translated
  || source.entry_display_name
  || getTimelineSourceDisplayName(t, source);

export const getTimelineEntryDescription = (
  t: TimelineTranslateFn,
  source: SensorSourceStatusItem
): string =>
  source.entry_description_translated
  || source.entry_description
  || getTimelineSourceDescription(t, source);

const timestampValue = (value: number | string | null | undefined): number => {
  if (value == null || value === '') {
    return 0;
  }
  if (typeof value === 'number') {
    return value;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const buildTimelineCapabilities = (
  t: TimelineTranslateFn,
  statuses: SensorSourceStatusItem[]
): TimelineCapability[] => {
  const grouped = new Map<string, TimelineCapability>();

  for (const source of statuses) {
    const capabilityId = getTimelineCapabilityId(source);
    const existing = grouped.get(capabilityId);
    const capability = existing ?? {
      id: capabilityId,
      displayName: getTimelineCapabilityDisplayName(t, source),
      description: getTimelineCapabilityDescription(t, source),
      sources: [],
      enabledCount: 0,
      attentionCount: 0,
      lastSyncAt: null,
    };
    capability.sources.push(source);
    if (source.enabled) {
      capability.enabledCount += 1;
    }
    if (source.last_error || source.status === 'error' || source.available === false) {
      capability.attentionCount += 1;
    }
    if (timestampValue(source.last_sync_at) > timestampValue(capability.lastSyncAt)) {
      capability.lastSyncAt = source.last_sync_at;
    }
    grouped.set(capabilityId, capability);
  }

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
  return [...grouped.values()]
    .map((capability) => ({
      ...capability,
      sources: [...capability.sources].sort((left, right) => {
        const leftOrder = Number(left.entry_order ?? 999);
        const rightOrder = Number(right.entry_order ?? 999);
        if (leftOrder !== rightOrder) {
          return leftOrder - rightOrder;
        }
        return collator.compare(
          getTimelineEntryDisplayName(t, left),
          getTimelineEntryDisplayName(t, right)
        );
      }),
    }))
    .sort((left, right) => collator.compare(left.displayName, right.displayName));
};
