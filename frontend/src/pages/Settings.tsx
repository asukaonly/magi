/**
 * Settings page re-export.
 *
 * The settings content component lives in components/settings/SettingsContent
 * and is rendered inside SettingsCenterDialog rather than as a standalone route.
 * This re-export preserves backward compatibility for existing consumers.
 */
export { SettingsPage } from '@/components/settings/SettingsContent';
