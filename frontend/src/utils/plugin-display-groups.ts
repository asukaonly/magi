import type {
  PluginCapability,
  PluginDisplayGroupSpec,
  PluginPackageState,
  PluginRegistryEntry,
} from '@/api/modules/plugins';

export interface InstalledPluginDisplayItem {
  kind: 'single' | 'group';
  id: string;
  group?: PluginDisplayGroupSpec;
  plugins: PluginPackageState[];
  primary: PluginPackageState;
  order: number;
}

export interface MarketplacePluginDisplayItem {
  kind: 'single' | 'group';
  id: string;
  group?: PluginDisplayGroupSpec;
  entries: PluginRegistryEntry[];
  primary: PluginRegistryEntry;
  order: number;
}

export function localizedPluginText(
  base: string,
  i18nMap: Record<string, string> | undefined,
  lang: string,
): string {
  if (!i18nMap) return base;
  return i18nMap[lang] ?? i18nMap[lang.split('-')[0]] ?? base;
}

const displayItemId = (groupId: string): string => groupId.replace(/_/g, '-');

const groupSortValue = (group?: PluginDisplayGroupSpec | null): number =>
  Number.isFinite(group?.order) ? Number(group?.order) : 999;

const memberSortValue = (group?: PluginDisplayGroupSpec | null): number =>
  Number.isFinite(group?.member_order) ? Number(group?.member_order) : 999;

export function buildInstalledPluginDisplayItems(
  plugins: PluginPackageState[],
): InstalledPluginDisplayItem[] {
  const groupedPluginIds = new Set<string>();
  const grouped = new Map<string, Array<{ plugin: PluginPackageState; index: number }>>();

  plugins.forEach((plugin, index) => {
    const group = plugin.manifest.display_group;
    if (!group?.id) return;
    const members = grouped.get(group.id) ?? [];
    members.push({ plugin, index });
    grouped.set(group.id, members);
    groupedPluginIds.add(plugin.manifest.plugin_id);
  });

  const items: InstalledPluginDisplayItem[] = [];
  for (const [groupId, members] of grouped.entries()) {
    const sortedMembers = [...members].sort((left, right) => {
      const leftOrder = memberSortValue(left.plugin.manifest.display_group);
      const rightOrder = memberSortValue(right.plugin.manifest.display_group);
      return leftOrder === rightOrder ? left.index - right.index : leftOrder - rightOrder;
    });
    const pluginsInGroup = sortedMembers.map((member) => member.plugin);
    const group = pluginsInGroup[0]?.manifest.display_group;
    if (!group) continue;
    items.push({
      kind: 'group',
      id: displayItemId(groupId),
      group,
      plugins: pluginsInGroup,
      primary: pluginsInGroup[0],
      order: Math.min(...members.map((member) => member.index), groupSortValue(group)),
    });
  }

  plugins.forEach((plugin, index) => {
    if (groupedPluginIds.has(plugin.manifest.plugin_id)) return;
    items.push({
      kind: 'single',
      id: plugin.manifest.plugin_id,
      plugins: [plugin],
      primary: plugin,
      order: index,
    });
  });

  return items.sort((a, b) => a.order - b.order);
}

export function buildMarketplacePluginDisplayItems(
  entries: PluginRegistryEntry[],
): MarketplacePluginDisplayItem[] {
  const groupedPluginIds = new Set<string>();
  const grouped = new Map<string, Array<{ entry: PluginRegistryEntry; index: number }>>();

  entries.forEach((entry, index) => {
    const group = entry.display_group;
    if (!group?.id) return;
    const members = grouped.get(group.id) ?? [];
    members.push({ entry, index });
    grouped.set(group.id, members);
    groupedPluginIds.add(entry.plugin_id);
  });

  const items: MarketplacePluginDisplayItem[] = [];
  for (const [groupId, members] of grouped.entries()) {
    const sortedMembers = [...members].sort((left, right) => {
      const leftOrder = memberSortValue(left.entry.display_group);
      const rightOrder = memberSortValue(right.entry.display_group);
      return leftOrder === rightOrder ? left.index - right.index : leftOrder - rightOrder;
    });
    const entriesInGroup = sortedMembers.map((member) => member.entry);
    const group = entriesInGroup[0]?.display_group;
    if (!group) continue;
    items.push({
      kind: 'group',
      id: displayItemId(groupId),
      group,
      entries: entriesInGroup,
      primary: entriesInGroup[0],
      order: Math.min(...members.map((member) => member.index), groupSortValue(group)),
    });
  }

  entries.forEach((entry, index) => {
    if (groupedPluginIds.has(entry.plugin_id)) return;
    items.push({
      kind: 'single',
      id: entry.plugin_id,
      entries: [entry],
      primary: entry,
      order: index,
    });
  });

  return items.sort((a, b) => a.order - b.order);
}

export function getInstalledItemName(item: InstalledPluginDisplayItem, lang: string): string {
  if (item.group) {
    return localizedPluginText(item.group.name, item.group.name_i18n, lang);
  }
  return item.primary.manifest.name;
}

export function getInstalledItemDescription(item: InstalledPluginDisplayItem, lang: string): string {
  if (item.group) {
    return localizedPluginText(item.group.description, item.group.description_i18n, lang);
  }
  return item.primary.manifest.description;
}

export function getMarketplaceItemName(item: MarketplacePluginDisplayItem, lang: string): string {
  if (item.group) {
    return localizedPluginText(item.group.name, item.group.name_i18n, lang);
  }
  return localizedPluginText(item.primary.name, item.primary.name_i18n, lang);
}

export function getMarketplaceItemDescription(item: MarketplacePluginDisplayItem, lang: string): string {
  if (item.group) {
    return localizedPluginText(item.group.description, item.group.description_i18n, lang);
  }
  return localizedPluginText(item.primary.description, item.primary.description_i18n, lang);
}

export function getMarketplaceItemIcon(item: MarketplacePluginDisplayItem): string | undefined {
  return item.group?.icon || item.primary.icon;
}

export function getMarketplaceItemContributionTypes(item: MarketplacePluginDisplayItem): string[] {
  return [...new Set(item.entries.flatMap((entry) => entry.contribution_types))];
}

export function getMarketplaceItemCapabilities(item: MarketplacePluginDisplayItem): PluginCapability[] {
  const seen = new Set<string>();
  const capabilities: PluginCapability[] = [];
  for (const capability of item.entries.flatMap((entry) => entry.capabilities ?? [])) {
    const key = JSON.stringify({
      capability: capability.capability,
      scope: capability.scope ?? [],
      optional: capability.optional ?? false,
      reason: capability.reason ?? '',
      reason_i18n: capability.reason_i18n ?? {},
    });
    if (seen.has(key)) continue;
    seen.add(key);
    capabilities.push(capability);
  }
  return capabilities;
}

export function getMarketplaceItemMemberNames(item: MarketplacePluginDisplayItem, lang: string): string[] {
  if (item.kind !== 'group') return [];
  return item.entries.map((entry) => getMarketplaceEntryMemberName(entry, lang));
}

export function getMarketplaceEntryMemberName(entry: PluginRegistryEntry, lang: string): string {
  const group = entry.display_group;
  return localizedPluginText(
    group?.member_label || entry.name.replace(/\s*History$/i, ''),
    group?.member_label_i18n || entry.name_i18n,
    lang,
  )
    .replace(/\s*浏览(?:器)?历史$/u, '')
    .trim();
}

export function getInstalledItemMemberNames(item: InstalledPluginDisplayItem, lang: string): string[] {
  if (item.kind !== 'group') return [];
  return item.plugins.map((plugin) => {
    const group = plugin.manifest.display_group;
    return localizedPluginText(
      group?.member_label || plugin.manifest.name.replace(/\s*History$/i, ''),
      group?.member_label_i18n,
      lang,
    )
      .replace(/\s*浏览(?:器)?历史$/u, '')
      .trim();
  });
}
