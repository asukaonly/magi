import type { SourceStatusItem } from '@/api/modules/sources';
import type { PluginRegistryEntry } from '@/api/modules/plugins';
import { localizedPluginText } from '@/utils/plugin-display-groups';
import { getTimelineSourceDescription, getTimelineSourceDisplayName } from '@/utils/timeline-source-copy';

type TimelineTranslateFn = (key: string) => string;

export interface TimelineCapability {
  id: string;
  displayName: string;
  description: string;
  sources: SourceStatusItem[];
  enabledCount: number;
  attentionCount: number;
  lastSyncAt: number | string | null | undefined;
}

export interface TimelineAvailableEntry {
  capabilityId: string;
  capabilityDisplayName: string;
  capabilityDescription: string;
  pluginId: string;
  icon?: string;
  entryId: string;
  entryDisplayName: string;
  entryDescription: string;
  entryOrder: number;
  version: string;
  official: boolean;
  capabilities: PluginRegistryEntry['capabilities'];
  executionMode: PluginRegistryEntry['execution_mode'];
  installFingerprint: string;
}

export const getTimelineCapabilityId = (source: SourceStatusItem): string =>
  source.capability_id || source.source_name;

export const getTimelineCapabilityDisplayName = (
  t: TimelineTranslateFn,
  source: SourceStatusItem
): string =>
  source.capability_display_name_translated
  || source.capability_display_name
  || getTimelineSourceDisplayName(t, source);

export const getTimelineCapabilityDescription = (
  t: TimelineTranslateFn,
  source: SourceStatusItem
): string =>
  source.capability_description_translated
  || source.capability_description
  || getTimelineSourceDescription(t, source);

export const getTimelineEntryDisplayName = (
  t: TimelineTranslateFn,
  source: SourceStatusItem
): string =>
  source.entry_display_name_translated
  || source.entry_display_name
  || getTimelineSourceDisplayName(t, source);

export const getTimelineEntryDescription = (
  t: TimelineTranslateFn,
  source: SourceStatusItem
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
  statuses: SourceStatusItem[]
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
    const retrying = source.status === 'retrying' || source.sync_activity?.status === 'retrying';
    if (
      (source.last_error && !retrying)
      || source.status === 'error'
      || source.available === false
    ) {
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

const currentDesktopPlatform = (): 'macos' | 'windows' | null => {
  if (typeof navigator === 'undefined') {
    return null;
  }
  if (/mac/i.test(navigator.userAgent)) {
    return 'macos';
  }
  if (/win/i.test(navigator.userAgent)) {
    return 'windows';
  }
  return null;
};

const registryEntrySupportedOnCurrentPlatform = (entry: PluginRegistryEntry): boolean => {
  const platforms = entry.platforms ?? [];
  if (platforms.length === 0) {
    return true;
  }
  const platform = currentDesktopPlatform();
  return platform == null || platforms.includes(platform);
};

export const buildTimelineAvailableEntries = (
  registryEntries: PluginRegistryEntry[],
  installedPluginIds: Set<string>,
  language: string,
  installFingerprint: string | null = null,
): TimelineAvailableEntry[] => {
  if (!installFingerprint) {
    return [];
  }
  const entries = registryEntries
    .filter((entry) => {
      const group = entry.display_group;
      if (!group?.id) {
        return false;
      }
      if (!entry.contribution_types.includes('source')) {
        return false;
      }
      if (entry.installed || installedPluginIds.has(entry.plugin_id)) {
        return false;
      }
      return registryEntrySupportedOnCurrentPlatform(entry);
    })
    .map((entry) => {
      const group = entry.display_group!;
      return {
        capabilityId: group.id,
        capabilityDisplayName: localizedPluginText(group.name, group.name_i18n, language),
        capabilityDescription: localizedPluginText(group.description, group.description_i18n, language),
        pluginId: entry.plugin_id,
        icon: entry.icon || group.icon,
        entryId: group.member_label || entry.plugin_id,
        entryDisplayName: localizedPluginText(
          group.member_label || entry.name,
          group.member_label_i18n || entry.name_i18n,
          language
        ),
        entryDescription: localizedPluginText(entry.description, entry.description_i18n, language),
        entryOrder: Number(group.member_order ?? 999),
        version: entry.version,
        official: entry.official,
        capabilities: entry.capabilities,
        executionMode: entry.execution_mode,
        installFingerprint,
      } satisfies TimelineAvailableEntry;
    });

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
  return entries.sort((left, right) => {
    if (left.capabilityId !== right.capabilityId) {
      return collator.compare(left.capabilityDisplayName, right.capabilityDisplayName);
    }
    if (left.entryOrder !== right.entryOrder) {
      return left.entryOrder - right.entryOrder;
    }
    return collator.compare(left.entryDisplayName, right.entryDisplayName);
  });
};
