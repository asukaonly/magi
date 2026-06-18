import type {
  PluginCapability,
  PluginPackageState,
  PluginRegistryEntry,
} from '@/api/modules/plugins';

export interface PluginDisplayGroupDefinition {
  id: string;
  pluginIds: string[];
  name: string;
  name_i18n: Record<string, string>;
  description: string;
  description_i18n: Record<string, string>;
  icon: string;
}

export const PLUGIN_DISPLAY_GROUPS: PluginDisplayGroupDefinition[] = [
  {
    id: 'browser-history',
    pluginIds: ['chrome-history', 'safari-history', 'firefox-history', 'edge-history'],
    name: 'Browser History',
    name_i18n: { 'zh-CN': '浏览历史' },
    description: 'Manage browser history sources from Chrome, Safari, Firefox, and Edge.',
    description_i18n: {
      'zh-CN': '统一管理 Chrome、Safari、Firefox、Edge 等浏览器历史入口。',
    },
    icon: 'lucide:globe',
  },
];

export interface InstalledPluginDisplayItem {
  kind: 'single' | 'group';
  id: string;
  group?: PluginDisplayGroupDefinition;
  plugins: PluginPackageState[];
  primary: PluginPackageState;
  order: number;
}

export interface MarketplacePluginDisplayItem {
  kind: 'single' | 'group';
  id: string;
  group?: PluginDisplayGroupDefinition;
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

export function getPluginDisplayGroupForPluginId(pluginId: string): PluginDisplayGroupDefinition | null {
  return PLUGIN_DISPLAY_GROUPS.find((group) => group.pluginIds.includes(pluginId)) ?? null;
}

export function buildInstalledPluginDisplayItems(
  plugins: PluginPackageState[],
): InstalledPluginDisplayItem[] {
  const groupedPluginIds = new Set<string>();
  const items: InstalledPluginDisplayItem[] = [];

  for (const group of PLUGIN_DISPLAY_GROUPS) {
    const members = plugins.filter((plugin) => group.pluginIds.includes(plugin.manifest.plugin_id));
    if (members.length === 0) continue;
    members.forEach((plugin) => groupedPluginIds.add(plugin.manifest.plugin_id));
    items.push({
      kind: 'group',
      id: group.id,
      group,
      plugins: members,
      primary: members[0],
      order: plugins.findIndex((plugin) => group.pluginIds.includes(plugin.manifest.plugin_id)),
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
  const items: MarketplacePluginDisplayItem[] = [];

  for (const group of PLUGIN_DISPLAY_GROUPS) {
    const members = entries.filter((entry) => group.pluginIds.includes(entry.plugin_id));
    if (members.length === 0) continue;
    members.forEach((entry) => groupedPluginIds.add(entry.plugin_id));
    items.push({
      kind: 'group',
      id: group.id,
      group,
      entries: members,
      primary: members[0],
      order: entries.findIndex((entry) => group.pluginIds.includes(entry.plugin_id)),
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
  return item.entries.map((entry) =>
    localizedPluginText(entry.name.replace(/\s*History$/i, ''), entry.name_i18n, lang)
      .replace(/\s*浏览历史$/u, '')
      .trim()
  );
}

export function getInstalledItemMemberNames(item: InstalledPluginDisplayItem, lang: string): string[] {
  if (item.kind !== 'group') return [];
  return item.plugins.map((plugin) =>
    localizedPluginText(plugin.manifest.name.replace(/\s*History$/i, ''), undefined, lang)
      .replace(/\s*浏览历史$/u, '')
      .trim()
  );
}
