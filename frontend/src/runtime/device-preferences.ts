import { z } from 'zod';

const storageKey = 'magi.device.preferences.v1';
const schema = z.object({
  close_to_tray_enabled: z.boolean(),
  desktop_notifications_enabled: z.boolean(),
  desktop_notification_previews_enabled: z.boolean(),
  auto_start_enabled: z.boolean(),
  start_minimized: z.boolean(),
  skip_quit_confirmation: z.boolean(),
});
export type DevicePreferences = z.infer<typeof schema>;
export const DEFAULT_DEVICE_PREFERENCES: DevicePreferences = {
  close_to_tray_enabled: true,
  desktop_notifications_enabled: true,
  desktop_notification_previews_enabled: true,
  auto_start_enabled: false,
  start_minimized: false,
  skip_quit_confirmation: false,
};

export function readDevicePreferences(): DevicePreferences {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw) return schema.parse(JSON.parse(raw));
  } catch { /* Invalid device state is replaced with safe product defaults. */ }
  return { ...DEFAULT_DEVICE_PREFERENCES };
}

export function writeDevicePreferences(value: DevicePreferences): void {
  localStorage.setItem(storageKey, JSON.stringify(schema.parse(value)));
}

/** Remove device fields before transmitting a center configuration. */
export function withoutDevicePreferences<T extends Partial<DevicePreferences>>(value: T): Omit<T, keyof DevicePreferences> {
  const { close_to_tray_enabled: _tray, desktop_notifications_enabled: _notifications,
    desktop_notification_previews_enabled: _previews, auto_start_enabled: _autostart,
    start_minimized: _minimized, skip_quit_confirmation: _quit, ...center } = value;
  return center;
}
