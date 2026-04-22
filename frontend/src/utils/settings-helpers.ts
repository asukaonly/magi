/**
 * Settings page helper functions.
 */

import i18n from '@/i18n';
import type { LanguageCode } from '@/api/modules/config';
import { buildPluginFieldValueMap, type PluginPackageState } from '@/api/modules/plugins';
import type { SensorSourceStatusItem } from '@/api/modules/sensors';
import type { ToolConfig } from '@/api/modules/tools';
import type { PluginDraftMap, ToolDraftMap } from '@/types/settings';
import { LANGUAGE_STORAGE_KEY } from '@/constants/settings';

// ============================================================================
// Serialization
// ============================================================================

export const serialize = (value: unknown): string => JSON.stringify(value);

// ============================================================================
// Language Helpers
// ============================================================================

const toI18nLanguage = (language: LanguageCode): string =>
  language === 'zh' ? 'zh-CN' : 'en';

export const persistLanguageSelection = (language: LanguageCode): void => {
  const nextLanguage = toI18nLanguage(language);
  localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  document.documentElement.lang = nextLanguage;
};

export const previewLanguageSelection = async (language: LanguageCode): Promise<void> => {
  const nextLanguage = toI18nLanguage(language);
  document.documentElement.lang = nextLanguage;
  await i18n.changeLanguage(nextLanguage);
};

// ============================================================================
// Plugin Draft Helpers
// ============================================================================

const collectPluginSurfaceFields = (
  plugin: PluginPackageState,
  surfaces: string[]
) =>
  plugin.contributions
    .flatMap((contribution) => contribution.fields)
    .filter((field) => surfaces.includes(field.surface));

export const buildPluginDraftSnapshotFromPackages = (
  plugins: PluginPackageState[]
): PluginDraftMap =>
  Object.fromEntries(
    plugins.map((plugin) => [
      plugin.manifest.plugin_id,
      buildPluginFieldValueMap(
        collectPluginSurfaceFields(plugin, ['extensions']),
        plugin.current_settings
      ),
    ])
  );

export const buildPluginDraftSnapshotFromSensors = (
  statuses: SensorSourceStatusItem[]
): PluginDraftMap =>
  statuses.reduce<PluginDraftMap>((acc, source) => {
    const current = acc[source.plugin_id] || {};
    for (const field of source.fields) {
      current[field.key] = source.current_settings[field.key] ?? field.default;
    }
    const activationFlow = source.activation_flow;
    if (activationFlow) {
      current[activationFlow.enabled_key] =
        source.current_settings[activationFlow.enabled_key] ?? source.enabled;
      current[activationFlow.configured_key] =
        source.current_settings[activationFlow.configured_key] ?? false;
      for (const field of activationFlow.fields) {
        current[field.key] = source.current_settings[field.key] ?? field.default;
      }
    }
    acc[source.plugin_id] = current;
    return acc;
  }, {});

export const mergeDraftMaps = (
  current: PluginDraftMap,
  incoming: PluginDraftMap,
  options: { preserveExisting: boolean }
): PluginDraftMap => {
  const next = structuredClone(current);
  for (const [pluginId, values] of Object.entries(incoming)) {
    next[pluginId] = next[pluginId] || {};
    for (const [key, value] of Object.entries(values)) {
      if (options.preserveExisting && key in next[pluginId]) {
        continue;
      }
      next[pluginId][key] = value;
    }
  }
  return next;
};

// ============================================================================
// Tool Draft Helpers
// ============================================================================

export const buildToolDraftSnapshot = (tools: ToolConfig[]): ToolDraftMap =>
  Object.fromEntries(
    tools.map((tool) => [
      tool.name,
      {
        enabled: tool.enabled,
        values: structuredClone(tool.current_values || {}),
      },
    ])
  );

// ============================================================================
// Diff Helpers
// ============================================================================

export const diffFlatMaps = (
  saved: Record<string, unknown>,
  draft: Record<string, unknown>
): Record<string, unknown> => {
  const keys = new Set([...Object.keys(saved), ...Object.keys(draft)]);
  const updates: Record<string, unknown> = {};
  for (const key of keys) {
    if (serialize(saved[key] ?? null) !== serialize(draft[key] ?? null)) {
      updates[key] = draft[key];
    }
  }
  return updates;
};
