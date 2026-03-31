/**
 * Custom hooks barrel export.
 */

export {
  usePersonality,
  type UsePersonalityOptions,
  type UsePersonalityReturn,
  type PersonalityInfo,
  CONFIDENCE_OPTIONS,
  parseLines,
  toLines,
  getInitials,
  normalizeTransition,
  mergeConfig,
} from './usePersonality';

export { useMemory, formatTimestamp, type UseMemoryReturn } from './useMemory';

export { useSettings, type UseSettingsReturn } from './useSettings';

// Re-export commonly used hooks from other locations for convenience
export { useThemeStore as useTheme, type ThemeMode } from '@/stores/theme';
export { useRealtime } from '@/realtime/provider';
